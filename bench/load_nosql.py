"""Migration TP2 : PostgreSQL -> MongoDB / Cassandra (+ Redis / Neo4j si demande).

Exemples, depuis bench/ :
  python load_nosql.py --messages-seulement
  python load_nosql.py --sans-cassandra --messages-seulement
  python load_nosql.py                 # charge aussi Redis et Neo4j (mission 5)

Les collections et tables destination de messages sont remises a zero a chaque
execution : le TP suppose une migration complete et reproductible.
"""
import argparse
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from cassandra.concurrent import execute_concurrent_with_args
from cassandra.query import UNSET_VALUE
from pymongo import ASCENDING, DESCENDING

from common import bucket_de, cassandra_session, mongo_db, neo_driver, pg_conn, redis_conn

ap = argparse.ArgumentParser()
ap.add_argument("--sans-cassandra", action="store_true")
ap.add_argument("--messages-seulement", action="store_true", help="Ne pas charger Redis / Neo4j (mission 3)")
ap.add_argument("--sans-verification-complete", action="store_true", help="Ne pas relire chaque partition Cassandra")
args = ap.parse_args()
pg = pg_conn()


def lots(curseur, taille=1000):
    while True:
        rows = curseur.fetchmany(taille)
        if not rows:
            return
        yield rows


# ---------- MongoDB : etat 2015, documents + index composes ----------
db = mongo_db()
coll = db["messages"]
coll.drop()  # donnees de TP : evite des doublons lors des executions repetees

# ---------- Cassandra : etat 2017, salon + fenetre de 10 jours ----------
cs = None
if not args.sans_cassandra:
    # Executer d'abord cql/01_schema.cql apres le demarrage de Cassandra.
    cs = cassandra_session("discord")
    cs.execute("TRUNCATE discord.messages_par_salon")
    cs.execute("TRUNCATE discord.fenetres_par_salon")
    ins_cs = cs.prepare("""
        INSERT INTO discord.messages_par_salon
        (salon_id, bucket, message_id, auteur_id, contenu, envoye_le, pieces_jointes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """)
    ins_fenetre = cs.prepare("""
        INSERT INTO discord.fenetres_par_salon (salon_id, bucket) VALUES (?, ?)
    """)

requete = """
    SELECT m.id, m.salon_id, s.serveur_id, m.auteur_id,
           m.contenu, m.envoye_le, m.modifie_le, m.pieces_jointes
    FROM app.message AS m
    JOIN app.salon AS s ON s.id = m.salon_id
    ORDER BY m.id
"""
attendus = pg.execute("SELECT COUNT(*) FROM app.message").fetchone()[0]
partitions = Counter()
nb_mongo = 0
nb_cassandra = 0

# La transaction explicite permet un curseur cote serveur meme si pg_conn()
# est configure avec autocommit=True. On ne charge pas 300 000 lignes en RAM.
with pg.transaction():
    with pg.cursor(name="export_messages_tp2") as curseur:
        curseur.execute(requete)
        for lot in lots(curseur):
            documents, cql_args = [], []
            for mid, salon, serveur, auteur, contenu, envoye, modifie, pj in lot:
                mid, salon, serveur, auteur = int(mid), int(salon), int(serveur), int(auteur)
                d = {
                    "_id": mid, "salon_id": salon, "serveur_id": serveur,
                    "auteur_id": auteur, "contenu": contenu, "envoye_le": envoye,
                }
                if modifie is not None:
                    d["modifie_le"] = modifie
                if pj is not None:
                    d["pieces_jointes"] = pj   # objet variable, integre au document
                documents.append(d)

                if cs is not None:
                    b = bucket_de(mid)
                    partitions[(salon, b)] += 1
                    # Ne jamais envoyer None : UNSET_VALUE evite les tombstones.
                    pj_json = json.dumps(pj, ensure_ascii=False) if pj is not None else UNSET_VALUE
                    cql_args.append((salon, b, mid, auteur, contenu, envoye, pj_json))

            # Ecritures acquittees (ordered=False = pas d'ordre entre documents).
            resultat_mongo = coll.insert_many(documents, ordered=False)
            nb_mongo += len(resultat_mongo.inserted_ids)

            if cs is not None:
                reponses = execute_concurrent_with_args(
                    cs, ins_cs, cql_args, concurrency=32, raise_on_first_error=False
                )
                for ok, details in reponses:
                    if not ok:
                        raise RuntimeError(f"Ecriture Cassandra echouee : {details}")
                    nb_cassandra += 1

            if nb_mongo % 25000 < len(lot):
                print(f"Migration messages : {nb_mongo}/{attendus}", flush=True)

# Les index se construisent apres le chargement massif pour economiser du temps.
coll.create_index([("salon_id", ASCENDING), ("_id", DESCENDING)], name="idx_b1_salon_id")
coll.create_index([("serveur_id", ASCENDING), ("envoye_le", ASCENDING)], name="idx_b4_serveur_date")
compte_mongo = coll.count_documents({})
assert nb_mongo == attendus == compte_mongo, (
    f"Ecart MongoDB : PG={attendus}, ecritures={nb_mongo}, documents={compte_mongo}"
)
print(f"MESURE 5a | PostgreSQL : {attendus} ; MongoDB : {compte_mongo}")

if cs is not None:
    # Cree les fenetres non vides UNE FOIS, sans ecrire a chaque message.
    cles = list(partitions)
    for i in range(0, len(cles), 1000):
        reponses = execute_concurrent_with_args(
            cs, ins_fenetre, cles[i:i + 1000], concurrency=32,
            raise_on_first_error=False
        )
        for ok, details in reponses:
            if not ok:
                raise RuntimeError(f"Fenetre Cassandra non inseree : {details}")

    assert nb_cassandra == attendus, (
        f"Ecart ecritures acquittees Cassandra={nb_cassandra}, PG={attendus}"
    )
    print(f"MESURE 5a | Cassandra : {nb_cassandra} INSERT acquittes ; "
          f"{len(partitions)} partitions non vides")

    if not args.sans_verification_complete:
        # Preuve independante par LECTURES de chaque partition connue, pas
        # SELECT COUNT(*) sur toute la table Cassandra (scan global couteux).
        lire = cs.prepare("""
            SELECT message_id FROM discord.messages_par_salon
            WHERE salon_id = ? AND bucket = ?
        """)

        def verifier(partition):
            lu = sum(1 for _ in cs.execute(lire, partition))
            return partition, lu

        total_lu = 0
        with ThreadPoolExecutor(max_workers=16) as pool:
            for partition, lu in pool.map(verifier, cles):
                attendu = partitions[partition]
                if lu != attendu:
                    raise AssertionError(
                        f"Partition {partition} : Cassandra={lu}, PostgreSQL={attendu}"
                    )
                total_lu += lu
        assert total_lu == attendus
        print(f"MESURE 5a | Cassandra : {total_lu} messages relus dans "
              f"{len(cles)} partitions, toutes conformes a PostgreSQL")
    else:
        print("Verification complete Cassandra non executee (option --sans-verification-complete)")

# ---------- Redis / Neo4j : code fourni, utilise pour la mission 5 ----------
if not args.messages_seulement:
    r = redis_conn()
    r.flushdb()
    rnd = random.Random(7)
    users = [u for (u,) in pg.execute("SELECT id FROM app.utilisateur").fetchall()]
    en_ligne = set(rnd.sample(users, int(len(users) * 0.3)))
    pipe = r.pipeline()
    for u in en_ligne:
        pipe.set(f"presence:{u}", "en_ligne", ex=300)
    for serv, mem in pg.execute("SELECT serveur_id, array_agg(utilisateur_id) FROM app.membre GROUP BY 1").fetchall():
        pipe.sadd(f"membres:{serv}", *mem)
    pipe.execute()
    pg.execute("TRUNCATE app.presence")
    with pg.cursor() as c:
        c.executemany("INSERT INTO app.presence VALUES (%s, now())", [(u,) for u in sorted(en_ligne)])
    print(f"redis     : {r.dbsize()} cles ({len(en_ligne)} presences)")

    drv = neo_driver()
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        s.run("CREATE CONSTRAINT utilisateur_id IF NOT EXISTS FOR (u:Utilisateur) REQUIRE u.id IS UNIQUE").consume()
        s.run("CREATE CONSTRAINT serveur_id IF NOT EXISTS FOR (s:Serveur) REQUIRE s.id IS UNIQUE").consume()
        s.run("UNWIND $ids AS i MERGE (:Utilisateur {id: i})", ids=users).consume()
        ids_serveurs = [x for (x,) in pg.execute("SELECT id FROM app.serveur").fetchall()]
        s.run("UNWIND $ids AS i MERGE (:Serveur {id: i})", ids=ids_serveurs).consume()
        am = pg.execute("SELECT utilisateur_a, utilisateur_b FROM app.amitie").fetchall()
        for i in range(0, len(am), 5000):
            s.run("UNWIND $rows AS r MATCH (a:Utilisateur {id: r[0]}), "
                  "(b:Utilisateur {id: r[1]}) MERGE (a)-[:AMI_DE]->(b)",
                  rows=[list(x) for x in am[i:i + 5000]]).consume()
        me = pg.execute("SELECT utilisateur_id, serveur_id FROM app.membre").fetchall()
        for i in range(0, len(me), 5000):
            s.run("UNWIND $rows AS r MATCH (u:Utilisateur {id: r[0]}), "
                  "(v:Serveur {id: r[1]}) MERGE (u)-[:MEMBRE_DE]->(v)",
                  rows=[list(x) for x in me[i:i + 5000]]).consume()
        for t in ("AMI_DE", "MEMBRE_DE"):
            n = s.run(f"MATCH ()-[r:{t}]->() RETURN count(r) AS n").single()["n"]
            print(f"neo4j     : {n} relations {t}")
