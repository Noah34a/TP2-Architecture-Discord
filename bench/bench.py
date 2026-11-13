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
cs = cassandra_session("discord")
SELECT_CS = cs.prepare("SELECT message_id FROM messages_par_salon WHERE salon_id = ? AND bucket = ? LIMIT ?")
SELECT_FENETRES = cs.prepare("SELECT bucket FROM fenetres_par_salon WHERE salon_id = ?")
NEO = neo.session()

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
    raise NotImplementedError("À FAIRE — SET avec expiration")

def b2r_pg(serveur):
    return pg.execute("""SELECT count(*) FROM app.membre m JOIN app.presence p ON p.utilisateur_id = m.utilisateur_id
                         WHERE m.serveur_id = %s AND p.vu_le > now() - interval '5 minutes'""", (serveur,)).fetchone()[0]


def b2r_redis(serveur):
    raise NotImplementedError("À FAIRE — SMEMBERS + MGET")

# ---------- B3. Suggestions : serveurs où au moins 2 de mes amis sont membres et pas moi ----------
def b3_pg(uid):
    return pg.execute("""
        SELECT m.serveur_id, count(*) AS n
        FROM (SELECT utilisateur_b AS ami FROM app.amitie WHERE utilisateur_a = %(u)s
              UNION ALL SELECT utilisateur_a FROM app.amitie WHERE utilisateur_b = %(u)s) f
        JOIN app.membre m ON m.utilisateur_id = f.ami
        WHERE m.serveur_id NOT IN (SELECT serveur_id FROM app.membre WHERE utilisateur_id = %(u)s)
        GROUP BY m.serveur_id HAVING count(*) >= 2 ORDER BY n DESC, m.serveur_id LIMIT 5""", {"u": uid}).fetchall()


def b3_neo(uid):
    raise NotImplementedError("À FAIRE — Cypher")

# ---------- B3 bis. Amis d'amis : personnes que je ne connais pas, classées par nombre d'amis communs ----------
def b3bis_pg(uid):
    raise NotImplementedError("À FAIRE — SQL, 2 sauts")

def b3bis_neo(uid):
    raise NotImplementedError("À FAIRE — Cypher, 2 sauts")

# ---------- B4. Activité d'un serveur : messages et auteurs distincts par jour, octobre 2026 ----------
def b4_pg_normalise(serveur):
    raise NotImplementedError("À FAIRE — SQL")

def b4_pg_vue(serveur):
    raise NotImplementedError("À FAIRE — lire la vue matérialisée")

def b4_mongo(serveur):
    raise NotImplementedError("À FAIRE — aggregate")

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--mission3", action="store_true", help="Benchmark B1 seulement (mission 3)")
    args = ap.parse_args()
    n = args.n
    rnd = random.Random(1)

    # ---- Contrôles de cohérence AVANT tout chronométrage (Question 5.2 : à compléter pour chaque cas implémenté) ----
    # Mesure 5b : comparer effectivement les 50 memes Snowflakes, dans le meme ordre.
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
    # Les asserts des cas B2 / B3 / B4 seront completes pour les missions 5 et 6.

    lignes = []

    def mesure(cas, moteur, f, entrees):
        try:
            p50, p95 = chrono(f, entrees)
            lignes.append(f"| {cas} | {moteur} | {p50:.2f} | {p95:.2f} |")
        except NotImplementedError:
            lignes.append(f"| {cas} | {moteur} | à faire | à faire |")

    for nom, salon in (("chaud", SALON_CHAUD), ("moyen", SALON_MOYEN), ("clairsemé", SALON_CLAIRSEME)):
        e = [(salon,)] * n
        cas = f"B1 50 derniers messages, salon {nom}"
        mesure(cas, "PostgreSQL", b1_pg, e)
        mesure(cas, "MongoDB", b1_mongo, e)
        mesure(cas, "Cassandra", b1_cassandra, e)
        mesure(cas, "Cassandra + fenetres non vides (bonus)", b1_cassandra_fenetres, e)
    if args.mission3:
        print(f"| Cas | Moteur | p50 (ms) | p95 (ms) |   (n = {n})\n|---|---|---:|---:|")
        print("\n".join(lignes))
        return
    e = [(rnd.randint(1, NB_UTILISATEURS),) for _ in range(n)]
    mesure("B2a présence : écriture", "PostgreSQL", b2w_pg, e)
    mesure("B2a présence : écriture", "Redis", b2w_redis, e)
    e = [(SERVEUR_TEST,)] * n
    mesure("B2b présence : en ligne dans un serveur (478 membres)", "PostgreSQL", b2r_pg, e)
    mesure("B2b présence : en ligne dans un serveur (478 membres)", "Redis", b2r_redis, e)
    e = [(rnd.randint(1, NB_UTILISATEURS),) for _ in range(n)]
    mesure("B3 serveurs suggérés (amis)", "PostgreSQL", b3_pg, e)
    mesure("B3 serveurs suggérés (amis)", "Neo4j", b3_neo, e)
    e = [(rnd.randint(1, NB_UTILISATEURS),) for _ in range(30)]
    mesure("B3 bis amis d'amis (n=30)", "PostgreSQL", b3bis_pg, e)
    mesure("B3 bis amis d'amis (n=30)", "Neo4j", b3bis_neo, e)
    e = [(SERVEUR_TEST,)] * n
    mesure("B4 activité d'un serveur (30 j)", "PostgreSQL normalisé", b4_pg_normalise, e)
    mesure("B4 activité d'un serveur (30 j)", "PostgreSQL vue matérialisée", b4_pg_vue, e)
    mesure("B4 activité d'un serveur (30 j)", "MongoDB (aggregate)", b4_mongo, e)

    print(f"| Cas | Moteur | p50 (ms) | p95 (ms) |   (n = {n})\n|---|---|---:|---:|")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
