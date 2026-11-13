# TP2 Discord — RUNBOOK : incident de tombstones Cassandra

## 1. Objectif et périmètre

Reproduire un incident de lecture causé par un grand nombre de tombstones dans Cassandra 4.1, diagnostiquer son origine et tester une stratégie alternative. Le test utilise uniquement la partition fictive `(salon_id=-1, bucket=0)` de `discord.messages_par_salon` ; elle est séparée des données métier du TP.

Le schéma de la Mission 3 utilise la clé de partition `(salon_id, bucket)` et le clustering `message_id` en ordre décroissant. Le bucket représente une fenêtre de 10 jours dérivée de l'identifiant Snowflake. Cette organisation limite la taille des partitions réelles, mais ne supprime pas à elle seule le risque lié aux suppressions répétées.

## 2. Symptôme observé

Exécution sur le Mac du TP, avec Cassandra 4.1 sous Docker, depuis le dossier `bench/` :

```bash
python tombstones.py 2>&1 | tee ../mission4_incident.txt
```

Résultats **réellement observés** :

| Étape | Résultat |
|---|---|
| Insertion de 120 000 messages dans une partition fictive | Réussie |
| Lecture initiale des 50 derniers messages | 50 messages lus en **2 ms** |
| Suppression individuelle de 119 999 messages | Exécutée ; il reste un message métier |
| Nouvelle lecture (`LIMIT 50`) | **Échec** après **79 ms** : `READ_TOO_MANY_TOMBSTONES` |

Le délai de 79 ms est le délai **avant échec**. Ce n'est pas une latence de lecture réussie.

## 3. Cause et diagnostic

Une suppression Cassandra n'efface pas immédiatement les cellules sur disque. Elle inscrit des *tombstones* pour masquer les valeurs supprimées, notamment afin que la suppression puisse se propager aux répliques. Lors de la lecture, Cassandra doit examiner ces marqueurs. La requête portant sur la partition surchargée franchit ici le seuil de sécurité du moteur et échoue avec `READ_TOO_MANY_TOMBSTONES`.

Pour investiguer un incident similaire :

1. Identifier la requête en échec et sa clé de partition (`salon_id`, `bucket`).
2. Vérifier les logs Cassandra et la présence du message `READ_TOO_MANY_TOMBSTONES`.
3. Examiner les métriques de table et le comportement de compaction (par exemple `nodetool tablestats discord.messages_par_salon`).
4. Vérifier s'il existe une série de suppressions ligne par ligne, des valeurs `NULL` écrites dans Cassandra, des partitions trop volumineuses ou des TTL massivement expirés.

Ces pistes sont des vérifications recommandées ; **seule l'erreur reproduite dans les résultats ci-dessus a été constatée sur ce Mac**.

## 4. Test de suppression par partition

```bash
python tombstones.py --reparer 2>&1 | tee ../mission4_reparation.txt
```

Résultats **réellement observés** :

| Étape | Résultat |
|---|---|
| Lecture avant suppression | 50 messages en **2 ms** |
| Suppression de la partition complète `(salon_id=-1, bucket=0)` | Réussie |
| Lecture après suppression | **0 message en 12 ms**, sans erreur |

La suppression par partition est représentée par un marqueur de suppression de plage/partition au lieu de 119 999 suppressions par ligne. Elle a permis une lecture vide sans erreur dans ce scénario.

**Limite essentielle :** ce test supprime également le dernier message. Il ne rétablit pas les messages ni ne démontre que toutes les tombstones ont disparu des fichiers SSTable. Les deux mesures (50 messages puis 0 message) ne portent pas sur le même contenu et ne prouvent pas un gain de performance à résultat égal.

## 5. Second correctif testé : purge contrôlée des tombstones (environnement local uniquement)

L'incident a été reproduit une deuxième fois pour tester la purge. Les résultats relevés sont : **50 messages en 3 ms** avant suppression, puis échec de lecture **après 53 ms** à la suite de 119 999 suppressions. Les logs Cassandra sauvegardés dans `mission4_logs.txt` confirment le diagnostic :

```text
WARN  Read 0 live rows and 100001 tombstone cells ...
ERROR Scanned over 100001 tombstones during query ... query aborted
```

Une purge a ensuite été effectuée **uniquement sur le conteneur Cassandra local du TP**, en mettant temporairement la période de grâce à zéro puis en vidant la memtable et en lançant une compaction :

```bash
docker compose --profile colonne exec -T cassandra cqlsh -e "ALTER TABLE discord.messages_par_salon WITH gc_grace_seconds = 0;"
docker compose --profile colonne exec -T cassandra nodetool flush discord messages_par_salon
docker compose --profile colonne exec -T cassandra nodetool compact discord messages_par_salon
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT message_id FROM discord.messages_par_salon WHERE salon_id = -1 AND bucket = 0 LIMIT 50;"
```

**Résultat observé :** la requête s'exécute sans erreur et retourne **un seul message, `message_id = 1`**, celui qui n'avait pas été supprimé. Aucune durée de lecture après compaction n'a été relevée ; il ne faut pas en inventer. Ce résultat valide la récupération du message restant après purge pour ce test local.

Le paramètre a été remis à sa valeur initiale immédiatement après le test :

```bash
docker compose --profile colonne exec -T cassandra cqlsh -e "ALTER TABLE discord.messages_par_salon WITH gc_grace_seconds = 864000;"
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT gc_grace_seconds FROM system_schema.tables WHERE keyspace_name = 'discord' AND table_name = 'messages_par_salon';"
```

**Valeur retournée : `864000` secondes.**

**Précaution :** ce protocole est une démonstration sur un unique nœud local, pas un runbook de purge pour la production. En présence de répliques déconnectées ou non réparées, réduire `gc_grace_seconds` et compacter peut permettre la réapparition de données supprimées (*zombies*). En production, il faut examiner la topologie, les réparations, les sauvegardes, la rétention et le cycle des SSTables avec l'équipe d'exploitation avant toute purge.

## 6. Prévention et remédiation adaptées à une vraie application

- Conserver les partitions bornées par **salon et fenêtres de dix jours** ; surveiller les salons extrêmement actifs et adapter le découpage si nécessaire.
- Éviter les campagnes de `DELETE` ligne par ligne. Lorsque tout un bloc de données doit expirer, privilégier une politique de rétention et un découpage compatible avec des suppressions par partition, si les exigences métier le permettent.
- Écrire `UNSET_VALUE` pour les champs Cassandra absents plutôt qu'un `NULL` qui crée une tombstone.
- Si des données doivent rester accessibles, ne pas supprimer leur partition. Prévoir une migration/reconstruction contrôlée des messages à conserver avant de changer la stratégie de suppression.
- Surveiller les tombstones parcourues, le nombre de partitions, la taille des partitions, les erreurs de lecture, les latences p95 et les compactions.
- Ne pas abaisser ou augmenter les seuils de tombstones pour masquer l'incident. Ne pas lancer de compaction forcée ni modifier `gc_grace_seconds` sans évaluer les répliques, les sauvegardes et l'espace disque : une suppression prématurée des tombstones peut réintroduire des données anciennes.

## 7. Vérification après correction

- La requête de lecture ciblée ne doit plus renvoyer `READ_TOO_MANY_TOMBSTONES`.
- Les résultats doivent correspondre au jeu de données attendu **après** l'opération : zéro message pour le test de suppression de partition, ou messages préservés dans un scénario où ils doivent être conservés.
- Relancer le contrôle de cohérence entre PostgreSQL, MongoDB et Cassandra sur les **données métier**. Le test fictif de la Mission 4 ne doit pas les modifier.
- Reporter les mesures obtenues sans confondre délai d'échec, lecture réussie et lecture vide.

## 8. Bilan

L'incident est reproduit : après **119 999 suppressions individuelles**, la lecture échoue avec `READ_TOO_MANY_TOMBSTONES`. Le scénario alternatif de suppression d'une partition permet une lecture vide en **12 ms** sans erreur ; le test distinct de purge/compaction a permis de retrouver **le message restant**. Cela illustre un risque propre aux suppressions massives dans Cassandra et l'importance d'un modèle de partitionnement et de rétention pensé en amont.

**Fichiers de preuve :** `mission4_incident.txt`, `mission4_reparation.txt`, `mission4_incident_purge.txt`, `mission4_logs.txt` et `bench/tombstones.py`.
