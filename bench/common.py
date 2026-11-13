"""Connexions et fonctions partagées par load_nosql.py, bench.py et tombstones.py."""
import atexit

import psycopg
import redis
from cassandra.cluster import Cluster
from neo4j import GraphDatabase
from pymongo import MongoClient

EPOCH_MS = 1420070400000          # époque des Snowflake (2015-01-01)
BUCKET_MS = 10 * 24 * 3600 * 1000  # fenêtre de partition : 10 jours, comme dans l'article de 2017


def pg_conn():
    return psycopg.connect("postgresql://tp:tp@localhost:5432/discord", autocommit=True)


def mongo_db():
    return MongoClient("mongodb://localhost:27017")["discord"]


def redis_conn():
    return redis.Redis(decode_responses=True)


def neo_driver():
    d = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "tpynov2026"))
    atexit.register(d.close)   # sinon le driver se plaint à la sortie de l'interpréteur
    return d


def cassandra_session(keyspace=None):
    s = Cluster(["127.0.0.1"], port=9042).connect()
    if keyspace:
        s.set_keyspace(keyspace)
    return s


def bucket_de(message_id):
    """Numéro de fenêtre de 10 jours dérivé du Snowflake (ms depuis 2015 = id >> 22)."""
    return (message_id >> 22) // BUCKET_MS
