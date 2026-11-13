-- FOURNI. Charge les CSV tels quels (tout en texte) dans le schéma `staging`. Ne pas modifier.
DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA staging;
CREATE TABLE staging.utilisateurs (id text, pseudo text, email text, cree_le text);
CREATE TABLE staging.serveurs     (id text, nom text, proprietaire_id text, cree_le text);
CREATE TABLE staging.salons       (id text, serveur_id text, nom text, type text, cree_le text);
CREATE TABLE staging.membres      (utilisateur_id text, serveur_id text, role text, rejoint_le text);
CREATE TABLE staging.messages     (id text, salon_id text, auteur_id text, contenu text, envoye_le text, modifie_le text, pieces_jointes text);
CREATE TABLE staging.amities      (utilisateur_a text, utilisateur_b text, depuis text);
COPY staging.utilisateurs FROM '/data/utilisateurs.csv' CSV HEADER;
COPY staging.serveurs     FROM '/data/serveurs.csv'     CSV HEADER;
COPY staging.salons       FROM '/data/salons.csv'       CSV HEADER;
COPY staging.membres      FROM '/data/membres.csv'      CSV HEADER;
COPY staging.messages     FROM '/data/messages.csv'     CSV HEADER;
COPY staging.amities      FROM '/data/amities.csv'      CSV HEADER;
SELECT 'staging.messages' AS table, count(*) FROM staging.messages
UNION ALL SELECT 'staging.membres', count(*) FROM staging.membres;
