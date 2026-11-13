"""Génère l'export « legacy » de la plateforme de discussion à reconstruire (modèle inspiré de Discord).

Usage : python generate_data.py [--messages 300000] [--seed 42]
Produit dans le dossier courant :
  utilisateurs.csv, serveurs.csv, salons.csv, membres.csv, messages.csv, amities.csv
Aucune dépendance hors bibliothèque standard. Les chiffres sont déterministes pour une graine donnée.

Particularité voulue : la répartition des messages est très inégale (quelques salons très actifs,
beaucoup de salons presque vides), comme sur la vraie plateforme. Les identifiants de message sont
des « Snowflake » : (millisecondes depuis 2015-01-01) << 22 | compteur, donc triables par date.
"""
import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone

EPOCH_MS = 1420070400000  # 2015-01-01T00:00:00Z, époque des Snowflake Discord
DEBUT = datetime(2026, 1, 1, tzinfo=timezone.utc)
FIN = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)

PSEUDOS = ["lynx", "pixel", "orbit", "nova", "echo", "zen", "byte", "kiwi", "raven", "fox", "luna", "atlas", "mango", "sparks"]
NOMS_SERVEUR = ["Les Garrigues Gamers", "Atelier Python", "Club Escalade", "Ciné Club", "Bachelor B3", "Musique Libre", "Foot Entre Potes", "Open Source FR", "Cuisine & Co", "Retro Games"]
SALONS_TEXTE = ["general", "annonces", "aide", "memes", "projets", "off-topic", "ressources", "idees", "partage", "hors-sujet"]
SALONS_VOCAL = ["vocal-1", "vocal-2", "detente"]
PHRASES = ["salut tout le monde", "quelqu'un a vu le dernier patch ?", "ok pour ce soir", "merci !", "je regarde ça demain",
           "mdr", "qui est dispo pour jouer ?", "voilà le lien", "bien vu", "on se retrouve à 21h", "super idée", "je confirme"]


def snowflake(dt, seq):
    ms = int(dt.timestamp() * 1000) - EPOCH_MS
    return (ms << 22) | (seq & 0x3FFFFF)


def piece_jointe(r):
    t = r.random()
    if t < 0.5:
        return {"type": "image", "nom": f"img{r.randint(1, 999)}.png", "largeur": r.choice([640, 1080, 1920]), "hauteur": r.choice([480, 720, 1080])}
    if t < 0.8:
        return {"type": "fichier", "nom": f"doc{r.randint(1, 999)}.pdf", "octets": r.randint(10_000, 5_000_000)}
    return {"type": "lien", "titre": r.choice(PHRASES), "url": f"https://exemple.fr/{r.randint(1, 9999)}", "miniature": r.random() < 0.5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--messages", type=int, default=300_000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    r = random.Random(a.seed)
    n_users, n_serv = 5000, 150
    span = (FIN - DEBUT).total_seconds()

    users = []
    for i in range(1, n_users + 1):
        cree = DEBUT + timedelta(seconds=r.random() * span * 0.5)
        users.append((i, f"{r.choice(PSEUDOS)}{i}", f"user{i}@exemple.fr", cree.isoformat()))
    activite = [1 / (rank ** 0.6) for rank in range(1, n_users + 1)]
    r.shuffle(activite)

    # serveurs : taille de communauté très inégale (log-normale), le propriétaire en est membre
    serveurs, membres, salons = [], [], []
    taille = {}
    sid_salons = {}
    next_salon = 1
    for s in range(1, n_serv + 1):
        n = int(min(2500, max(4, r.lognormvariate(3.3, 1.3))))
        taille[s] = n
        cree = DEBUT + timedelta(seconds=r.random() * span * 0.3)
        ids = set()
        while len(ids) < n:
            ids.add(r.choices(range(1, n_users + 1), weights=activite)[0])
        ids = list(ids)
        owner = ids[0]
        serveurs.append((s, f"{r.choice(NOMS_SERVEUR)} #{s}", owner, cree.isoformat()))
        for k, u in enumerate(ids):
            role = "proprietaire" if u == owner else ("moderateur" if r.random() < 0.03 else "membre")
            membres.append((u, s, role, (cree + timedelta(hours=k)).isoformat()))
        liste = []
        for nom in r.sample(SALONS_TEXTE, r.randint(2, 8)):
            salons.append((next_salon, s, nom, "texte", cree.isoformat()))
            liste.append(next_salon)
            next_salon += 1
        for nom in r.sample(SALONS_VOCAL, r.randint(1, 2)):
            salons.append((next_salon, s, nom, "vocal", cree.isoformat()))
            next_salon += 1
        sid_salons[s] = liste

    # messages : poids d'un salon = taille du serveur^1.3 / rang du salon dans le serveur
    pop, poids = [], []
    membres_par_serveur = {}
    for u, s, *_ in membres:
        membres_par_serveur.setdefault(s, []).append(u)
    for s, liste in sid_salons.items():
        for rang, sal in enumerate(liste, 1):
            pop.append((sal, s))
            poids.append(taille[s] ** 1.3 / rang)
    choix = r.choices(range(len(pop)), weights=poids, k=a.messages)
    creation_salon = {x[0]: datetime.fromisoformat(x[4]) for x in salons}
    horodatages = sorted(DEBUT + timedelta(seconds=r.random() * span) for _ in range(a.messages))
    messages = []
    seq = 0
    for ts, idx in zip(horodatages, choix):
        sal, s = pop[idx]
        if ts < creation_salon[sal]:
            ts = creation_salon[sal] + timedelta(seconds=r.randint(1, 3600))
        seq += 1
        auteur = r.choice(membres_par_serveur[s])
        pj = json.dumps(piece_jointe(r), ensure_ascii=False) if r.random() < 0.08 else ""
        modif = (ts + timedelta(minutes=r.randint(1, 30))).isoformat() if r.random() < 0.05 else ""
        messages.append((snowflake(ts, seq), sal, auteur, r.choice(PHRASES), ts.isoformat(), modif, pj))

    # amitiés : 70 % entre membres d'un même serveur
    amities = set()
    while len(amities) < 15000:
        u = r.choices(range(1, n_users + 1), weights=activite)[0]
        if r.random() < 0.7:
            s = r.choice([m[1] for m in r.sample(membres, 1)])
            v = r.choice(membres_par_serveur[s])
        else:
            v = r.randint(1, n_users)
        if u != v:
            amities.add((min(u, v), max(u, v)))
    amities = [(u, v, (DEBUT + timedelta(seconds=r.random() * span)).isoformat()) for u, v in sorted(amities)]

    def ecrire(nom, entete, lignes):
        with open(nom, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(entete)
            w.writerows(lignes)

    ecrire("utilisateurs.csv", ["id", "pseudo", "email", "cree_le"], users)
    ecrire("serveurs.csv", ["id", "nom", "proprietaire_id", "cree_le"], serveurs)
    ecrire("salons.csv", ["id", "serveur_id", "nom", "type", "cree_le"], salons)
    ecrire("membres.csv", ["utilisateur_id", "serveur_id", "role", "rejoint_le"], membres)
    ecrire("messages.csv", ["id", "salon_id", "auteur_id", "contenu", "envoye_le", "modifie_le", "pieces_jointes"], messages)
    ecrire("amities.csv", ["utilisateur_a", "utilisateur_b", "depuis"], amities)
    print(f"{len(users)} utilisateurs, {len(serveurs)} serveurs, {len(salons)} salons, {len(membres)} adhésions, "
          f"{len(messages)} messages, {len(amities)} amitiés.")


if __name__ == "__main__":
    main()
