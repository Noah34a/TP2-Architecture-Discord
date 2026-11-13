-- TP2 Discord - Mission 1 - Tests de contraintes (sans donnees persistantes)
-- Executer apres 01_schema.sql et 02_chargement.sql.
-- Chaque bloc attend un refus, affiche son message puis annule le test.
\set ON_ERROR_STOP on

-- Test 1 : pseudo unique.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.utilisateur (id, pseudo, email, cree_le)
        SELECT 900001, pseudo, 'autre1@example.fr', now() FROM app.utilisateur WHERE id = 1;
        RAISE EXCEPTION 'ECHEC TEST 1 : le pseudo en double a ete accepte';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'TEST 1 OK - pseudo unique : %', SQLERRM;
    END;
END $$;

-- Test 2 : adresse email invalide.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.utilisateur (id, pseudo, email, cree_le)
        VALUES (900002, 'testemail', 'sans-arobase', now());
        RAISE EXCEPTION 'ECHEC TEST 2 : l email invalide a ete accepte';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 2 OK - email avec @ : %', SQLERRM;
    END;
END $$;

-- Test 3 : salon de type interdit.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.salon (id, serveur_id, nom, type, cree_le)
        VALUES (900003, 1, 'test-type-invalide', 'video', now());
        RAISE EXCEPTION 'ECHEC TEST 3 : le type video a ete accepte';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 3 OK - type texte/vocal : %', SQLERRM;
    END;
END $$;

-- Test 4 : role interdit pour un membre.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.membre (utilisateur_id, serveur_id, role, rejoint_le)
        SELECT u.id, 1, 'administrateur', now()
        FROM app.utilisateur u
        WHERE NOT EXISTS (
            SELECT 1 FROM app.membre m
            WHERE m.utilisateur_id = u.id AND m.serveur_id = 1
        )
        ORDER BY u.id LIMIT 1;
        RAISE EXCEPTION 'ECHEC TEST 4 : le role administrateur a ete accepte';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 4 OK - role autorise : %', SQLERRM;
    END;
END $$;

-- Test 5 : pas d'amitie avec soi-meme (a doit etre inferieur a b).
DO $$ BEGIN
    BEGIN
        INSERT INTO app.amitie (utilisateur_a, utilisateur_b, depuis)
        VALUES (1, 1, now());
        RAISE EXCEPTION 'ECHEC TEST 5 : l auto-amitie a ete acceptee';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 5 OK - ordre des amities : %', SQLERRM;
    END;
END $$;

-- Test 6 : aucun message dans un salon vocal.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.message (id, salon_id, auteur_id, contenu, envoye_le)
        SELECT 9000000000000000001, s.id, m.utilisateur_id, 'test salon vocal', now()
        FROM app.salon s
        JOIN app.membre m ON m.serveur_id = s.serveur_id
        WHERE s.type = 'vocal'
        ORDER BY s.id, m.utilisateur_id LIMIT 1;
        RAISE EXCEPTION 'ECHEC TEST 6 : un message dans un salon vocal a ete accepte';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 6 OK - salon vocal interdit : %', SQLERRM;
    END;
END $$;

-- Test 7 : date de modification posterieure a l'envoi.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.message
            (id, salon_id, auteur_id, contenu, envoye_le, modifie_le)
        SELECT 9000000000000000002, s.id, m.utilisateur_id,
               'test date invalide', now(), now() - INTERVAL '1 hour'
        FROM app.salon s
        JOIN app.membre m ON m.serveur_id = s.serveur_id
        WHERE s.type = 'texte'
        ORDER BY s.id, m.utilisateur_id LIMIT 1;
        RAISE EXCEPTION 'ECHEC TEST 7 : une modification avant envoi a ete acceptee';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 7 OK - dates coherentes : %', SQLERRM;
    END;
END $$;

-- Test 8 : message interdit pour un auteur non membre du serveur.
DO $$ BEGIN
    BEGIN
        INSERT INTO app.message (id, salon_id, auteur_id, contenu, envoye_le)
        SELECT 9000000000000000003, s.id, u.id, 'test non membre', now()
        FROM app.salon s CROSS JOIN app.utilisateur u
        WHERE s.type = 'texte'
          AND NOT EXISTS (
              SELECT 1 FROM app.membre m
              WHERE m.serveur_id = s.serveur_id AND m.utilisateur_id = u.id
          )
        ORDER BY s.id, u.id LIMIT 1;
        RAISE EXCEPTION 'ECHEC TEST 8 : un auteur non membre a pu ecrire';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'TEST 8 OK - auteur membre : %', SQLERRM;
    END;
END $$;

SELECT 'Tests de contraintes executes : aucun enregistrement de test conserve' AS resultat;
