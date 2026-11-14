"""Benchmark : chaque cas d'usage, chaque moteur qui y prétend, mêmes entrées.

Usage : python bench.py [--n 300]
Affiche un tableau Markdown à coller dans MESURES.md. Complétez les fonctions « À FAIRE ». Les moteurs doivent d'abord donner la MÊME réponse (asserts).
"""
import argparse
import random
import statistics
import time
from datetime import datetime, timezone

from common import bucket_de, cassandra_session, mongo_db, neo_driver, pg_conn, redis_conn

pg, mdb, rds, neo = pg_conn(), mongo_db(), redis_conn(), neo_driver()
NEO = neo.session()
cs = None
SELECT_CS = None
SELECT_FENETRES = None


def initialiser_cassandra():
    """Mission 5 seule : inutile de se connecter a Cassandra."""
    global cs, SELECT_CS, SELECT_FENETRES
    cs = cassandra_session("discord")
    SELECT_CS = cs.prepare("SELECT message_id FROM messages_par_salon WHERE salon_id = ? AND bucket = ? LIMIT ?")
    SELECT_FENETRES = cs.prepare("SELECT bucket FROM fenetres_par_salon WHERE salon_id = ?")

SALON_CHAUD, SALON_MOYEN, SALON_CLAIRSEME = 775, 522, 342   # 12 952 / 97 / 1 messages, Mesure 0
DERNIER_BUCKET = bucket_de(pg.execute("SELECT max(id) FROM app.message").fetchone()[0])
CREATION = {s: bucket_de(int(c.timestamp() * 1000 - 1420070400000) << 22)
            for s, c in pg.execute("SELECT id, cree_le FROM app.salon").fetchall()}
NB_UTILISATEURS = pg.execute("SELECT max(id) FROM app.utilisateur").fetchone()[0]
SERVEUR_TEST = 118
DEBUT, FIN = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 31, tzinfo=timezone.utc)


# ---------- B1. Les 50 derniers messages d'un salon ----------
def b1_pg(salon):
    return [x[0] for x in pg.execute("SELECT id FROM app.message WHERE salon_id = %s ORDER BY id DESC LIMIT 50", (salon,)).fetchall()]


def b1_mongo(salon):
    """Index compose MongoDB : (salon_id, _id DESC)."""
    cursor = mdb.messages.find(
        {"salon_id": salon}, {"_id": 1}
    ).sort("_id", -1).limit(50)
    return [int(doc["_id"]) for doc in cursor]


def lire_cs(salon, buckets):
    """Lire 50 IDs par ordre de Snowflake decroissant ; suivi des partitions visitees."""
    ids, visites = [], 0
    for b in buckets:
        visites += 1
        restant = 50 - len(ids)
        # CQL trie deja les messages de chaque fenetre par message_id DESC.
        ids.extend(row.message_id for row in cs.execute(SELECT_CS, (salon, b, restant)))
        if len(ids) >= 50:
            break
    return ids, visites


def b1_cassandra(salon):
    """Version naive : lit aussi les fenetres vides, du plus recent au plus ancien."""
    return lire_cs(salon, range(DERNIER_BUCKET, CREATION[salon] - 1, -1))[0]


def b1_cassandra_fenetres(salon):
    """Correctif facultatif : lire seulement les fenetres connues non vides.

    Le prix du correctif est une table supplementaire a alimenter lors de
    la migration ou des futures ecritures, plus une requete de metadonnees.
    """
    buckets = (r.bucket for r in cs.execute(SELECT_FENETRES, (salon,)))
    return lire_cs(salon, buckets)[0]



# ---------- B2. Présence : battement de cœur (écriture) et « combien sont en ligne dans ce serveur ? » (lecture) ----------
def b2w_pg(uid):
    pg.execute("INSERT INTO app.presence VALUES (%s, now()) ON CONFLICT (utilisateur_id) DO UPDATE SET vu_le = now()", (uid,))


def b2w_redis(uid):
    # Heartbeat : chaque ecriture prolonge la presence de 5 minutes.
    rds.set(f"presence:{uid}", "en_ligne", ex=300)

def b2r_pg(serveur):
    return pg.execute("""SELECT count(*) FROM app.membre m JOIN app.presence p ON p.utilisateur_id = m.utilisateur_id
                         WHERE m.serveur_id = %s AND p.vu_le > now() - interval '5 minutes'""", (serveur,)).fetchone()[0]


def b2r_redis(serveur):
    # L'ensemble donne les membres; MGET recupere leurs presences en une seule lecture.
    membres = rds.smembers(f"membres:{serveur}")
    if not membres:
        return 0
    etats = rds.mget([f"presence:{uid}" for uid in membres])
    return sum(etat is not None for etat in etats)

# ---------- B3. Suggestions : serveurs où au moins 2 de mes amis sont membres et pas moi ----------
def b3_pg(uid):
    return pg.execute("""
        SELECT m.serveur_id, count(*) AS n
        FROM (SELECT utilisateur_b AS ami FROM app.amitie WHERE utilisateur_a = %(u)s
              UNION ALL SELECT utilisateur_a FROM app.amitie WHERE utilisateur_b = %(u)s) f
        JOIN app.membre m ON m.utilisateur_id = f.ami
        WHERE m.serveur_id NOT IN (SELECT serveur_id FROM app.membre WHERE utilisateur_id = %(u)s)
        GROUP BY m.serveur_id HAVING count(*) >= 2 ORDER BY n DESC, m.serveur_id LIMIT 5""", {"u": uid}).fetchall()


CYPHER_B3 = """
MATCH (u:Utilisateur {id: $u})-[:AMI_DE]-(ami:Utilisateur)-[:MEMBRE_DE]->(s:Serveur)
WHERE NOT EXISTS { MATCH (u)-[:MEMBRE_DE]->(s) }
WITH s.id AS serveur_id, count(DISTINCT ami) AS n
WHERE n >= 2
RETURN serveur_id, n
ORDER BY n DESC, serveur_id ASC
LIMIT 5
"""


def b3_neo(uid):
    return [(int(row["serveur_id"]), int(row["n"]))
            for row in NEO.run(CYPHER_B3, u=uid)]

# ---------- B3 bis. Amis d'amis : personnes que je ne connais pas, classées par nombre d'amis communs ----------
SQL_B3BIS = """
WITH mes_amis AS (
    SELECT utilisateur_b AS ami FROM app.amitie WHERE utilisateur_a = %(u)s
    UNION ALL
    SELECT utilisateur_a AS ami FROM app.amitie WHERE utilisateur_b = %(u)s
), candidats AS (
    SELECT a.utilisateur_b AS candidat, m.ami AS commun
    FROM mes_amis m JOIN app.amitie a ON a.utilisateur_a = m.ami
    UNION ALL
    SELECT a.utilisateur_a AS candidat, m.ami AS commun
    FROM mes_amis m JOIN app.amitie a ON a.utilisateur_b = m.ami
)
SELECT c.candidat, COUNT(DISTINCT c.commun) AS nb_amis_communs
FROM candidats c
WHERE c.candidat <> %(u)s
  AND NOT EXISTS (SELECT 1 FROM mes_amis m WHERE m.ami = c.candidat)
GROUP BY c.candidat
ORDER BY nb_amis_communs DESC, c.candidat ASC
LIMIT 5
"""

CYPHER_B3BIS = """
MATCH (u:Utilisateur {id: $u})-[:AMI_DE]-(commun:Utilisateur)-[:AMI_DE]-(candidat:Utilisateur)
WHERE candidat <> u AND NOT EXISTS { MATCH (u)-[:AMI_DE]-(candidat) }
WITH candidat.id AS candidat, count(DISTINCT commun) AS nb_amis_communs
RETURN candidat, nb_amis_communs
ORDER BY nb_amis_communs DESC, candidat ASC
LIMIT 5
"""


def b3bis_pg(uid):
    return [(int(id_), int(n)) for id_, n in pg.execute(SQL_B3BIS, {"u": uid}).fetchall()]


def b3bis_neo(uid):
    return [(int(row["candidat"]), int(row["nb_amis_communs"]))
            for row in NEO.run(CYPHER_B3BIS, u=uid)]

# ---------- B4. Activité d'un serveur : messages et auteurs distincts par jour, octobre 2026 ----------
def b4_pg_normalise(serveur):
    """Activite d'octobre 2026 en UTC, calcul SQL sans denormalisation."""
    rows = pg.execute("""
        SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
               COUNT(*) AS nb_messages,
               COUNT(DISTINCT m.auteur_id) AS nb_auteurs
        FROM app.message AS m
        JOIN app.salon AS s ON s.id = m.salon_id
        WHERE s.serveur_id = %s
          AND m.envoye_le >= TIMESTAMPTZ '2026-10-01 00:00:00+00'
          AND m.envoye_le <  TIMESTAMPTZ '2026-11-01 00:00:00+00'
        GROUP BY (m.envoye_le AT TIME ZONE 'UTC')::date
        ORDER BY jour
    """, (serveur,)).fetchall()
    return [(str(jour), int(messages), int(auteurs))
            for jour, messages, auteurs in rows]

def b4_pg_vue(serveur):
    """Meme activite, pre-agregee dans la vue materialisee Mission 2."""
    rows = pg.execute("""
        SELECT jour, nb_messages, nb_auteurs
        FROM app.activite_serveur_jour
        WHERE serveur_id = %s
          AND jour >= DATE '2026-10-01'
          AND jour <  DATE '2026-11-01'
        ORDER BY jour
    """, (serveur,)).fetchall()
    return [(str(jour), int(messages), int(auteurs))
            for jour, messages, auteurs in rows]

def b4_mongo(serveur):
    """Aggregate MongoDB : messages et auteurs distincts par jour UTC."""
    pipeline = [
        {"$match": {
            "serveur_id": int(serveur),
            "envoye_le": {
                "$gte": datetime(2026, 10, 1, tzinfo=timezone.utc),
                "$lt": datetime(2026, 11, 1, tzinfo=timezone.utc),
            },
        }},
        {"$group": {
            "_id": {"$dateToString": {
                "format": "%Y-%m-%d", "date": "$envoye_le", "timezone": "UTC",
            }},
            "nb_messages": {"$sum": 1},
            "auteurs": {"$addToSet": "$auteur_id"},
        }},
        {"$project": {
            "nb_messages": 1,
            "nb_auteurs": {"$size": "$auteurs"},
        }},
        {"$sort": {"_id": 1}},
    ]
    return [(row["_id"], int(row["nb_messages"]), int(row["nb_auteurs"]))
            for row in mdb.messages.aggregate(pipeline)]


def verifier_b4():
    """Interdit les comparaisons de latence si les moteurs divergent."""
    a = b4_pg_normalise(SERVEUR_TEST)
    b = b4_pg_vue(SERVEUR_TEST)
    c = b4_mongo(SERVEUR_TEST)
    assert a == b == c, (
        f"B4 incoherent sur le serveur {SERVEUR_TEST} : "
        f"PostgreSQL={a[:3]}...; vue={b[:3]}...; MongoDB={c[:3]}..."
    )
    print(f"MESURE 8 OK | B4 serveur {SERVEUR_TEST} | "
          f"{len(a)} jours, {sum(r[1] for r in a)} messages | "
          "PostgreSQL normalise = vue materialisee = MongoDB")

def chrono(f, entrees, echauffement=10):
    for e in entrees[:echauffement]:
        f(*e)
    t = []
    for e in entrees:
        t0 = time.perf_counter()
        f(*e)
        t.append((time.perf_counter() - t0) * 1000)
    t.sort()
    return statistics.median(t), t[int(len(t) * 0.95) - 1]


def verifier_mission5():
    """Les deux moteurs doivent rendre exactement les memes reponses avant les mesures."""
    attentes = {
        "utilisateurs": pg.execute("SELECT count(*) FROM app.utilisateur").fetchone()[0],
        "serveurs": pg.execute("SELECT count(*) FROM app.serveur").fetchone()[0],
        "amities": pg.execute("SELECT count(*) FROM app.amitie").fetchone()[0],
        "membres": pg.execute("SELECT count(*) FROM app.membre").fetchone()[0],
    }
    neo_counts = {
        "utilisateurs": NEO.run("MATCH (n:Utilisateur) RETURN count(n) AS n").single()["n"],
        "serveurs": NEO.run("MATCH (n:Serveur) RETURN count(n) AS n").single()["n"],
        "amities": NEO.run("MATCH ()-[r:AMI_DE]->() RETURN count(r) AS n").single()["n"],
        "membres": NEO.run("MATCH ()-[r:MEMBRE_DE]->() RETURN count(r) AS n").single()["n"],
    }
    assert attentes == neo_counts, (
        f"Neo4j non charge ou incomplet : PG={attentes} ; Neo4j={neo_counts}. "
        "Lancer load_nosql.py --presence-graphe-seulement"
    )
    print(f"M7 OK | Neo4j : {neo_counts['utilisateurs']} utilisateurs, "
          f"{neo_counts['serveurs']} serveurs, {neo_counts['amities']} amities, "
          f"{neo_counts['membres']} appartenances")

    # Controler les cles Redis essentielles et les presences courantes.
    nb_presence_pg = pg.execute("SELECT count(*) FROM app.presence WHERE vu_le > now() - interval '5 minutes'").fetchone()[0]
    nb_presence_redis = len(rds.keys("presence:*"))
    assert nb_presence_pg == nb_presence_redis, (
        f"Presences discordantes (TTL expire ?) : PG={nb_presence_pg}, "
        f"Redis={nb_presence_redis}. Recharger Redis et Neo4j pour ce TP."
    )
    print(f"M7 OK | presences actives : PostgreSQL={nb_presence_pg}, Redis={nb_presence_redis}")

    for serveur in (118, 80, 52, 1):
        pg_n, redis_n = b2r_pg(serveur), b2r_redis(serveur)
        assert pg_n == redis_n, f"B2b serveur {serveur}: PG={pg_n}, Redis={redis_n}"
        print(f"M7 OK | B2b serveur {serveur} : {pg_n} membres en ligne dans les deux moteurs")

    # IDs reproductibles (y compris des utilisateurs dont le resultat est vide).
    ids_test = [1, 42, 118, 5000] + random.Random(7).sample(range(1, NB_UTILISATEURS + 1), 15)
    for uid in ids_test:
        pg_b3, neo_b3 = b3_pg(uid), b3_neo(uid)
        assert pg_b3 == neo_b3, (
            f"B3 utilisateur {uid} : PG={pg_b3}, Neo4j={neo_b3}"
        )
        pg_b3bis, neo_b3bis = b3bis_pg(uid), b3bis_neo(uid)
        assert pg_b3bis == neo_b3bis, (
            f"B3 bis utilisateur {uid} : PG={pg_b3bis}, Neo4j={neo_b3bis}"
        )
    print(f"M7 OK | B3 et B3 bis : {len(ids_test)} utilisateurs testes, listes et scores identiques")


def preuve_ttl():
    """Preuve isolee : n'interfere pas avec les vrais utilisateurs."""
    cle = "preuve:ttl:mission5"
    rds.set(cle, "en_ligne", ex=2)
    ttl_depart = rds.ttl(cle)
    assert rds.get(cle) == "en_ligne"
    time.sleep(2.4)
    assert rds.get(cle) is None and rds.ttl(cle) == -2, "La cle Redis n'a pas expire"
    print(f"M7 OK | TTL Redis : cle temporaire EX 2, TTL initial={ttl_depart}s, "
          "cle absente automatiquement apres 2,4s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--mission3", action="store_true", help="Benchmark B1 seulement")
    ap.add_argument("--mission5", action="store_true", help="B2 / B3 / B3 bis seulement, sans benchmark des messages")
    args = ap.parse_args()
    if args.mission3 and args.mission5:
        ap.error("Choisir --mission3 ou --mission5")
    if args.n < 1:
        ap.error("--n doit etre au moins 1")
    n = args.n
    rnd = random.Random(1)
    lignes = []

    def mesure(cas, moteur, f, entrees):
        try:
            p50, p95 = chrono(f, entrees)
            lignes.append(f"| {cas} | {moteur} | {p50:.2f} | {p95:.2f} |")
        except NotImplementedError:
            lignes.append(f"| {cas} | {moteur} | à faire | à faire |")

    if not args.mission5:
        initialiser_cassandra()
        if not args.mission3:
            verifier_b4()
        for nom, salon in (("chaud", SALON_CHAUD), ("moyen", SALON_MOYEN), ("clairseme", SALON_CLAIRSEME)):
            ids_pg = b1_pg(salon)
            ids_mongo = b1_mongo(salon)
            ids_cs, visites = lire_cs(salon, range(DERNIER_BUCKET, CREATION[salon] - 1, -1))
            ids_opt = b1_cassandra_fenetres(salon)
            assert ids_pg == ids_mongo == ids_cs == ids_opt, (
                f"MESURE 5b ECHEC : salon {salon} : "
                f"PostgreSQL={len(ids_pg)}, MongoDB={len(ids_mongo)}, "
                f"Cassandra={len(ids_cs)}, Cassandra opt={len(ids_opt)}"
            )
            buckets_opti = (r.bucket for r in cs.execute(SELECT_FENETRES, (salon,)))
            _, visites_opti = lire_cs(salon, buckets_opti)
            print(f"MESURE 5b OK | salon {nom} ({salon}) | "
                  f"{len(ids_pg)} IDs identiques et ordonnes | "
                  f"fenetres Cassandra : {visites} naive / {visites_opti} optimisees")

        for nom, salon in (("chaud", SALON_CHAUD), ("moyen", SALON_MOYEN), ("clairsemé", SALON_CLAIRSEME)):
            entrees = [(salon,)] * n
            cas = f"B1 50 derniers messages, salon {nom}"
            mesure(cas, "PostgreSQL", b1_pg, entrees)
            mesure(cas, "MongoDB", b1_mongo, entrees)
            mesure(cas, "Cassandra", b1_cassandra, entrees)
            mesure(cas, "Cassandra + fenetres non vides (bonus)", b1_cassandra_fenetres, entrees)

    if args.mission3:
        print(f"| Cas | Moteur | p50 (ms) | p95 (ms) |   (n = {n})\n|---|---|---:|---:|")
        print("\n".join(lignes))
        return

    # Assertions sur B2b, B3 et B3 bis AVANT tout chronometrage de la Mission 5.
    verifier_mission5()
    preuve_ttl()

    entrees = [(rnd.randint(1, NB_UTILISATEURS),) for _ in range(n)]
    mesure("B2a présence : écriture", "PostgreSQL", b2w_pg, entrees)
    mesure("B2a présence : écriture", "Redis", b2w_redis, entrees)

    # Les ecritures du benchmark viennent de modifier les deux moteurs.
    pg_n, redis_n = b2r_pg(SERVEUR_TEST), b2r_redis(SERVEUR_TEST)
    assert pg_n == redis_n, f"B2b post-ecritures : PG={pg_n} Redis={redis_n}"
    entrees = [(SERVEUR_TEST,)] * n
    mesure("B2b présence : en ligne dans un serveur (478 membres)", "PostgreSQL", b2r_pg, entrees)
    mesure("B2b présence : en ligne dans un serveur (478 membres)", "Redis", b2r_redis, entrees)

    entrees = [(rnd.randint(1, NB_UTILISATEURS),) for _ in range(n)]
    mesure("B3 serveurs suggérés (amis)", "PostgreSQL", b3_pg, entrees)
    mesure("B3 serveurs suggérés (amis)", "Neo4j", b3_neo, entrees)
    entrees = [(rnd.randint(1, NB_UTILISATEURS),) for _ in range(30)]
    mesure("B3 bis amis d'amis (n=30)", "PostgreSQL", b3bis_pg, entrees)
    mesure("B3 bis amis d'amis (n=30)", "Neo4j", b3bis_neo, entrees)

    if not args.mission5:
        entrees = [(SERVEUR_TEST,)] * n
        mesure("B4 activité d'un serveur (30 j)", "PostgreSQL normalisé", b4_pg_normalise, entrees)
        mesure("B4 activité d'un serveur (30 j)", "PostgreSQL vue matérialisée", b4_pg_vue, entrees)
        mesure("B4 activité d'un serveur (30 j)", "MongoDB (aggregate)", b4_mongo, entrees)

    print(f"| Cas | Moteur | p50 (ms) | p95 (ms) |   (n = {n})\n|---|---|---:|---:|")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
