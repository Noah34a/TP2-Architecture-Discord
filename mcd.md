# MCD - Mon Discord miniature

Ce schéma montre les données principales et leurs relations. Je l'ai fait à partir du MCD du TP1 (page 2). Ce n'est pas exactement le schéma SQL du TP2 : ici, on parle surtout des relations entre les éléments.

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

J'ai mis le rôle dans l'appartenance, et chaque amitié est enregistrée une seule fois. Dans le MCD, les pièces jointes sont séparées du message. Dans le vrai SQL du TP2, j'ai finalement utilisé un champ JSONB pour les pièces jointes et j'ai ajouté `proprietaire_id` dans `serveur`, avec des triggers pour éviter les incohérences. Je l'explique dans `DOSSIER_ARCHI.md`.
