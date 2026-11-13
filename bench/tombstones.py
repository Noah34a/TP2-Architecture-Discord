"""CORRIGÉ — Rejouer l'incident des « tombstones » (décrit dans l'article Discord de janvier 2017) à petite échelle.

Un salon a eu des millions de messages supprimés, il n'en reste qu'un ; lire ce salon a provoqué des pauses de 10 s.
Ici : 120 000 messages dans UNE partition, on en supprime 119 999 un par un, puis on lit « les 50 derniers ».

Usage : python tombstones.py            (crée l'incident, tente la lecture)
        python tombstones.py --reparer  (supprime la partition d'un coup, au lieu de ligne par ligne)
"""
import sys
import time

from cassandra import ReadFailure
from cassandra.concurrent import execute_concurrent_with_args

from common import cassandra_session

N = 120_000
SALON, BUCKET = -1, 0           # salon fictif : n'interfère pas avec les vraies données
cs = cassandra_session("discord")
cs.default_timeout = 120        # 120 000 écritures en rafale : le délai client par défaut (10 s) saute à la première pause du moteur
ins = cs.prepare("INSERT INTO messages_par_salon (salon_id, bucket, message_id, auteur_id, contenu) VALUES (?,?,?,?,?)")
dele = cs.prepare("DELETE FROM messages_par_salon WHERE salon_id = ? AND bucket = ? AND message_id = ?")


def lire():
    t0 = time.perf_counter()
    try:
        rows = list(cs.execute("SELECT message_id FROM messages_par_salon WHERE salon_id = %s AND bucket = %s LIMIT 50", (SALON, BUCKET)))
        return f"{len(rows)} message(s) lu(s) en {(time.perf_counter() - t0) * 1000:.0f} ms"
    except ReadFailure as e:
        return f"ÉCHEC après {(time.perf_counter() - t0) * 1000:.0f} ms : {str(e).splitlines()[0][:160]}"


def remplir():
    cs.execute("DELETE FROM messages_par_salon WHERE salon_id = %s AND bucket = %s", (SALON, BUCKET))
    list(execute_concurrent_with_args(cs, ins, [(SALON, BUCKET, i, 1, "x") for i in range(1, N + 1)], concurrency=64))


if "--reparer" in sys.argv:
    remplir()
    print("avant   :", lire())
    cs.execute("DELETE FROM messages_par_salon WHERE salon_id = %s AND bucket = %s", (SALON, BUCKET))   # UNE tombstone de partition
    print("après suppression de la partition entière :", lire())
else:
    remplir()
    print("initial :", lire())
    list(execute_concurrent_with_args(cs, dele, [(SALON, BUCKET, i) for i in range(2, N + 1)], concurrency=64))
    print(f"après {N - 1} suppressions ligne par ligne (il reste 1 message, le plus ancien) :", lire())
