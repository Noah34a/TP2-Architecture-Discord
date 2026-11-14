# TP2 Discord - Dossier d'architecture (version 2)

B3 Ynov Montpellier - Conception et architecture des données

Ce dossier reprend mon TP1 et les tests faits au TP2. Le but était de voir si les bases de données que j'avais choisies au début étaient vraiment adaptées à une petite plateforme comme Discord.

**Petite précision :** mon PDF du TP1 fait 7 pages et s'arrête au début du 4.b. Je n'avais pas rédigé les parties 4.c à 4.f, ni les cinq hypothèses chiffrées demandées pour le jour 2. Je les complète ici avec ce que j'avais écrit et les résultats des tests, sans faire comme si je les avais prévues avant.

## 0. Ce que j'avais retenu de Discord

Discord avait de plus en plus de messages à gérer. Ils utilisaient MongoDB au début, puis les lectures sont devenues moins régulières quand il y avait trop de données. Ils sont ensuite passés à Cassandra puis ScyllaDB pour mieux gérer les gros volumes.

Dans mon TP1, j'avais retenu trois chiffres : **100 millions de messages par jour**, environ **50 % de lectures et 50 % d'écritures**, et **100 Mo** comme seuil de surveillance pour les partitions Cassandra. Ce sont des chiffres tirés de l'étude de Discord, pas de mes mesures.

## 1. Les données de ma plateforme

### 1.a. Les éléments principaux

J'ai des utilisateurs, des serveurs, des salons, des membres, des messages, des pièces jointes, des amitiés et des présences. Un serveur Discord, ici, c'est une communauté. Un utilisateur peut rejoindre un serveur et envoyer des messages suivant ses droits. Il y a trois rôles : **membre, modérateur et propriétaire**.

### 1.b. Les règles importantes

| Directement dans la base | Vérifiées par du code ou un trigger | Autre fonctionnement |
|---|---|---|
| Email unique | Vérifier qu'on est membre avant d'écrire | Une présence expire après 5 min |
| Un nom de salon unique par serveur | Interdire un message dans un salon vocal | Les fichiers peuvent être gardés séparément |
| Une amitié enregistrée une seule fois | Garder un seul propriétaire | Un cache ne remplace pas la vraie base |
| Seulement les trois rôles prévus | Vérifier le droit de supprimer un message | Redis peut servir pour les états temporaires |

### 1.c. Le MCD

J'ai gardé le rôle dans l'**appartenance** entre un utilisateur et un serveur. Un propriétaire est aussi un membre. Les amitiés sont enregistrées une seule fois par paire. Et les pièces jointes sont séparées des messages dans le MCD, car elles n'ont pas toutes la même forme.

Mon schéma est dans `mcd.md`.

### 1.d. Ce que j'ai réellement créé en SQL

Cette partie était vide dans mon PDF du TP1. Pour le TP2, j'ai créé les tables suivantes avec PostgreSQL :

| Table | Ce qu'elle garde |
|---|---|
| `app.utilisateur` | Les comptes, pseudos et emails |
| `app.serveur` | Les serveurs, leur propriétaire et le nombre de membres |
| `app.salon` | Les salons texte/vocaux et leur serveur |
| `app.membre` | Qui fait partie de quel serveur, avec quel rôle |
| `app.message` | Les messages, leur auteur, leur salon, leurs dates et `pieces_jointes JSONB` |
| `app.amitie` | Les amitiés entre deux utilisateurs |
| `app.presence` | Une version SQL des présences pour faire les comparaisons |

J'ai ajouté des clés primaires, étrangères, des contraintes `CHECK` et des index. Par exemple, l'index `(salon_id, id DESC)` aide à lire les 50 derniers messages. Les **8 tests d'intégrité** ont marché.

Il y a deux différences avec mon MCD du TP1 : dans mon SQL, les pièces jointes sont dans un champ JSONB du message et pas dans une table à part. Et le propriétaire existe dans `serveur.proprietaire_id` ainsi que par son rôle dans `membre`. Pour éviter que les deux valeurs se contredisent, j'ai mis des contrôles avec des triggers. C'est moins simple que ce que j'avais dessiné au départ, mais j'ai testé que la règle est respectée.

### 1.e. Les questions encore ouvertes

J'avais noté cinq questions : peut-on mettre plusieurs pièces jointes dans un message, envoyer seulement une image, quitter un serveur en étant propriétaire, conserver les messages supprimés, et mettre à jour les suggestions immédiatement ? Je n'ai pas de réponse client à ces questions, donc ce sont toujours des points à décider.

## 2. Les accès et les volumes

### 2.a. Ce que j'avais prévu au TP1

| Action | Fréquence estimée | Temps visé |
|---|---:|---:|
| Envoyer un message | 10/s | 80 ms |
| Lire les 50 derniers messages | 30/s | 80 ms |
| Vérifier les droits | 10/s | 20 ms |
| Voir qui est en ligne | 10/s | 80 ms |
| Suggérer des serveurs | 3/s | 200 ms |
| Calculer les statistiques | 1/jour | Pas urgent |
| Supprimer un message | « À la seconde » dans mon TP1 | 80 ms |
| Rechercher un message | 1/s | 300 ms |

Ces fréquences étaient des **estimations**, pas des tests de charge. Au TP2, j'ai mesuré des requêtes sur mon Mac, mais je n'ai pas simulé 30 personnes qui lisent en même temps chaque seconde.

### 2.b. Les calculs du TP1

Avec **100 millions de messages par jour**, on arrive à environ **1 157 messages par seconde** en moyenne et **3 472/s** avec un pic supposé trois fois plus fort. À **300 octets par message**, ça fait **30 Go/jour**, donc **10,95 To/an** si ça continue au même rythme.

Avec l'index théorique, j'avais calculé **34 Go** pour 100 millions de messages, alors que l'exemple supposait **16 Go de RAM**. C'est pour ça qu'un gros historique peut finir par provoquer plus de lectures sur disque. Le calcul avec 12 nœuds de 1 To et trois copies donnait environ **4 To logiques compressés** ; c'était seulement un ordre de grandeur.

### 2.c. Les optimisations possibles

Au TP1, j'avais pensé à garder les derniers messages en cache et à calculer les statistiques une fois par jour. Pendant le TP2, j'ai surtout testé deux choses dans PostgreSQL :

- Une **vue matérialisée** pour les statistiques : **0,15 ms en p50** au lieu de **3,11 ms** avec le calcul normal.
- Un **compteur de membres** maintenu par trigger : il est bien passé de **478 à 479**, puis revenu à **478**.

Je n'ai pas testé de cache Redis pour les 50 messages. Je ne peux donc pas dire qu'il serait plus rapide dans ce cas.

Pour le compteur, j'ai choisi d'ajouter ou enlever 1 avec un trigger plutôt que de recompter tous les membres après chaque changement. Un changement de serveur enlève 1 d'un côté et ajoute 1 de l'autre. Pour la vue, je proposerais un rafraîchissement chaque nuit avec `REFRESH MATERIALIZED VIEW CONCURRENTLY`, mais je n'ai pas mis en place de tâche automatique pendant le TP. Entre deux rafraîchissements, les statistiques peuvent être en retard.

## 3. Où stocker les messages ?

### 3.a et 3.b. Les différentes bases

PostgreSQL est pratique ici parce que j'ai beaucoup de relations entre les utilisateurs, les serveurs et les messages. MongoDB peut stocker les messages sans problème, mais les lectures peuvent coûter plus cher quand les données ne tiennent plus en mémoire. Cassandra est fait pour mieux répartir de très gros volumes, mais son fonctionnement est plus compliqué. Redis est utile pour des données temporaires, pas pour garder seul tout l'historique.

C'est pour ça que j'étais déjà parti sur **PostgreSQL + Redis** au TP1.

### 3.c. Le découpage des messages dans Cassandra

Pour un salon imaginaire qui reçoit **10 millions de messages par an** (300 octets par message), j'avais comparé trois solutions :

| Découpage | Taille calculée |
|---|---:|
| Tout le salon dans une partition | 3 000 Mo |
| Une partition par période de 10 jours | Environ 82 Mo |
| Une partition par jour | Environ 8,2 Mo |

J'avais préféré la **période de 10 jours** : ça évite une énorme partition, sans créer autant de petites partitions qu'un découpage par jour. Par contre, dans un salon peu actif, le programme peut chercher dans beaucoup de périodes vides.

C'est ce que j'ai vu au TP2 : pour le salon clairsemé, Cassandra a parcouru **26 périodes** avec la méthode simple, contre **1** avec une table qui connaît les périodes non vides. Ça confirme le problème des fenêtres vides, mais ça ne prouve pas le calcul de 82 Mo à très grande échelle.

L'optimisation n'a pas aidé tous les salons. Sur le salon moyen, elle a demandé **14 fenêtres au lieu de 16**, mais elle était quand même plus lente (**8,20 ms contre 6,07 ms en p50**). En fait, il faut aussi lire la liste des fenêtres non vides et la tenir à jour. Ça vaut le coup surtout si on évite vraiment beaucoup de recherches inutiles.

### 3.d. Les problèmes possibles

Dans mon TP1, j'avais parlé des champs `NULL`, des suppressions massives, des salons trop actifs et des pauses mémoire Cassandra.

Pour les suppressions, j'ai pu reproduire le problème. Après **119 999 suppressions**, Cassandra a répondu `READ_TOO_MANY_TOMBSTONES`. Le détail est dans `RUNBOOK_tombstones.md`. Je n'ai pas testé les pauses de la JVM ni un vrai cluster avec plusieurs machines.

## 4. Mon architecture après les tests

### 4.a. Ce que j'avais choisi au départ

Dans le tableau 4.a de mon vrai TP1, j'avais déjà choisi **PostgreSQL pour presque tout** (utilisateurs, serveurs, messages, amitiés, droits, statistiques) et **Redis pour les présences en ligne**. Les fichiers joints peuvent être stockés à part, avec leur référence dans PostgreSQL.

### 4.b. Le schéma

J'ai mis l'architecture dans `architecture.md`. Les messages et données importantes restent dans PostgreSQL. Redis garde les clés de présence qui expirent au bout de **300 secondes**. MongoDB, Cassandra et Neo4j sont seulement des bases utilisées pour les essais de ce TP.

### 4.c. Mes trois décisions après les mesures

**1. Je garde PostgreSQL pour les messages.** Sur les trois salons, il est plus rapide que MongoDB et Cassandra. Par exemple, sur le salon chaud, il est à **0,14 ms en p50**. Avec seulement 300 000 messages, je ne vois pas de raison d'ajouter un moteur plus compliqué. Je réexaminerais le choix si on dépasse régulièrement **80 ms au p95 côté application**, après avoir essayé d'optimiser les requêtes.

**2. Je garde les droits dans PostgreSQL.** Le TP2 montre qu'on peut refuser un utilisateur non membre ou un message envoyé dans un salon vocal. Je préfère ça plutôt que d'utiliser uniquement un cache Redis, qui pourrait ne pas être à jour. Je n'ai pas testé le cas où un utilisateur se fait exclure exactement en même temps qu'il écrit.

**3. Je garde Redis pour les présences.** Redis est plus rapide pour renouveler un statut : **0,13 ms** contre **0,26 ms** dans le benchmark final. Il fait aussi expirer les clés automatiquement. En revanche, PostgreSQL est plus rapide pour compter les membres en ligne dans notre test. Donc Redis sert surtout à gérer les présences, pas à remplacer toute la base.

Ces trois décisions sont expliquées ici au Jour 2 à partir du choix de mon TP1. Elles n'étaient pas rédigées dans une section 4.c du PDF original.

### 4.d. Le risque principal

Si un message est supprimé de PostgreSQL mais reste dans un cache Redis, quelqu'un pourrait quand même le voir. Pour éviter ça, je n'active pas de cache de messages sans test. Si je le fais plus tard, il faudra vider le cache après chaque modification ou suppression, et prévoir une expiration courte.

### 4.e. Si je ne peux garder que deux bases

Je garde **PostgreSQL et Redis**, comme au TP1. PostgreSQL est la base principale. Redis sert aux présences. La vue matérialisée reste dans PostgreSQL, donc je n'ai pas besoin de MongoDB, Cassandra ou Neo4j pour cette petite version.

### 4.f. Mes cinq attentes du TP1 comparées aux résultats

Je n'avais pas écrit cinq hypothèses chiffrées dans le PDF du TP1. Je reprends donc cinq idées que j'avais vraiment notées pour les comparer aux tests. Quand je n'ai pas testé exactement la même chose, je le dis.

| Ce que je pensais au TP1 | Valeur prévue | Ce que j'ai mesuré | Conclusion |
|---|---|---|---|
| Les 50 derniers messages doivent s'afficher vite | Objectif de 80 ms | PostgreSQL : p95 0,16 / 0,14 / 0,16 ms | Ça marche sur mon Mac, pas encore testé avec 30 lectures/s |
| Les droits doivent être vérifiés rapidement | Objectif de 20 ms | R2 : 0,292 ms sur une exécution | Objectif tenu sur ce test, pas de test avec plusieurs utilisateurs en même temps |
| La présence doit expirer seule | 300 secondes | Clé Redis de test expirée après 2,4 s avec TTL 2 s | Le TTL fonctionne, mais j'ai pas attendu les 300 s |
| Les périodes Cassandra évitent les partitions trop grosses | Environ 82 Mo dans mon calcul théorique | 15 965 partitions ; 26 fenêtres naïves / 1 non vide sur le petit salon | Je vois le coût des périodes vides, mais je n'ai pas mesuré la taille théorique à 10 M de messages |
| Calculer les stats à l'avance évite de tout recalculer | Une fois par jour, pas de gain chiffré prévu | 3,11 ms → 0,15 ms en p50 avec la vue | Gros gain sur ma machine, mais il faut actualiser les données |

Ce tableau compare les idées présentes dans mon TP1 aux vrais tests du TP2. **Je n'avais pas annoncé les facteurs de gain avant les expériences**, donc je ne vais pas en inventer maintenant.

## 5. Bilan de la Mission 6

| Test | Ce que j'ai constaté |
|---|---|
| B1, derniers messages | PostgreSQL est le plus rapide sur les trois salons |
| B2, présences | Redis gagne à l'écriture, PostgreSQL gagne pour le comptage |
| B3, suggestions | PostgreSQL est plus rapide que Neo4j sur ce petit graphe |
| B4, statistiques | La vue matérialisée PostgreSQL gagne (0,15 ms en p50) |
| Cassandra, suppressions | Trop de tombstones peuvent faire échouer une lecture |

### Pourquoi je regarde le p95 ?

La moyenne ne montre pas bien les requêtes qui sont beaucoup plus lentes que les autres. Le **p95** permet de regarder ce qui se passe pour les 95 % de requêtes les plus rapides, donc de mieux repérer les cas où le temps commence à monter. J'ai aussi fait **10 passages d'échauffement** avant les mesures pour ne pas mélanger les premiers chargements avec les temps habituels.

### Ce que mes tests ne montrent pas

Il y a trois grosses limites : je n'ai que **300 000 messages**, mes requêtes ne sont pas lancées avec une vraie foule d'utilisateurs en même temps, et tous mes moteurs tournent **sur un seul Mac avec Docker**. Donc je ne peux pas affirmer que PostgreSQL sera toujours le meilleur à l'échelle de Discord.

### Quand est-ce que je changerais d'architecture ?

- Si la lecture des messages dépasse régulièrement **80 ms au p95 côté application**, même après optimisation et avec une vraie charge, je testerais une solution pour de gros volumes.
- Si les suggestions deviennent trop lentes (objectif du TP1 : **200 ms**) avec un graphe plus complexe, je referais une comparaison avec Neo4j.
- Si la recherche de messages devient trop lente (objectif : **300 ms**), je testerais d'abord les index PostgreSQL puis éventuellement un moteur de recherche.
- Pour un cache Redis des messages, je demanderais une vraie preuve de gain **sur les mêmes 50 messages**, et je vérifierais aussi qu'un message supprimé ne reste pas affiché.

## Conclusion

Au départ, j'avais choisi PostgreSQL et Redis. Après les tests, **je garde ce choix**. PostgreSQL suffit pour gérer les messages, les relations et les contrôles dans notre miniature. Redis est utile pour la présence qui expire automatiquement. Les autres bases ont servi à comparer et à comprendre leurs avantages, mais elles ajoutent de la complexité sans gain suffisant ici.

Mes chiffres, y compris les p50 et p95, sont dans `MESURES.md`. Les tests de suppression Cassandra sont dans `RUNBOOK_tombstones.md`. Les schémas sont dans `mcd.md` et `architecture.md`.
