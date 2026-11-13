-- TP2 Discord - Mission 1 - Schema relationnel PostgreSQL
-- Convention de nommage conforme a l'annexe A du TP2.
-- A executer APRES sql/00_staging.sql, dans la base discord.
-- Attention : relancer ce fichier supprime le schema app et ses donnees.
\set ON_ERROR_STOP on
BEGIN;

DROP SCHEMA IF EXISTS app CASCADE;
CREATE SCHEMA app;

CREATE TABLE app.utilisateur (
    id          INTEGER PRIMARY KEY,
    pseudo      VARCHAR(64) NOT NULL UNIQUE,
    email       VARCHAR(255) NOT NULL UNIQUE,
    cree_le     TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_utilisateur_pseudo CHECK (length(btrim(pseudo)) > 0),
    CONSTRAINT ck_utilisateur_email CHECK (position('@' IN email) > 1)
);

CREATE TABLE app.serveur (
    id               INTEGER PRIMARY KEY,
    nom              VARCHAR(150) NOT NULL,
    proprietaire_id  INTEGER NOT NULL REFERENCES app.utilisateur(id),
    cree_le          TIMESTAMPTZ NOT NULL,
    -- Colonne prevue par le contrat de nommage. Le trigger de maintenance
    -- du compteur sera ajoute et mesure a la mission 2.
    nb_membres       INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_serveur_nom CHECK (length(btrim(nom)) > 0),
    CONSTRAINT ck_serveur_nb_membres CHECK (nb_membres >= 0)
);

CREATE TABLE app.salon (
    id          INTEGER PRIMARY KEY,
    serveur_id  INTEGER NOT NULL REFERENCES app.serveur(id),
    nom         VARCHAR(100) NOT NULL,
    type        VARCHAR(10) NOT NULL,
    cree_le     TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_salon_nom_par_serveur UNIQUE (serveur_id, nom),
    CONSTRAINT ck_salon_nom CHECK (length(btrim(nom)) > 0),
    CONSTRAINT ck_salon_type CHECK (type IN ('texte', 'vocal'))
);

CREATE TABLE app.membre (
    utilisateur_id  INTEGER NOT NULL REFERENCES app.utilisateur(id),
    serveur_id      INTEGER NOT NULL REFERENCES app.serveur(id),
    role            VARCHAR(15) NOT NULL,
    rejoint_le      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (utilisateur_id, serveur_id),
    CONSTRAINT ck_membre_role CHECK (role IN ('proprietaire', 'moderateur', 'membre'))
);

CREATE TABLE app.message (
    -- Snowflake : depasse la plage INTEGER, d'ou BIGINT.
    id              BIGINT PRIMARY KEY,
    salon_id        INTEGER NOT NULL REFERENCES app.salon(id),
    auteur_id       INTEGER NOT NULL REFERENCES app.utilisateur(id),
    contenu         TEXT NOT NULL,
    envoye_le       TIMESTAMPTZ NOT NULL,
    modifie_le      TIMESTAMPTZ,
    pieces_jointes  JSONB,
    CONSTRAINT ck_message_id CHECK (id > 0),
    CONSTRAINT ck_message_contenu CHECK (length(btrim(contenu)) > 0),
    CONSTRAINT ck_message_dates CHECK (modifie_le IS NULL OR modifie_le >= envoye_le),
    CONSTRAINT ck_message_pj CHECK (pieces_jointes IS NULL OR jsonb_typeof(pieces_jointes) = 'object')
);

CREATE TABLE app.amitie (
    utilisateur_a  INTEGER NOT NULL REFERENCES app.utilisateur(id),
    utilisateur_b  INTEGER NOT NULL REFERENCES app.utilisateur(id),
    depuis         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (utilisateur_a, utilisateur_b),
    CONSTRAINT ck_amitie_ordre CHECK (utilisateur_a < utilisateur_b)
);

-- Candidat relationnel du benchmark de presence (mission 5).
CREATE TABLE app.presence (
    utilisateur_id  INTEGER PRIMARY KEY REFERENCES app.utilisateur(id),
    vu_le           TIMESTAMPTZ NOT NULL
);

-- Index et justification :
-- R1 / B1 : les 50 derniers messages d'un salon, pagination par id Snowflake.
CREATE INDEX idx_message_salon_id_desc ON app.message (salon_id, id DESC);
-- Pour les controles d'integrite et les operations sur un auteur.
CREATE INDEX idx_message_auteur ON app.message (auteur_id);
-- R2 / B2b : trouver rapidement les membres d'un serveur.
-- La PK (utilisateur_id, serveur_id) couvre deja les acces par utilisateur.
CREATE INDEX idx_membre_serveur ON app.membre (serveur_id, utilisateur_id);
-- R3 : l'index UNIQUE (serveur_id, nom) couvre deja le debut des recherches de salons par serveur.
-- B3 / B3 bis : la PK couvre utilisateur_a ; cet index couvre utilisateur_b.
CREATE INDEX idx_amitie_b ON app.amitie (utilisateur_b, utilisateur_a);
-- Verifications de FK lors de suppression ou changement de proprietaire.
CREATE INDEX idx_serveur_proprietaire ON app.serveur (proprietaire_id);

-- Un serveur ne doit pas contenir plusieurs membres au role proprietaire.
CREATE UNIQUE INDEX ux_membre_proprietaire_serveur
    ON app.membre (serveur_id) WHERE role = 'proprietaire';

-- Regle : chaque proprietaire doit appartenir a son serveur avec le bon role.
-- Trigger differe : l'ordre de chargement impose d'inserer le serveur
-- AVANT ses membres. Le controle s'executera a la fin de la transaction.
CREATE FUNCTION app.verifier_proprietaire(p_serveur_id INTEGER)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    v_proprietaire INTEGER;
BEGIN
    SELECT proprietaire_id INTO v_proprietaire
    FROM app.serveur WHERE id = p_serveur_id;
    IF NOT FOUND THEN
        RETURN; -- Serveur supprime dans la meme transaction.
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM app.membre
        WHERE serveur_id = p_serveur_id
          AND utilisateur_id = v_proprietaire
          AND role = 'proprietaire'
    ) THEN
        RAISE EXCEPTION 'Le proprietaire du serveur % doit etre membre avec le role proprietaire', p_serveur_id
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION app.trg_verifier_proprietaire_serveur()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM app.verifier_proprietaire(NEW.id);
    RETURN NULL; -- Valeur ignoree pour un trigger AFTER.
END;
$$;

CREATE CONSTRAINT TRIGGER ck_proprietaire_serveur
AFTER INSERT OR UPDATE ON app.serveur
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION app.trg_verifier_proprietaire_serveur();

CREATE FUNCTION app.trg_verifier_proprietaire_membre()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM app.verifier_proprietaire(OLD.serveur_id);
    ELSIF TG_OP = 'UPDATE' THEN
        PERFORM app.verifier_proprietaire(OLD.serveur_id);
        PERFORM app.verifier_proprietaire(NEW.serveur_id);
    ELSE
        PERFORM app.verifier_proprietaire(NEW.serveur_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ck_proprietaire_membre
AFTER INSERT OR UPDATE OR DELETE ON app.membre
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION app.trg_verifier_proprietaire_membre();

-- Regles sur le chemin d'ecriture d'un message : salon textuel,
-- auteur membre du serveur et envoi apres la creation du salon.
-- Le controle ne s'execute pas lors d'une simple edition du contenu.
CREATE FUNCTION app.trg_verifier_message()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_serveur_id INTEGER;
    v_type VARCHAR(10);
    v_cree_le TIMESTAMPTZ;
BEGIN
    SELECT serveur_id, type, cree_le INTO v_serveur_id, v_type, v_cree_le
    FROM app.salon WHERE id = NEW.salon_id;
    IF NOT FOUND THEN
        RETURN NEW; -- La FK rejettera un salon inexistant.
    END IF;

    IF v_type <> 'texte' THEN
        RAISE EXCEPTION 'Un message ne peut pas etre envoye dans un salon vocal (salon %)', NEW.salon_id
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM app.membre
        WHERE utilisateur_id = NEW.auteur_id AND serveur_id = v_serveur_id
    ) THEN
        RAISE EXCEPTION 'L auteur % n est pas membre du serveur %', NEW.auteur_id, v_serveur_id
            USING ERRCODE = '23514';
    END IF;
    IF NEW.envoye_le < v_cree_le THEN
        RAISE EXCEPTION 'Le message precede la creation du salon %', NEW.salon_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ck_message_ecriture
BEFORE INSERT OR UPDATE OF salon_id, auteur_id, envoye_le ON app.message
FOR EACH ROW EXECUTE FUNCTION app.trg_verifier_message();

-- Une conversion d'un salon avec messages en salon vocal est interdite.
CREATE FUNCTION app.trg_verifier_type_salon()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.type = 'vocal' AND OLD.type = 'texte'
       AND EXISTS (SELECT 1 FROM app.message WHERE salon_id = NEW.id) THEN
        RAISE EXCEPTION 'Un salon contenant des messages ne peut pas devenir vocal (salon %)', NEW.id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ck_conversion_salon
BEFORE UPDATE OF type ON app.salon
FOR EACH ROW EXECUTE FUNCTION app.trg_verifier_type_salon();

COMMIT;
