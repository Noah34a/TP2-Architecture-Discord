# TP2 — MESURES

Bachelor 3 Ynov Montpellier — Architecture des données, plateforme miniature de discussion.

**Règle :** les volumes sont contrôlés sur le poste de travail ; les temps de latence ci-dessous ne doivent pas être inventés. Ajouter les sorties du Terminal lors de l'exécution.

## Machine

- Machine : MacBook Pro (modèle de processeur et mémoire totale à préciser).
- Système : macOS (version à préciser).
- Docker Desktop : utilisé avec PostgreSQL 16, MongoDB 7, Redis 7, Neo4j 5 ; Cassandra 4.1 sera lancé à la mission 3.
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

## Mesure 5 — Vérification de la migration (mission 3)

À remplir avec la sortie de `bench/load_nosql.py --messages-seulement` et `bench/bench.py --mission3 --n 100`.

| Contrôle | PostgreSQL | MongoDB | Cassandra |
|---|---:|---:|---:|
| Nombre total de messages (5a) | 300 000 | À relever | À relever |
| IDs identiques salon 775 (5b) | 50 attendus | À tester | À tester |
| IDs identiques salon 522 (5b) | 50 attendus | À tester | À tester |
| IDs identiques salon 342 (5b) | 1 attendu | À tester | À tester |

Pour Cassandra, vérifier l'égalité des comptages par les insertions acquittées et, surtout, par une lecture de chaque partition non vide connue depuis PostgreSQL : ne pas utiliser `SELECT count(*)` global en production.

## Mesure 6 — p50 et p95 des 50 derniers messages (mission 3)

Coller ici le tableau produit par `python bench.py --mission3 --n 100`. Les mesures réelles seront obtenues sur le Mac, sans données simulées.

## Mesures 7 et 8 — À réaliser aux missions 5 et 6

Conserver les résultats bruts des benchmarks et le modèle de machine pour le rendu.
