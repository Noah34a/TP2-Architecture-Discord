# Architecture du TP2 Discord

Après les tests, je garde **PostgreSQL + Redis** pour ma version simple. PostgreSQL s'occupe des données importantes et Redis des présences qui expirent au bout de 5 minutes.

```mermaid
flowchart LR
    CLIENT[Client] --> API[Application / API]
    API -->|Comptes, droits, messages, amitiés| PG[(PostgreSQL : vérité durable)]
    API -->|Heartbeat SET EX 300| R[(Redis : présence éphémère)]
    PG -->|Calcul / refresh planifié| V[(Vue matérialisée : activité/jour)]
    API -->|Fichiers joints éventuels| F[(Stockage de fichiers)]
    PG -.->|Migration des données pour le TP2| MO[(MongoDB : test B1/B4)]
    PG -.->|Migration des messages pour le TP2| C[(Cassandra : test B1)]
    PG -.->|Migration des liens pour le TP2| N[(Neo4j : test B3)]
```

- **PostgreSQL** garde les comptes, les salons, les membres, les messages, les amitiés et les droits. C'est la base principale.
- **Redis** garde un statut temporaire avec une clé qui expire après **300 secondes**. Si Redis redémarre, les présences peuvent être perdues, mais les utilisateurs les recréent en revenant.
- Pour les **statistiques**, j'ai une vue matérialisée dans PostgreSQL. Elle est rapide mais il faut la mettre à jour.
- **MongoDB, Cassandra et Neo4j** m'ont servi pour les comparaisons du TP. Je n'ai pas besoin de les ajouter à la version simple.

Pour le TP2, j'ai copié les données vers ces autres bases avec des scripts Python, pas avec une synchronisation en temps réel. Si je voulais garder plusieurs bases en production, il faudrait prévoir comment les mettre à jour sans perdre de données.

Je n'ai pas activé de cache Redis pour les 50 derniers messages, car je n'ai pas fait de benchmark de ce cache. Les résultats détaillés sont dans `MESURES.md`.
