# TP2 Discord - Tombstones Cassandra (Mission 4)

### Fiche rapide si une lecture de salon plante

1. Je récupère le salon, le `bucket` et le message d'erreur exact.
2. Je cherche `READ_TOO_MANY_TOMBSTONES` dans les logs Cassandra, puis je regarde les suppressions et les stats de la table.
3. Je vérifie quels messages doivent encore exister. Je ne supprime **pas** toute la partition si elle contient des données à garder.
4. Pour une vraie base, je prépare un correctif adapté avec les répliques, les sauvegardes et la réparation du cluster. Je ne mets **pas** `gc_grace_seconds` à 0 directement.
5. Après correction, je vérifie que la lecture marche **et** renvoie les messages attendus. Je surveille les nouvelles erreurs et le p95.

Les deux méthodes que j'ai testées plus bas sont des **tests locaux**, pas deux commandes à lancer au hasard en production.

## 1. Le but du test

Dans cette mission, je devais montrer ce qui se passe quand on supprime énormément de messages dans Cassandra. Pour ne pas toucher aux vrais messages du TP, j'ai utilisé une partition de test avec `salon_id = -1` et `bucket = 0`.

Dans mon schéma Cassandra, les messages sont rangés par salon et par période de 10 jours. Ça limite la taille des partitions, mais ça n'empêche pas tous les problèmes quand on supprime beaucoup de données.

## 2. Reproduire le problème

Depuis le dossier `bench`, j'ai lancé :

```bash
python tombstones.py 2>&1 | tee ../mission4_incident.txt
```

J'ai créé **120 000 messages** dans la partition, puis supprimé **119 999 messages un par un**.

| Moment du test | Résultat |
|---|---|
| Avant les suppressions | 50 messages lus en **2 ms** |
| Après les 119 999 suppressions | Échec après **79 ms** |
| Erreur affichée | `READ_TOO_MANY_TOMBSTONES` |

Les **79 ms** sont le temps avant l'erreur, pas le temps d'une lecture réussie.

### Pourquoi ça bloque ?

Dans Cassandra, supprimer un message ne l'efface pas forcément tout de suite du disque. Il reste un marqueur de suppression appelé **tombstone**. Quand il y en a trop, Cassandra doit en parcourir énormément pour retrouver les messages encore présents, et la requête peut échouer.

Le script insère des messages numérotés de **1 à 120 000**, puis supprime ceux de **2 à 120 000**. Il reste donc le numéro **1**, qui est le plus ancien. Comme Cassandra lit les identifiants du plus récent au plus ancien, il tombe d'abord sur tous les messages supprimés avant d'arriver au seul qui reste. Il doit donc traverser énormément de tombstones. Le moteur finit par refuser la lecture quand le seuil de sécurité est dépassé, pour éviter qu'une requête utilise trop de ressources et ralentisse les autres.

Dans les logs du deuxième essai, j'ai retrouvé ces messages :

```text
WARN  Read 0 live rows and 100001 tombstone cells ...
ERROR Scanned over 100001 tombstones during query ... query aborted
```

Pour diagnostiquer ça, je regarde la requête qui plante, la partition concernée, les logs et les éventuelles suppressions en masse. Je peux aussi utiliser `nodetool tablestats discord.messages_par_salon` pour voir l'état de la table.

## 3. Premier test de correction : supprimer toute la partition

J'ai lancé :

```bash
python tombstones.py --reparer 2>&1 | tee ../mission4_reparation.txt
```

| Avant | Après |
|---|---|
| 50 messages lus en **2 ms** | **0 message en 12 ms**, sans erreur |

Ça fonctionne pour ce test, mais **ça supprime aussi le dernier message**. Donc ce n'est pas une bonne solution si je dois conserver des messages. Ça ne prouve pas non plus que tous les marqueurs ont déjà disparu du disque.

## 4. Deuxième test : nettoyer les tombstones

J'ai refait l'incident une deuxième fois. Avant les suppressions, je lisais 50 messages en **3 ms**. Après les 119 999 suppressions, la lecture a échoué au bout de **53 ms**.

Sur **mon Cassandra local uniquement**, j'ai ensuite essayé de purger les tombstones :

```bash
docker compose --profile colonne exec -T cassandra cqlsh -e "ALTER TABLE discord.messages_par_salon WITH gc_grace_seconds = 0;"
docker compose --profile colonne exec -T cassandra nodetool flush discord messages_par_salon
docker compose --profile colonne exec -T cassandra nodetool compact discord messages_par_salon
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT message_id FROM discord.messages_par_salon WHERE salon_id = -1 AND bucket = 0 LIMIT 50;"
```

Cette fois, Cassandra a répondu **sans erreur** et j'ai retrouvé **le seul message restant (`message_id = 1`)**. Je n'ai pas relevé le temps de cette lecture, donc je ne peux pas le comparer aux autres.

J'ai ensuite remis le réglage de départ :

```bash
docker compose --profile colonne exec -T cassandra cqlsh -e "ALTER TABLE discord.messages_par_salon WITH gc_grace_seconds = 864000;"
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT gc_grace_seconds FROM system_schema.tables WHERE keyspace_name = 'discord' AND table_name = 'messages_par_salon';"
```

Le résultat était bien **864000 secondes**.

**Attention :** je n'ai fait ça que pour le TP, sur une seule instance locale. Dans un vrai cluster, mettre `gc_grace_seconds` à 0 et compacter sans vérifier les répliques pourrait faire réapparaître des données supprimées. Il ne faut pas reproduire cette commande en production telle quelle.

## 5. Ce que je ferais pour éviter le problème

- Garder des partitions pas trop grosses en séparant les messages par salon et période.
- Éviter de supprimer des dizaines de milliers de messages un par un quand une autre méthode est possible.
- Ne pas écrire des champs `NULL` dans Cassandra si le champ est absent ; utiliser `UNSET_VALUE` dans le script.
- Surveiller les erreurs, le nombre de tombstones et les temps de réponse.
- Ne jamais supprimer une partition entière si elle contient encore des messages à garder.

### L'alerte que je mettrais sur un vrai serveur

Je voudrais être prévenu dès qu'une requête renvoie `READ_TOO_MANY_TOMBSTONES`, même une seule fois. Je surveillerais aussi les avertissements de tombstones dans les logs et la **latence p95** des lectures par salon. Par exemple, si elle dépasse régulièrement l'objectif de **80 ms** qu'on avait fixé au TP1, je chercherais le problème avant que les lecteurs soient bloqués. Ce sont des **alertes que je propose**, pas des alertes que j'ai vraiment installées pendant le TP.

En cas d'incident, je commencerais par identifier la partition touchée et regarder les logs. Je ne lancerais pas directement une purge : je vérifierais d'abord s'il reste des messages à conserver et, sur un vrai cluster, l'état des répliques et des réparations. C'est justement pour ça que mes deux tests de correction ne sont pas interchangeables.

## 6. Comment je vérifie que c'est réparé

La requête ne doit plus afficher `READ_TOO_MANY_TOMBSTONES`. Je vérifie aussi **ce qu'elle renvoie** : 0 message dans le test où je vide toute la partition, ou bien 1 message dans le test où je garde le dernier.

Les données normales du TP ne doivent pas avoir changé, car j'ai utilisé une partition fictive.

## Conclusion

J'ai réussi à reproduire le problème des tombstones, puis à tester deux façons différentes de le résoudre sur la base locale. La première permet de vider complètement une partition ; la deuxième a permis de retrouver le message encore présent. Ce que je retiens, c'est qu'avec Cassandra il faut prévoir les suppressions dès qu'on choisit comment répartir les données.

Preuves : `mission4_incident.txt`, `mission4_reparation.txt`, `mission4_incident_purge.txt`, `mission4_logs.txt` et `bench/tombstones.py`.
