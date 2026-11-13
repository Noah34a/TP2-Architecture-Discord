-- TP2 Discord - Mission 2 : requetes critiques, mesures et denormalisations.
-- A executer APRES la Mission 1 : sql/01_schema.sql et sql/02_chargement.sql.
-- Lancer a la racine du depot :
-- docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U tp -d discord < sql/03_requetes.sql | tee mission2_resultats.txt
-- Les temps et les plans EXPLAIN sont ceux de VOTRE machine : a recopier dans MESURES.md.
-- Eviter de relancer 01_schema.sql ensuite : cela effacerait les objets de la mission 2.
\set ON_ERROR_STOP on
\pset pager off
\timing on

\echo === MESURE 2 : R1 - 50 derniers messages (salon CHAUD 775) ===
-- L'index (salon_id, id DESC) aide la pagination par cle (Snowflake).
-- Premier lot : pas d'OFFSET.
SELECT m.id, m.envoye_le, u.pseudo AS auteur, m.contenu
FROM app.message AS m
JOIN app.utilisateur AS u ON u.id = m.auteur_id
WHERE m.salon_id = 775
ORDER BY m.id DESC
LIMIT 50;

\echo === MESURE 2 : R1 - 50 derniers messages (salon MOYEN 522) ===
SELECT m.id, m.envoye_le, u.pseudo AS auteur, m.contenu
FROM app.message AS m
JOIN app.utilisateur AS u ON u.id = m.auteur_id
WHERE m.salon_id = 522
ORDER BY m.id DESC
LIMIT 50;

\echo === MESURE 2 : R1 - 50 derniers messages (salon CLAIRSEME 342) ===
SELECT m.id, m.envoye_le, u.pseudo AS auteur, m.contenu
FROM app.message AS m
JOIN app.utilisateur AS u ON u.id = m.auteur_id
WHERE m.salon_id = 342
ORDER BY m.id DESC
LIMIT 50;

\echo === R1 - pagination par cle : page suivante du salon 775 ===
-- Le dernier ID de la page 1 sert de curseur de pagination.
SELECT MIN(id) AS curseur_id
FROM (SELECT id FROM app.message WHERE salon_id = 775 ORDER BY id DESC LIMIT 50) AS page_1
\gset
SELECT m.id, m.envoye_le, u.pseudo AS auteur, m.contenu
FROM app.message AS m
JOIN app.utilisateur AS u ON u.id = m.auteur_id
WHERE m.salon_id = 775 AND m.id < :curseur_id
ORDER BY m.id DESC
LIMIT 50;

\echo === MESURE 2 : R2 - utilisateur autorise a ecrire (salon 775) ===
-- Choisir un membre reel de ce serveur pour que le test positif soit reproductible.
SELECT m.utilisateur_id AS utilisateur_autorise
FROM app.membre AS m
JOIN app.salon AS s ON s.serveur_id = m.serveur_id
WHERE s.id = 775
ORDER BY m.utilisateur_id
LIMIT 1
\gset
SELECT EXISTS (
    SELECT 1
    FROM app.salon AS s
    JOIN app.membre AS m ON m.serveur_id = s.serveur_id
    WHERE s.id = 775 AND s.type = 'texte'
      AND m.utilisateur_id = :utilisateur_autorise
) AS peut_ecrire;

\echo === R2 - utilisateur non membre : resultat attendu false ===
SELECT u.id AS utilisateur_non_membre
FROM app.utilisateur AS u
WHERE NOT EXISTS (
    SELECT 1 FROM app.membre AS m
    JOIN app.salon AS s ON s.serveur_id = m.serveur_id
    WHERE s.id = 775 AND m.utilisateur_id = u.id
)
ORDER BY u.id
LIMIT 1
\gset
SELECT EXISTS (
    SELECT 1
    FROM app.salon AS s
    JOIN app.membre AS m ON m.serveur_id = s.serveur_id
    WHERE s.id = 775 AND s.type = 'texte'
      AND m.utilisateur_id = :utilisateur_non_membre
) AS peut_ecrire;

\echo === MESURE 2 : R3 - activite quotidienne du serveur 118 en octobre 2026 (AVANT vue) ===
-- Fuseau UTC explicite pour ne pas dependre du fuseau de la session PostgreSQL.
-- L'intervalle [debut, fin) inclut tout octobre, sans inclure novembre.
SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
       COUNT(*) AS nb_messages,
       COUNT(DISTINCT m.auteur_id) AS nb_auteurs
FROM app.message AS m
JOIN app.salon AS s ON s.id = m.salon_id
WHERE s.serveur_id = 118
  AND m.envoye_le >= TIMESTAMPTZ '2026-10-01 00:00:00+00'
  AND m.envoye_le <  TIMESTAMPTZ '2026-11-01 00:00:00+00'
GROUP BY (m.envoye_le AT TIME ZONE 'UTC')::date
ORDER BY jour;

\echo === MESURE 3 : EXPLAIN (ANALYZE, BUFFERS) de R3 - relever le noeud le plus couteux ===
EXPLAIN (ANALYZE, BUFFERS)
SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
       COUNT(*) AS nb_messages,
       COUNT(DISTINCT m.auteur_id) AS nb_auteurs
FROM app.message AS m
JOIN app.salon AS s ON s.id = m.salon_id
WHERE s.serveur_id = 118
  AND m.envoye_le >= TIMESTAMPTZ '2026-10-01 00:00:00+00'
  AND m.envoye_le <  TIMESTAMPTZ '2026-11-01 00:00:00+00'
GROUP BY (m.envoye_le AT TIME ZONE 'UTC')::date
ORDER BY jour;

\echo === DENORMALISATION 2 : compteur nb_membres maintenu par trigger ===
-- Choix : incrementer/decrementer atomiquement plutot que recompter tous les membres.
-- Le changement de serveur via UPDATE decremente l'ancien et incremente le nouveau.
-- Les UPDATE de role et autres champs ne changent pas le nombre de membres.
-- Cout : une mise a jour de ligne serveur a chaque insertion/suppression de membre,
-- ce qui peut entrainer de la contention sur un serveur tres actif.
CREATE OR REPLACE FUNCTION app.maintenir_nb_membres()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE app.serveur SET nb_membres = nb_membres + 1
        WHERE id = NEW.serveur_id;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE app.serveur SET nb_membres = nb_membres - 1
        WHERE id = OLD.serveur_id;
        RETURN OLD;
    ELSIF NEW.serveur_id <> OLD.serveur_id THEN
        UPDATE app.serveur SET nb_membres = nb_membres - 1
        WHERE id = OLD.serveur_id;
        UPDATE app.serveur SET nb_membres = nb_membres + 1
        WHERE id = NEW.serveur_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_maintenir_nb_membres ON app.membre;
CREATE TRIGGER trg_maintenir_nb_membres
AFTER INSERT OR DELETE OR UPDATE OF serveur_id ON app.membre
FOR EACH ROW EXECUTE FUNCTION app.maintenir_nb_membres();

\echo === PREUVE compteur : initial, insertion, relecture, suppression, relecture ===
-- Tout le test est dans une transaction annulee a la fin : aucune donnee de test conservee.
BEGIN;
SELECT nb_membres AS nb_initial
FROM app.serveur WHERE id = 118
\gset
SELECT u.id AS utilisateur_test
FROM app.utilisateur AS u
WHERE NOT EXISTS (
    SELECT 1 FROM app.membre AS m
    WHERE m.utilisateur_id = u.id AND m.serveur_id = 118
)
ORDER BY u.id
LIMIT 1
\gset
\echo Avant insertion (serveur 118) :
SELECT nb_membres AS avant FROM app.serveur WHERE id = 118;
INSERT INTO app.membre (utilisateur_id, serveur_id, role, rejoint_le)
VALUES (:utilisateur_test, 118, 'membre', NOW());
\echo Apres insertion (doit avoir augmente de 1) :
SELECT nb_membres AS apres_insertion,
       nb_membres = (:nb_initial + 1) AS test_ok
FROM app.serveur WHERE id = 118;
DELETE FROM app.membre
WHERE utilisateur_id = :utilisateur_test AND serveur_id = 118;
\echo Apres suppression (doit etre revenu a la valeur initiale) :
SELECT nb_membres AS apres_suppression,
       nb_membres = :nb_initial AS test_ok
FROM app.serveur WHERE id = 118;
ROLLBACK;

\echo === DENORMALISATION 1 : vue materialisee dactivite quotidienne ===
-- Precalculer messages + auteurs distincts par serveur et par jour UTC.
-- On garde toute la periode pour reutiliser la vue au-dela d'octobre.
CREATE MATERIALIZED VIEW IF NOT EXISTS app.activite_serveur_jour AS
SELECT s.serveur_id,
       (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
       COUNT(*) AS nb_messages,
       COUNT(DISTINCT m.auteur_id) AS nb_auteurs
FROM app.message AS m
JOIN app.salon AS s ON s.id = m.salon_id
GROUP BY s.serveur_id, (m.envoye_le AT TIME ZONE 'UTC')::date
WITH DATA;

-- Cet index UNIQUE est requis pour REFRESH MATERIALIZED VIEW CONCURRENTLY.
CREATE UNIQUE INDEX IF NOT EXISTS ux_activite_serveur_jour
ON app.activite_serveur_jour (serveur_id, jour);

\echo === MESURE 4 : R3 via vue materialisee (APRES vue) ===
SELECT jour, nb_messages, nb_auteurs
FROM app.activite_serveur_jour
WHERE serveur_id = 118
  AND jour >= DATE '2026-10-01'
  AND jour < DATE '2026-11-01'
ORDER BY jour;

\echo === MESURE 4 : EXPLAIN de la version materialisee ===
EXPLAIN (ANALYZE, BUFFERS)
SELECT jour, nb_messages, nb_auteurs
FROM app.activite_serveur_jour
WHERE serveur_id = 118
  AND jour >= DATE '2026-10-01'
  AND jour < DATE '2026-11-01'
ORDER BY jour;

\echo === Controle : R3 normalise et vue materialisee doivent renvoyer les memes valeurs ===
WITH normalisee AS (
    SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
           COUNT(*) AS nb_messages,
           COUNT(DISTINCT m.auteur_id) AS nb_auteurs
    FROM app.message AS m
    JOIN app.salon AS s ON s.id = m.salon_id
    WHERE s.serveur_id = 118
      AND m.envoye_le >= TIMESTAMPTZ '2026-10-01 00:00:00+00'
      AND m.envoye_le <  TIMESTAMPTZ '2026-11-01 00:00:00+00'
    GROUP BY (m.envoye_le AT TIME ZONE 'UTC')::date
), materialisee AS (
    SELECT jour, nb_messages, nb_auteurs
    FROM app.activite_serveur_jour
    WHERE serveur_id = 118
      AND jour >= DATE '2026-10-01' AND jour < DATE '2026-11-01'
)
SELECT COUNT(*) AS nb_lignes_differentes
FROM (
    (SELECT * FROM normalisee EXCEPT ALL SELECT * FROM materialisee)
    UNION ALL
    (SELECT * FROM materialisee EXCEPT ALL SELECT * FROM normalisee)
) AS ecarts;

\echo === Controle : compteurs nb_membres corrects sur tous les serveurs ===
SELECT COUNT(*) AS compteurs_incorrects
FROM app.serveur AS s
WHERE s.nb_membres <> (
    SELECT COUNT(*) FROM app.membre AS m WHERE m.serveur_id = s.id
);

\echo === INFORMATION : la vue nest PAS actualisee automatiquement apres chaque message ===
\echo Actualisation apres des ecritures :
\echo REFRESH MATERIALIZED VIEW CONCURRENTLY app.activite_serveur_jour;
\echo Le refresh concurrent exige lindex UNIQUE ci-dessus, evite de bloquer les lectures ordinaires,
\echo mais coute un recalcul complet. Le declenchement doit etre decide (tache planifiee, par exemple).
