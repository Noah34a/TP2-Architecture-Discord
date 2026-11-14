# TP2 — MESURES

Bachelor 3 Ynov Montpellier — Architecture des données, plateforme miniature de discussion.

**Méthode :** les volumes et les latences ci-dessous proviennent des sorties du Terminal réalisées sur le Mac du TP. Les performances sont celles de ce jeu de données local, pas de Discord en production.

## Machine

- Machine : MacBook Pro — puce **Apple M5**, **10 cœurs** (4 performance + 6 efficacité), **16 Go RAM**.
- Système : **macOS 26.6.2** (build 25G83).
- Docker Desktop / Docker Compose : **PostgreSQL 16, MongoDB 7, Redis 7, Neo4j 5, Cassandra 4.1** (profil `colonne` pour Cassandra).
- Python : environnement virtuel `.venv`, dépendances de `requirements.txt` installées.

## Mesure 0 — État des lieux des données

Données générées localement avec `python data/generate_data.py` (graine par défaut 42).

| CSV | Enregistrements (sans l'en-tête) |
|---|---:|
| `utilisateurs.csv` | 5 000 |
| `serveurs.csv` | 150 |
| `salons.csv` | 974 |
| `membres.csv` | 7 984 |
| `messages.csv` | 300 000 |
| `amities.csv` | 15 000 |
| **Total** | **329 108** |

Répartition des messages, en incluant tous les salons (dont les vocaux, qui n'ont pas de messages textuels) :

| Indicateur | Mesure |
|---|---:|
| Minimum par salon | 0 |
| Médiane par salon | 41 |
| Maximum par salon | 12 952 |
| Part des messages dans les 10 salons les plus actifs | 22,7 % |
| Salons avec moins de 20 messages | 375 |

Salons textuels retenus pour comparer les performances :

| Profil | Salon ID | Serveur ID | Messages |
|---|---:|---:|---:|
| Chaud | 775 | 118 | 12 952 |
| Moyen | 522 | 80 | 97 |
| Clairsemé | 342 | 52 | 1 |

**Analyse.** La charge est fortement inégale : les 10 salons les plus actifs totalisent 22,7 % des messages, alors que 375 salons en ont moins de 20. Cela permet de reproduire des profils contrastés (très actif, moyen et peu actif). En revanche, 300 000 messages et une génération locale ne reproduisent ni l'échelle réelle de Discord, ni sa concurrence, ni les conditions réseau et matérielles de production. On ne peut donc pas déduire les performances réelles de Discord de ce benchmark.

## Mesure 1 — Chargement relationnel et contraintes

Commandes exécutées : `sql/00_staging.sql`, `sql/01_schema.sql`, `sql/02_chargement.sql` et `sql/04_tests_mission1.sql`.

| Table `app.*` | Lignes `app` | Lignes `staging` | Écart |
|---|---:|---:|---:|
| `utilisateur` | 5 000 | 5 000 | 0 |
| `serveur` | 150 | 150 | 0 |
| `salon` | 974 | 974 | 0 |
| `membre` | 7 984 | 7 984 | 0 |
| `message` | 300 000 | 300 000 | 0 |
| `amitie` | 15 000 | 15 000 | 0 |

Invariants : **0** propriétaires invalides, **0** messages dans des salons vocaux, **0** compteurs incorrects après le chargement.

Huit violations ont été refusées lors des tests : pseudo en double ; e-mail sans `@` ; type de salon interdit ; rôle interdit ; amitié avec soi-même ; message dans un salon vocal ; date de modification avant l'envoi ; auteur non membre du serveur. Messages observés : contraintes `utilisateur_pseudo_key`, `ck_utilisateur_email`, `ck_salon_type`, `ck_membre_role`, `ck_amitie_ordre`, `ck_message_dates` et exceptions des triggers pour salon vocal et auteur non membre. Tous les tests ont été exécutés sans conserver de données de test.

**Choix de conception.** Les clés primaires, clés étrangères, `UNIQUE` et `CHECK` règlent les contraintes simples. Des triggers empêchent l'envoi de messages dans un salon vocal et par un non-membre. Le contrôle du propriétaire est différé à la fin de la transaction pour permettre l'insertion du serveur avant celle de ses membres. Le coût des triggers est un travail supplémentaire à l'écriture, notamment sur l'envoi de messages ; ils garantissent cependant la cohérence même si plusieurs clients écrivent dans la base.

**Index.** `(salon_id, id DESC)` sur les messages sert les 50 derniers messages ; `(serveur_id, utilisateur_id)` sur les membres sert les accès par serveur ; les index des clés étrangères facilitent les jointures et les contrôles ; `(utilisateur_b, utilisateur_a)` complète la clé primaire d'amitié. Le détail se trouve dans les commentaires de `sql/01_schema.sql`.

## Mesure 2 — Latence des requêtes critiques

Exécution locale de `sql/03_requetes.sql` avec `\timing on` le 13 novembre 2026. Mesures relevées sur le second passage, après correction des lignes `\echo`. Ce sont des temps de requête, non des p50/p95.

| Requête | Périmètre | Durée relevée (ms) |
|---|---|---:|
| R1 | 50 derniers messages, salon chaud 775 | 0,936 |
| R1 | 50 derniers messages, salon moyen 522 | 0,396 |
| R1 | 50 derniers messages, salon clairsemé 342 | 0,179 |
| R2 | Droit d'écriture, membre du salon 775 | 0,292 |
| R3 | Activité par jour, serveur 118, octobre 2026 | 7,831 |

R1 pagine par `id < curseur_id` et non par `OFFSET`. R2 vérifie que le salon est textuel et que l'utilisateur est membre du serveur. R3 compte les messages et les auteurs distincts par jour en UTC.

## Mesure 3 — Plan d'exécution de R3

Extrait du plan réel, second passage :

```text
GroupAggregate (actual time=3.6..3.8 rows=31 loops=1)
  -> Sort (rows=1928)
       -> Nested Loop (rows=1928)
            -> Index Scan using salon_pkey on salon s (rows=4)
            -> Bitmap Heap Scan on message m (rows=482 loops=4)
                 Recheck Cond: (salon_id = s.id)
                 Filter: (envoye_le >= 2026-10-01 AND envoye_le < 2026-11-01)
                 Rows Removed by Filter: 4377
                 Buffers: shared hit=5633
                 -> Bitmap Index Scan on idx_message_salon_id_desc
Execution Time: 3.785 ms
```

- Le point coûteux dans l'accès aux messages est le **Bitmap Heap Scan** répété quatre fois ; il se trouve sous un **Nested Loop**. Le regroupement et le tri ajoutent aussi du travail.
- Il s'agit d'un **parcours indexé**, pas d'un parcours séquentiel complet : le moteur sélectionne les salons via l'index et retrouve leurs messages avec `idx_message_salon_id_desc`.
- Mais cet index ne contient pas `envoye_le` comme colonne de filtre. PostgreSQL doit relire et éliminer les messages hors octobre, d'où `Rows Removed by Filter`. Les temps `EXPLAIN` et `\timing` sont différents car ils ne mesurent pas exactement la même chose.

## Mesure 4 — Dénormalisations

### Vue matérialisée `app.activite_serveur_jour`

| Version de R3 | Durée relevée (ms) |
|---|---:|
| Requête sur tables normalisées | 7,831 |
| Lecture de la vue matérialisée | 0,136 |

- Vérification observée : `nb_lignes_differentes = 0`. Sur ce second passage, la lecture de la vue a été environ **57,6 fois plus rapide** que la requête normalisée (7,831 / 0,136), sur ce poste uniquement.
- **Gain attendu en lecture** : lecture de résultats par serveur et jour déjà agrégés, au lieu de calculer `COUNT(DISTINCT)` sur les messages.
- **Coût payé** : stockage supplémentaire, création et rafraîchissement de la vue (recalcul depuis les messages).
- **Risque** : données périmées si un message est ajouté, modifié ou supprimé avant le prochain rafraîchissement.
- **Garde-fou** : planifier un `REFRESH MATERIALIZED VIEW CONCURRENTLY app.activite_serveur_jour;` à une fréquence à définir selon le besoin de fraîcheur, et surveiller la date du dernier rafraîchissement. L'index unique `(serveur_id, jour)` rend le refresh concurrent possible ; des lectures ordinaires continuent pendant le refresh, qui consomme néanmoins des ressources.

### Compteur `app.serveur.nb_membres`

| Étape de preuve | Valeur | Résultat attendu |
|---|---:|---|
| Avant insertion | 478 | Nombre initial |
| Après insertion | 479 | Initial + 1 ; `test_ok = t` |
| Après suppression | 478 | Initial ; `test_ok = t` |

- **Gain en lecture** : `SELECT nb_membres` sans recalculer `COUNT(*)` sur la table des membres.
- **Coût payé** : une mise à jour du serveur à chaque insertion ou suppression de membre.
- **Risque** : contention sur la ligne du serveur lors d'inscriptions concurrentes, ou compteur incorrect si des écritures contournent le trigger.
- **Garde-fou** : trigger atomique dans la même transaction et vérification périodique par comparaison avec un `COUNT(*)` réel (`compteurs_incorrects` doit être **0**).
- **Choix** : incrémenter/décrémenter évite le coût d'un recomptage de tous les membres ; si l'on déplace un membre par `UPDATE serveur_id`, décrémenter l'ancien serveur et incrémenter le nouveau. Les autres mises à jour ne changent pas le compteur.

## Mesure 5 — Migration et égalité des résultats (Mission 3)

**Protocole :** `python load_nosql.py --messages-seulement` depuis `bench/`, puis `python bench.py --mission3 --n 100`. Les contrôles ne se limitent pas aux accusés d'insertion : les **15 965 partitions Cassandra non vides** ont été relues et comparées à PostgreSQL.

| Contrôle | PostgreSQL | MongoDB | Cassandra |
|---|---:|---:|---:|
| Messages après migration (5a) | **300 000** | **300 000** | **300 000** |
| 50 derniers IDs salon chaud 775 (5b) | 50 | 50 identiques | 50 identiques |
| 50 derniers IDs salon moyen 522 (5b) | 50 | 50 identiques | 50 identiques |
| Derniers IDs salon clairsemé 342 (5b) | 1 | 1 identique | 1 identique |

- Insertion Cassandra : **300 000 INSERT acquittés**, **15 965 partitions non vides**, et **300 000 messages relus** conformes à PostgreSQL.
- Recherche Cassandra naïve / fenêtres non vides : salon 775 **1/1**, salon 522 **16/14**, salon 342 **26/1**. Le nombre de fenêtres explorées explique la pénalité sur un salon presque vide.
- MongoDB utilise un index composé sur `(salon_id, _id DESC)` ; Cassandra partitionne par `(salon_id, bucket de 10 jours)` avec tri décroissant de l'identifiant Snowflake. La table supplémentaire de fenêtres non vides est une **dénormalisation** avec coût de maintenance.

## Mesure 6 — B1 : latence p50 / p95, 100 exécutions

Résultats du premier benchmark `python bench.py --mission3 --n 100`, latences **du script Python (client + requête)** sur ce poste :

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

**Analyse.** PostgreSQL est le plus rapide dans les trois salons. Dans le salon clairsemé, Cassandra naïf affiche p50 **10,86 ms** contre **1,23 ms** pour l'optimisation. Sur le salon moyen, cette optimisation est au contraire plus lente (**8,20 ms** contre **6,07 ms**) : elle ajoute une lecture de métadonnées qui ne se rentabilise pas systématiquement. Les tests de Mission 4 prouvent en outre le risque des tombstones ; voir `RUNBOOK_tombstones.md`.

## Mesure 7 — Redis et Neo4j : cohérence et performances, 100 exécutions

**Chargement réel :** Redis **1 650 clés** (dont 1 500 présences), Neo4j **5 000 utilisateurs**, **150 serveurs**, **15 000 relations d'amitié** et **7 984 appartenances**.

**Preuves de correction :** présences actives PostgreSQL/Redis **1 500/1 500** au contrôle ; résultats identiques pour le comptage en ligne des serveurs 118 (**159**), 80 (**7**), 52 (**1**) et 1 (**5**) ; recommandations B3 et B3 bis comparées sur **19 utilisateurs**, mêmes listes et scores. Le test Redis d'une clé `EX 2` a confirmé sa disparition après **2,4 s**. Les présences opérationnelles utilisent un TTL de **300 s** ; leur extinction après 300 s n'a pas été attendue dans cette expérience.

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

**Interprétation :** Redis gagne pour l'écriture d'une présence (**p50 0,21 ms** contre **0,42 ms**), mais perd pour le comptage des personnes en ligne dans un serveur (**2,31 ms** contre **0,26 ms**). Neo4j est plus lent que SQL sur les deux recommandations testées : B3 **1,25 ms** contre **0,24 ms** et B3 bis **1,20 ms** contre **0,22 ms** en p50. Ces résultats sont liés aux requêtes, aux index et à la faible taille du graphe : pas de classement universel des moteurs.

**Pourquoi vérifier l'égalité avant de mesurer ?** Une solution qui rend une liste incomplète ou incorrecte peut sembler plus rapide simplement parce qu'elle fait moins de travail : le benchmark ne serait pas pertinent.

**Expiration sans Redis :** PostgreSQL doit stocker `last_seen_at`, filtrer `last_seen_at > now()-interval '5 minutes'` à la lecture et planifier une purge si l'on veut supprimer physiquement les lignes obsolètes. Avec Redis, la clé expire nativement.

## Mesure 8 — Benchmark final complet, 300 exécutions

Commande : `python bench.py --n 300` (rechargement Redis/Neo4j avant lancement). Les chiffres ci-dessous sont **issus de la sortie Terminal du 13 novembre 2026** ; ils ne sont pas simulés. L'outil a exécuté 10 appels d'échauffement par cas avant de chronométrer. B3 bis est le seul sous-test avec **30 entrées** au lieu de 300, comme l'indique le script.

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

**Contrôles de correction :** B1 retourne les mêmes 50/50/1 IDs pour PostgreSQL, MongoDB et Cassandra ; B2b donne les mêmes comptes PostgreSQL/Redis ; B3 et B3 bis donnent les mêmes recommandations et scores ; B4 **31 jours**, **1 928 messages**, et résultats identiques entre PostgreSQL normalisé, vue matérialisée et MongoDB. L'égalité a été vérifiée **avant les chronométrages**.

**Bilan par besoin.** PostgreSQL conserve l'avantage sur B1 ; Redis gagne sur B2a et perd sur B2b ; PostgreSQL gagne sur les suggestions B3/B3 bis ; la vue matérialisée PostgreSQL de B4 (**p50 0,15 ms**) est environ **20,7 fois** plus rapide que la version SQL normalisée (**3,11 ms**), au prix du rafraîchissement et du risque de données périmées. MongoDB agrégé (1,77 ms) se situe entre les deux. Cassandra passe de 8,29 à 0,85 ms en p50 sur le salon clairsemé avec la liste de fenêtres non vides, mais reste moins rapide que PostgreSQL (0,14 ms) ici.

### Méthodologie et limites

- **Pourquoi le p95 ?** Il mesure la latence sous laquelle passent 95 % des observations et révèle mieux les requêtes lentes qu'une seule moyenne ; la moyenne masque les pics. Ici, 300 tests séquentiels ne constituent pas une charge concurrente.
- **Pourquoi échauffer ?** Les premières requêtes peuvent inclure initialisation des connexions, chargement de pages en mémoire et caches froids. Le benchmark teste ensuite un régime relativement chaud ; il faut aussi tester le froid avant de conclure pour la production.
- **Limite 1 — Échelle :** seulement 300 000 messages et 5 000 utilisateurs, très loin des milliards de messages et des partitions extrêmement chaudes de Discord. L'ordre des performances peut changer avec une RAM saturée.
- **Limite 2 — Concurrence :** requêtes appelées en séquence, sans vrais pics multi-utilisateurs, ni mesure de débit soutenu, de contention, de p99 sous charge ou de panne réplique.
- **Limite 3 — Réseau et plateforme :** cinq moteurs sur Docker Desktop, un seul Mac (M5, 16 Go), accès localhost et caches en mémoire ; pas de latence réseau distribuée, ni comparaison à ressources isolées identiques. B3 bis utilise 30 entrées et non 300.

**Portée du verdict :** ces chiffres établissent ce qui gagne **sur ce protocole local et ce jeu de données**, pas ce qui serait le plus rapide dans un cluster de production.

### Tombstones (Mission 4) — preuve complémentaire

- Lecture initiale : **50 messages / 2 ms** ; après **119 999 DELETE** dans une partition, échec `READ_TOO_MANY_TOMBSTONES` après **79 ms** (ce temps est un délai **d'échec**, pas une latence de lecture réussie).
- Suppression complète de la partition fictive : lecture de **0 message / 12 ms**, sans erreur.
- Second scénario avec purge locale contrôlée : un message conservé après `flush` + `compact` ; `gc_grace_seconds` temporairement 0 puis restauré à **864 000**. Procédure strictement de laboratoire, jamais une recommandation de production sans examen des répliques.

**Fichiers de preuve disponibles côté poste utilisateur :** `mission2_resultats.txt`, `mission3_chargement.txt`, `mission3_bench.txt`, `mission4_incident.txt`, `mission4_reparation.txt`, `mission4_incident_purge.txt`, `mission4_logs.txt`, `mission5_chargement.txt`, `mission5_bench.txt`, `mission6_bench.txt`.
