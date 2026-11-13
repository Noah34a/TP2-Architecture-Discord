-- TP2 Discord — Mission 3. Cassandra 4.1, instance locale a un seul noeud.
-- PostgreSQL reste la source de verite ; cette base est une copie pour B1.
-- La replication SimpleStrategy / facteur 1 convient au TP, PAS a la production.
CREATE KEYSPACE IF NOT EXISTS discord
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
AND durable_writes = true;

-- Une partition par (salon, fenetre de 10 jours) pour eviter une partition
-- geante ; tri des messages par Snowflake decroissant pour B1.
CREATE TABLE IF NOT EXISTS discord.messages_par_salon (
    salon_id int,
    bucket bigint,
    message_id bigint,
    auteur_id int,
    contenu text,
    envoye_le timestamp,
    pieces_jointes text,
    PRIMARY KEY ((salon_id, bucket), message_id)
) WITH CLUSTERING ORDER BY (message_id DESC);

-- Metadonnees facultatives pour le correctif "fenetres non vides".
-- Leur maintenance a un cout a chaque creation d'une nouvelle fenetre.
CREATE TABLE IF NOT EXISTS discord.fenetres_par_salon (
    salon_id int,
    bucket bigint,
    PRIMARY KEY (salon_id, bucket)
) WITH CLUSTERING ORDER BY (bucket DESC);
