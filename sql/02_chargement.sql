-- TP2 Discord - Mission 1 - Chargement staging -> app
-- Tous les transferts sont effectues dans une seule transaction.
-- Ce script est relancable : il remplace les donnees des tables app.*.
\set ON_ERROR_STOP on
BEGIN;

-- Le TRUNCATE n'enleve pas le schema. Toutes les tables liees sont listees.
TRUNCATE TABLE app.message, app.amitie, app.presence,
               app.membre, app.salon, app.serveur, app.utilisateur;

-- 1. Utilisateurs : racine des FK.
INSERT INTO app.utilisateur (id, pseudo, email, cree_le)
SELECT id::INTEGER, pseudo, email, cree_le::TIMESTAMPTZ
FROM staging.utilisateurs;

-- 2. Serveurs : le proprietaire existe deja. Son adhesion arrive en 4.
--    Le trigger de proprietaire est differe jusqu'au COMMIT.
INSERT INTO app.serveur (id, nom, proprietaire_id, cree_le)
SELECT id::INTEGER, nom, proprietaire_id::INTEGER, cree_le::TIMESTAMPTZ
FROM staging.serveurs;

-- 3. Salons : chaque serveur doit exister.
INSERT INTO app.salon (id, serveur_id, nom, type, cree_le)
SELECT id::INTEGER, serveur_id::INTEGER, nom, type, cree_le::TIMESTAMPTZ
FROM staging.salons;

-- 4. Membres : les utilisateurs et les serveurs existent.
INSERT INTO app.membre (utilisateur_id, serveur_id, role, rejoint_le)
SELECT utilisateur_id::INTEGER, serveur_id::INTEGER, role,
       rejoint_le::TIMESTAMPTZ
FROM staging.membres;

-- 5. Messages : les auteurs, salons et appartenances existent.
--    Les champs vides du CSV deviennent des NULL SQL.
INSERT INTO app.message
    (id, salon_id, auteur_id, contenu, envoye_le, modifie_le, pieces_jointes)
SELECT id::BIGINT, salon_id::INTEGER, auteur_id::INTEGER,
       contenu, envoye_le::TIMESTAMPTZ,
       NULLIF(modifie_le, '')::TIMESTAMPTZ,
       NULLIF(pieces_jointes, '')::JSONB
FROM staging.messages;

-- 6. Amities : les deux utilisateurs doivent exister.
INSERT INTO app.amitie (utilisateur_a, utilisateur_b, depuis)
SELECT utilisateur_a::INTEGER, utilisateur_b::INTEGER,
       depuis::TIMESTAMPTZ
FROM staging.amities;

-- Initialisation du compteur, avant sa maintenance automatique en mission 2.
UPDATE app.serveur s
SET nb_membres = (
    SELECT count(*)::INTEGER
    FROM app.membre m
    WHERE m.serveur_id = s.id
);

COMMIT;

-- Mesure 1 : toutes les tables doivent contenir exactement les memes volumes
-- que staging, a l'exception de presence (pas de CSV de presence).
SELECT 'utilisateur' AS table_app, (SELECT count(*) FROM app.utilisateur) AS app,
       (SELECT count(*) FROM staging.utilisateurs) AS staging
UNION ALL SELECT 'serveur', (SELECT count(*) FROM app.serveur),
       (SELECT count(*) FROM staging.serveurs)
UNION ALL SELECT 'salon', (SELECT count(*) FROM app.salon),
       (SELECT count(*) FROM staging.salons)
UNION ALL SELECT 'membre', (SELECT count(*) FROM app.membre),
       (SELECT count(*) FROM staging.membres)
UNION ALL SELECT 'message', (SELECT count(*) FROM app.message),
       (SELECT count(*) FROM staging.messages)
UNION ALL SELECT 'amitie', (SELECT count(*) FROM app.amitie),
       (SELECT count(*) FROM staging.amities);

-- Controle des deux invariants du TP : chacune des requetes doit retourner 0.
SELECT count(*) AS proprietaires_invalides
FROM app.serveur s
WHERE NOT EXISTS (
    SELECT 1 FROM app.membre m
    WHERE m.serveur_id = s.id
      AND m.utilisateur_id = s.proprietaire_id
      AND m.role = 'proprietaire'
);

SELECT count(*) AS messages_dans_salon_vocal
FROM app.message m
JOIN app.salon s ON s.id = m.salon_id
WHERE s.type = 'vocal';

-- Le compteur initial doit aussi correspondre aux membres reels.
SELECT count(*) AS compteurs_incorrects
FROM app.serveur s
WHERE s.nb_membres <> (SELECT count(*) FROM app.membre m WHERE m.serveur_id = s.id);
