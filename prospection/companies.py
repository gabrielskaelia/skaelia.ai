# -*- coding: utf-8 -*-
"""Consolidation des entreprises à partir des offres collectées.

Déduplique les entreprises et exclut les cabinets de recrutement / agences
d'intérim (concurrents, pas prospects).
"""
import re
import unicodedata


def _normaliser(nom):
    """Nom en minuscules, sans accents ni ponctuation, pour la déduplication."""
    nom = unicodedata.normalize("NFKD", nom)
    nom = "".join(c for c in nom if not unicodedata.combining(c))
    nom = re.sub(r"[^a-z0-9]+", " ", nom.lower()).strip()
    # Retirer les suffixes juridiques courants
    nom = re.sub(r"\b(sas|sarl|sa|sasu|eurl|groupe|france)\b", "", nom).strip()
    return nom


def est_client(nom, clients_norm):
    """True si l'entreprise `nom` fait partie de nos clients (missions Nicoka)."""
    cle = _normaliser(nom)
    if not cle:
        return False
    return any(cle == c or cle.startswith(c + " ") or c.startswith(cle + " ")
               for c in clients_norm if c)


def consolider_entreprises(offres, exclusions=None, clients=None):
    """Regroupe les offres par entreprise.

    Retourne une liste [{entreprise, nb_offres, postes, lieux, sources, urls,
    type}] triée par nombre d'offres décroissant. `exclusions` = noms à ignorer
    (cabinets de recrutement, agences d'intérim...). `clients` = noms de nos
    entreprises clientes (Nicoka) : elles sont marquées type="client", les
    autres type="prospect".
    """
    exclusions_norm = {_normaliser(e) for e in (exclusions or [])}
    clients_norm = {_normaliser(c) for c in (clients or [])}
    groupes = {}
    for offre in offres:
        nom = offre.get("entreprise", "").strip()
        if not nom:
            continue
        cle = _normaliser(nom)
        if not cle:
            continue
        # Exclusion : correspondance exacte ou le nom commence par un exclu
        if any(cle == ex or cle.startswith(ex + " ") for ex in exclusions_norm if ex):
            continue
        g = groupes.setdefault(cle, {
            "entreprise": nom,
            "nb_offres": 0,
            "postes": [],
            "lieux": [],
            "sources": set(),
            "urls": [],
            "type": "client" if est_client(nom, clients_norm) else "prospect",
        })
        g["nb_offres"] += 1
        if offre["titre"] not in g["postes"]:
            g["postes"].append(offre["titre"])
        if offre["lieu"] and offre["lieu"] not in g["lieux"]:
            g["lieux"].append(offre["lieu"])
        g["sources"].add(offre["source"])
        g["urls"].append(offre["url"])

    resultat = []
    for g in groupes.values():
        g["sources"] = ", ".join(sorted(g["sources"]))
        resultat.append(g)
    resultat.sort(key=lambda g: g["nb_offres"], reverse=True)
    return resultat
