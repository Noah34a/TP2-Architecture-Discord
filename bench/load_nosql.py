"""Alimente MongoDB, Cassandra, Redis et Neo4j à partir de PostgreSQL (source de vérité du TP).

Usage : python load_nosql.py [--sans-cassandra]
"""
import argparse
import json
import random

from cassandra import ConsistencyLevel
from cassandra.concurrent import execute_concurrent_with_args
from cassandra.query import UNSET_VALUE

from common import bucket_de, cassandra_session, mongo_db, neo_driver, pg_conn, redis_conn

ap = argparse.ArgumentParser()
ap.add_argument("--sans-cassandra", action="store_true")
args = ap.parse_args()
pg = pg_conn()


def lots(curseur, taille):
    while True:
        rows = curseur.fetchmany(taille)
        if not rows:
            return
        yield rows


# ---------- MongoDB : la configuration « 2015 » — une collection, un index composé ----------
# À FAIRE : collection `messages`, un document par message (champs de votre choix, mais gardez `_id` = id du message,
#           `salon_id`, `serveur_id`, `auteur_id`, `contenu`, `envoye_le`, et `pieces_jointes` seulement s'il y en a).
#           Créez les index qui servent B1 (derniers messages d'un salon) et B4 (activité d'un serveur par jour).
db = mongo_db()


# ---------- Cassandra : une table = une requête ----------
# À FAIRE : keyspace `discord`, table `messages_par_salon` (clé de partition + clustering issus de VOTRE dossier d'architecture),
#           puis chargement depuis PostgreSQL avec `bucket_de(message_id)` (common.py) et `execute_concurrent_with_args`.
#           Règle apprise à l'article : n'écrivez JAMAIS de NULL (UNSET_VALUE) — un NULL crée une tombstone.
if not args.sans_cassandra:
    cs = cassandra_session()

# ---------- Redis : présence (TTL 5 min) + ensembles de membres ----------
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
print(f"redis     : {r.dbsize()} clés ({len(en_ligne)} présences)")

# ---------- Neo4j : amitiés et appartenances ----------
drv = neo_driver()
with drv.session() as s:
    s.run("MATCH (n) DETACH DELETE n")
    s.run("CREATE CONSTRAINT utilisateur_id IF NOT EXISTS FOR (u:Utilisateur) REQUIRE u.id IS UNIQUE")
    s.run("CREATE CONSTRAINT serveur_id IF NOT EXISTS FOR (s:Serveur) REQUIRE s.id IS UNIQUE")
    s.run("UNWIND $ids AS i MERGE (:Utilisateur {id: i})", ids=users)
    s.run("UNWIND $ids AS i MERGE (:Serveur {id: i})", ids=[x for (x,) in pg.execute("SELECT id FROM app.serveur").fetchall()])
    am = pg.execute("SELECT utilisateur_a, utilisateur_b FROM app.amitie").fetchall()
    for i in range(0, len(am), 5000):
        s.run("UNWIND $rows AS r MATCH (a:Utilisateur {id: r[0]}), (b:Utilisateur {id: r[1]}) MERGE (a)-[:AMI_DE]->(b)", rows=[list(x) for x in am[i:i + 5000]])
    me = pg.execute("SELECT utilisateur_id, serveur_id FROM app.membre").fetchall()
    for i in range(0, len(me), 5000):
        s.run("UNWIND $rows AS r MATCH (u:Utilisateur {id: r[0]}), (v:Serveur {id: r[1]}) MERGE (u)-[:MEMBRE_DE]->(v)", rows=[list(x) for x in me[i:i + 5000]])
    for t in ("AMI_DE", "MEMBRE_DE"):
        print(f"neo4j     : {s.run(f'MATCH ()-[r:{t}]->() RETURN count(r) AS n').single()['n']} relations {t}")
