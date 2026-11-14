# TP2 Discord - Mes mesures

B3 Ynov Montpellier - Conception et architecture des données

Dans ce TP, j'ai testé plusieurs bases de données pour voir laquelle répond le mieux aux besoins de notre petit Discord. J'ai utilisé Docker pour faire tourner les bases, puis Python et SQL pour charger les données et faire les tests.

Tous les chiffres qui suivent viennent des tests faits sur mon Mac. Ce ne sont pas les performances du vrai Discord.

## Machine utilisée

- MacBook Pro avec une puce **Apple M5 (10 cœurs)** et **16 Go de RAM**.
- **macOS 26.6.2** (build 25G83).
- Docker Desktop avec **PostgreSQL 16, MongoDB 7, Cassandra 4.1, Redis 7 et Neo4j 5**.
- Python avec l'environnement `.venv` et les librairies de `requirements.txt`.

## Mesure 0 - Les données de départ

J'ai lancé `python data/generate_data.py` pour générer les fichiers CSV (graine 42). Voilà ce que ça donne :

| CSV | Enregistrements (sans l'en-tête) |
|---|---:|
| `utilisateurs.csv` | 5 000 |
| `serveurs.csv` | 150 |
| `salons.csv` | 974 |
| `membres.csv` | 7 984 |
| `messages.csv` | 300 000 |
| `amities.csv` | 15 000 |
| **Total** | **329 108** |

J'ai ensuite regardé comment les messages étaient répartis entre les salons.

| Indicateur | Mesure |
|---|---:|
| Minimum par salon | 0 |
| Médiane par salon | 41 |
| Maximum par salon | 12 952 |
| Part des messages dans les 10 salons les plus actifs | 22,7 % |
| Salons avec moins de 20 messages | 375 |

Pour les tests, j'ai pris trois salons différents : un très actif, un moyen et un qui contient presque aucun message.

| Profil | Salon ID | Serveur ID | Messages |
|---|---:|---:|---:|
| Chaud | 775 | 118 | 12 952 |
| Moyen | 522 | 80 | 97 |
| Clairsemé | 342 | 52 | 1 |

Les salons ne sont pas tous aussi actifs. Par exemple, les 10 plus gros regroupent **22,7 % des messages**. C'est intéressant parce qu'on peut voir comment les bases réagissent suivant le nombre de messages.

## Mesure 1 - Base PostgreSQL

J'ai d'abord créé les tables avec `sql/01_schema.sql` et chargé les CSV avec `sql/02_chargement.sql`, après avoir préparé les données avec `sql/00_staging.sql`.

J'ai comparé le nombre de lignes avant et après le chargement :

| Table `app.*` | Lignes `app` | Lignes `staging` | Écart |
|---|---:|---:|---:|
| `utilisateur` | 5 000 | 5 000 | 0 |
| `serveur` | 150 | 150 | 0 |
| `salon` | 974 | 974 | 0 |
| `membre` | 7 984 | 7 984 | 0 |
| `message` | 300 000 | 300 000 | 0 |
| `amitie` | 15 000 | 15 000 | 0 |

Tout correspond. J'ai aussi vérifié qu'il n'y avait **aucun propriétaire invalide**, **aucun message dans un salon vocal** et **aucun compteur de membres incorrect**.

J'ai lancé `sql/04_tests_mission1.sql` pour essayer d'ajouter des données qui ne devraient pas être acceptées : pseudo déjà utilisé, email incorrect, mauvais rôle, amitié avec soi-même, message dans un salon vocal, mauvaise date et auteur qui n'est pas membre. **Les 8 tests ont été refusés comme prévu**, sans laisser de fausses données dans les tables.

J'ai mis des clés primaires, des clés étrangères, des `CHECK`, des index et des triggers. Par exemple, un trigger vérifie qu'une personne a le droit d'envoyer un message. L'index `(salon_id, id DESC)` sert à récupérer les 50 derniers messages d'un salon.

## Mesure 2 - Temps des requêtes SQL

J'ai utilisé `\timing on` dans `sql/03_requetes.sql`. Voici les temps du deuxième passage, le 13 novembre 2026 :

| Requête | Périmètre | Durée relevée (ms) |
|---|---|---:|
| R1 | 50 derniers messages, salon chaud 775 | 0,936 |
| R1 | 50 derniers messages, salon moyen 522 | 0,396 |
| R1 | 50 derniers messages, salon clairsemé 342 | 0,179 |
| R2 | Droit d'écriture, membre du salon 775 | 0,292 |
| R3 | Activité par jour, serveur 118, octobre 2026 | 7,831 |

- **R1** : afficher les 50 derniers messages, avec une pagination par identifiant plutôt qu'avec `OFFSET`.
- **R2** : vérifier si une personne est membre et si le salon est textuel.
- **R3** : compter les messages et les auteurs différents pour chaque jour d'octobre 2026.

Ce sont des temps pris pendant l'exécution des requêtes, pas encore des p50 ou p95.

## Mesure 3 - Comprendre pourquoi R3 prend du temps

J'ai lancé `EXPLAIN (ANALYZE, BUFFERS)` sur R3.

```text
GroupAggregate (31 jours)
  -> Sort (1928 lignes)
       -> Nested Loop
            -> Index Scan sur les salons du serveur 118
            -> Bitmap Heap Scan sur les messages (4 passages)
                 Rows Removed by Filter: 4377
                 Buffers: shared hit=5633
                 -> Bitmap Index Scan sur idx_message_salon_id_desc
Execution Time: 3.785 ms
```

Ce qui coûte le plus dans l'accès aux messages, c'est le **Bitmap Heap Scan**. PostgreSQL utilise bien un index, donc il ne lit pas toute la table d'un coup. Mais il doit quand même écarter beaucoup de messages qui ne sont pas en octobre, parce que l'index ne filtre pas directement la date.

## Mesure 4 - Deux optimisations PostgreSQL

### La vue matérialisée

Au lieu de refaire les calculs à chaque fois, j'ai créé une vue qui garde déjà les statistiques par serveur et par jour.

| Version de R3 | Durée relevée (ms) |
|---|---:|
| Requête sur tables normalisées | 7,831 |
| Lecture de la vue matérialisée | 0,136 |

C'est environ **57,6 fois plus rapide** sur cette exécution. J'ai aussi comparé les résultats : **0 ligne différente**. Par contre, il faut penser à actualiser la vue après de nouveaux messages, sinon les chiffres ne sont plus à jour.

La commande d'actualisation est :

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY app.activite_serveur_jour;
```

### Le compteur de membres

J'ai testé un compteur `nb_membres` qui est mis à jour automatiquement par un trigger.

| Étape de preuve | Valeur | Résultat attendu |
|---|---:|---|
| Avant insertion | 478 | Nombre initial |
| Après insertion | 479 | Initial + 1 ; `test_ok = t` |
| Après suppression | 478 | Initial ; `test_ok = t` |

Il passe bien de **478 à 479**, puis revient à **478**. Ça évite de recompter les membres à chaque lecture. En échange, ça ajoute une mise à jour à chaque arrivée ou départ. J'ai aussi contrôlé tous les serveurs : **0 compteur incorrect**.

## Mesure 5 - Charger MongoDB et Cassandra

J'ai utilisé `python load_nosql.py --messages-seulement` pour copier les messages depuis PostgreSQL, puis `python bench.py --mission3 --n 100` pour comparer les résultats.

| Contrôle | PostgreSQL | MongoDB | Cassandra |
|---|---:|---:|---:|
| Messages après migration (5a) | **300 000** | **300 000** | **300 000** |
| 50 derniers IDs salon chaud 775 (5b) | 50 | 50 identiques | 50 identiques |
| 50 derniers IDs salon moyen 522 (5b) | 50 | 50 identiques | 50 identiques |
| Derniers IDs salon clairsemé 342 (5b) | 1 | 1 identique | 1 identique |

Les **300 000 messages** sont bien dans les trois bases. Pour Cassandra, le script a vérifié **15 965 partitions non vides** en relisant les messages : les données correspondent à PostgreSQL.

Cassandra range les messages avec la clé `(salon_id, bucket)` : un bucket représente une période de 10 jours. Sur le salon clairsemé, le programme naïf a consulté **26 fenêtres**, alors qu'avec une table des fenêtres non vides il n'en consulte qu'**1**. Cette deuxième table demande quand même un peu plus d'entretien.

## Mesure 6 - Comparaison des 50 derniers messages (100 tests)

J'ai fait 100 mesures pour chaque base. **p50** veut dire que la moitié des requêtes passent en dessous de ce temps ; **p95** indique le temps sous lequel passent 95 % des requêtes.

| Cas | Moteur | p50 (ms) | p95 (ms) |
|---|---|---:|---:|
| B1 50 derniers messages, salon chaud | PostgreSQL | 0.16 | 0.20 |
| B1 50 derniers messages, salon chaud | MongoDB | 0.24 | 0.30 |
| B1 50 derniers messages, salon chaud | Cassandra | 0.57 | 1.25 |
| B1 50 derniers messages, salon chaud | Cassandra + fenetres non vides (bonus) | 0.93 | 1.04 |
| B1 50 derniers messages, salon moyen | PostgreSQL | 0.15 | 0.17 |
| B1 50 derniers messages, salon moyen | MongoDB | 0.23 | 0.28 |
| B1 50 derniers messages, salon moyen | Cassandra | 6.07 | 6.60 |
| B1 50 derniers messages, salon moyen | Cassandra + fenetres non vides (bonus) | 8.20 | 11.99 |
| B1 50 derniers messages, salon clairsemé | PostgreSQL | 0.14 | 0.17 |
| B1 50 derniers messages, salon clairsemé | MongoDB | 0.22 | 0.28 |
| B1 50 derniers messages, salon clairsemé | Cassandra | 10.86 | 19.07 |
| B1 50 derniers messages, salon clairsemé | Cassandra + fenetres non vides (bonus) | 1.23 | 1.75 |

Sur ces trois salons, **PostgreSQL est le plus rapide**. Cassandra a surtout du mal sur les salons où il faut chercher dans plusieurs périodes. Avec les fenêtres non vides, le salon clairsemé passe de **10,86 ms à 1,23 ms en p50**. Par contre, sur le salon moyen ça devient plus lent : **6,07 ms sans l'optimisation contre 8,20 ms avec**. Donc ajouter une optimisation ne veut pas forcément dire que tout ira plus vite.

## Mesure 7 - Redis et Neo4j (100 tests)

Pour Redis, j'ai chargé **1 500 présences**. Pour Neo4j, j'ai chargé **5 000 utilisateurs, 150 serveurs, 15 000 amitiés et 7 984 appartenances**.

Avant les mesures, j'ai vérifié que PostgreSQL et Redis donnaient les mêmes nombres de personnes en ligne sur les serveurs testés (**159, 7, 1 et 5**). J'ai aussi comparé les suggestions PostgreSQL et Neo4j sur **19 utilisateurs** : mêmes listes et mêmes scores.

J'ai testé une présence Redis avec une expiration de 2 secondes. Elle avait bien disparu après **2,4 secondes**. Dans l'application, les présences sont réglées sur **300 secondes**, soit 5 minutes.

| Cas | Moteur | p50 (ms) | p95 (ms) |
|---|---|---:|---:|
| B2a présence : écriture | PostgreSQL | 0.42 | 0.63 |
| B2a présence : écriture | Redis | 0.21 | 0.30 |
| B2b présence : en ligne dans un serveur (478 membres) | PostgreSQL | 0.26 | 0.28 |
| B2b présence : en ligne dans un serveur (478 membres) | Redis | 2.31 | 2.54 |
| B3 serveurs suggérés (amis) | PostgreSQL | 0.24 | 0.29 |
| B3 serveurs suggérés (amis) | Neo4j | 1.25 | 1.64 |
| B3 bis amis d'amis (n=30) | PostgreSQL | 0.22 | 0.26 |
| B3 bis amis d'amis (n=30) | Neo4j | 1.20 | 1.38 |

Redis gagne quand on **met à jour une présence** : **0,21 ms** contre **0,42 ms** pour PostgreSQL en p50. Par contre, pour **compter les gens en ligne dans un serveur**, PostgreSQL gagne. Redis doit lire plusieurs clés pour faire le comptage.

Neo4j est aussi plus lent pour nos suggestions. Sur un graphe plus compliqué, le résultat pourrait changer, mais ici PostgreSQL fait déjà bien le travail.

Si je n'utilisais pas Redis pour la présence, il faudrait garder une date de dernière activité dans PostgreSQL, filtrer les utilisateurs vus il y a moins de 5 minutes et prévoir un nettoyage des anciennes données.

## Mesure 8 - Benchmark final (300 tests)

Pour finir, j'ai relancé toutes les comparaisons avec `python bench.py --n 300`, après avoir rechargé Redis. Le script fait **10 passages d'échauffement** avant les mesures. Le test B3 bis utilise **30 entrées**, comme prévu dans le script, même pendant ce benchmark global.

| Cas | Moteur | p50 (ms) | p95 (ms) |
|---|---|---:|---:|
| B1 50 derniers messages, salon chaud | PostgreSQL | 0.14 | 0.16 |
| B1 50 derniers messages, salon chaud | MongoDB | 0.23 | 0.33 |
| B1 50 derniers messages, salon chaud | Cassandra | 0.45 | 0.54 |
| B1 50 derniers messages, salon chaud | Cassandra + fenetres non vides (bonus) | 0.85 | 1.35 |
| B1 50 derniers messages, salon moyen | PostgreSQL | 0.13 | 0.14 |
| B1 50 derniers messages, salon moyen | MongoDB | 0.22 | 0.24 |
| B1 50 derniers messages, salon moyen | Cassandra | 5.58 | 9.25 |
| B1 50 derniers messages, salon moyen | Cassandra + fenetres non vides (bonus) | 7.33 | 9.31 |
| B1 50 derniers messages, salon clairsemé | PostgreSQL | 0.14 | 0.16 |
| B1 50 derniers messages, salon clairsemé | MongoDB | 0.20 | 0.22 |
| B1 50 derniers messages, salon clairsemé | Cassandra | 8.29 | 11.97 |
| B1 50 derniers messages, salon clairsemé | Cassandra + fenetres non vides (bonus) | 0.85 | 1.09 |
| B2a présence : écriture | PostgreSQL | 0.26 | 0.55 |
| B2a présence : écriture | Redis | 0.13 | 0.16 |
| B2b présence : en ligne dans un serveur (478 membres) | PostgreSQL | 0.21 | 0.23 |
| B2b présence : en ligne dans un serveur (478 membres) | Redis | 1.13 | 1.33 |
| B3 serveurs suggérés (amis) | PostgreSQL | 0.14 | 0.16 |
| B3 serveurs suggérés (amis) | Neo4j | 0.97 | 1.82 |
| B3 bis amis d'amis (n=30) | PostgreSQL | 0.31 | 0.86 |
| B3 bis amis d'amis (n=30) | Neo4j | 0.92 | 1.14 |
| B4 activité d'un serveur (30 j) | PostgreSQL normalisé | 3.11 | 3.98 |
| B4 activité d'un serveur (30 j) | PostgreSQL vue matérialisée | 0.15 | 0.19 |
| B4 activité d'un serveur (30 j) | MongoDB (aggregate) | 1.77 | 2.41 |

Avant de chronométrer, le programme vérifie que les résultats correspondent : mêmes identifiants de messages, mêmes présences, mêmes suggestions et mêmes statistiques. Pour B4, les trois méthodes donnent bien **31 jours et 1 928 messages**.

### Ce que j'en retiens

- Pour les **messages (B1)**, PostgreSQL reste le plus rapide sur nos trois salons.
- Pour la **présence (B2)**, Redis est plus rapide à l'écriture, mais PostgreSQL est plus rapide pour le comptage.
- Pour les **suggestions (B3)**, PostgreSQL gagne ici face à Neo4j.
- Pour les **statistiques (B4)**, la vue matérialisée PostgreSQL passe de **3,11 ms à 0,15 ms en p50**, soit environ **20,7 fois plus rapide**. Il faut juste la rafraîchir.

### Pourquoi regarder le p95 et faire un échauffement ?

Avec seulement une moyenne, on peut rater certaines requêtes lentes. Le p95 permet de mieux les voir. L'échauffement sert à éviter que les tout premiers chargements faussent trop les mesures. Du coup, les temps qu'on a relevés sont surtout des temps avec les caches déjà utilisés.

### Les limites de mes tests

J'ai testé **300 000 messages**, pas des milliards. Les requêtes sont lancées principalement **une par une** et les bases tournent sur **mon Mac avec Docker**. Donc les résultats peuvent être différents si on a des milliers de personnes connectées en même temps, plusieurs serveurs physiques ou un réseau plus lent.

### Test Cassandra des tombstones (Mission 4)

J'ai aussi testé **119 999 suppressions** de messages dans une partition de test. La lecture a échoué avec `READ_TOO_MANY_TOMBSTONES` après **79 ms**. Ensuite, la suppression de toute la partition a permis de lire **0 message en 12 ms**. J'ai également testé une purge locale qui a permis de retrouver le dernier message, puis remis `gc_grace_seconds` à **864000**. Les détails et les précautions sont dans `RUNBOOK_tombstones.md`.

Mes sorties de Terminal sont gardées dans les fichiers `mission2_resultats.txt`, `mission3_bench.txt`, `mission4_incident.txt`, `mission4_logs.txt`, `mission5_bench.txt` et `mission6_bench.txt`, entre autres.
