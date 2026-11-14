# MCD — Miniature Discord

Ce schéma reprend les entités présentes sur le MCD du **TP1 (page 2)**. Il s'agit du **modèle conceptuel**, pas d'une reproduction exacte du schéma SQL de la Mission 1.

```mermaid
erDiagram
    UTILISATEUR ||--o{ APPARTENANCE : rejoint
    SERVEUR ||--o{ APPARTENANCE : accueille
    SERVEUR ||--o{ SALON : contient
    SALON ||--o{ MESSAGE : contient
    UTILISATEUR ||--o{ MESSAGE : ecrit
    MESSAGE ||--o| PIECE_JOINTE : possede
    UTILISATEUR ||--o{ AMITIE : participant_A
    UTILISATEUR ||--o{ AMITIE : participant_B
    SERVEUR ||--o{ ACTIVITE_JOUR : produit
    UTILISATEUR {
        bigint id PK
        string pseudo
        string email
    }
    SERVEUR {
        bigint id PK
        string nom
    }
    APPARTENANCE {
        bigint utilisateur_id FK
        bigint serveur_id FK
        string role
        datetime rejoint_le
    }
    SALON {
        bigint id PK
        bigint serveur_id FK
        string nom
        string type
    }
    MESSAGE {
        bigint id PK
        bigint auteur_id FK
        bigint salon_id FK
        text contenu
        datetime envoye_le
    }
    PIECE_JOINTE {
        bigint id PK
        bigint message_id FK
        string type
    }
    AMITIE {
        bigint utilisateur_a FK
        bigint utilisateur_b FK
    }
    ACTIVITE_JOUR {
        bigint serveur_id FK
        date jour
        int nb_messages
    }
```

**Choix du TP1 :** le rôle appartient à l'association d'appartenance ; l'amitié est symétrique et stockée une fois ; un propriétaire est un membre ; la pièce jointe est séparée conceptuellement. **Écart TP2 :** la base physique créée au Jour 2 utilise `pieces_jointes JSONB` dans `message` et `proprietaire_id` dans `serveur` en plus du rôle, avec vérification de cohérence. Ces différences sont détaillées dans `DOSSIER_ARCHI.md`.
