# -*- coding: utf-8 -*-
"""Recherche des décideurs sur LinkedIn via recherche web ciblée.

On interroge un moteur de recherche avec `site:linkedin.com/in` + nom de
l'entreprise + intitulés de postes décideurs (RH, recrutement, direction).
Cela évite de scraper LinkedIn directement (compte non requis, pas de blocage).
"""
import re
import time
import unicodedata

from ddgs import DDGS

# Intitulés recherchés (une seule requête combinée pour aller vite).
ROLES_DEFAUT = [
    '"talent acquisition" OR "chargé de recrutement" OR "responsable recrutement"',
    'DRH OR RRH OR "responsable RH" OR "ressources humaines"',
    '"directeur général" OR CEO OR fondateur OR gérant',
]
# Filtre unique : décideurs RH + direction, regroupés dans un seul « OU ».
ROLE_FILTRE = ('"talent acquisition" OR "chargé de recrutement" OR '
               '"responsable recrutement" OR DRH OR RRH OR "responsable RH" OR '
               '"ressources humaines" OR "directeur général" OR CEO OR '
               'fondateur OR gérant OR président')

_RE_LINKEDIN_IN = re.compile(r"linkedin\.com/in/", re.I)


def _normaliser_texte(texte):
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()


def _mots_cles_entreprise(entreprise):
    """Mots significatifs du nom d'entreprise, pour vérifier la pertinence."""
    ignores = {"le", "la", "les", "de", "du", "des", "et", "groupe", "group",
               "france", "sas", "sarl", "sa", "sasu", "eurl"}
    mots = [m for m in _normaliser_texte(entreprise).split()
            if len(m) >= 3 and m not in ignores]
    return mots or _normaliser_texte(entreprise).split()


def _normaliser_url(url):
    """URL de profil canonique (retire paramètres et suffixe de langue /en, /fr...)."""
    url = url.split("?")[0].rstrip("/")
    url = re.sub(r"/(en|fr|es|de|it|nl|pt)$", "", url)
    return re.sub(r"^https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", url)


def _parser_titre(titre):
    """Découpe un titre de résultat "Prénom Nom - Poste - Entreprise | LinkedIn"."""
    # Couper tout ce qui suit "| LinkedIn" (les moteurs concatènent parfois
    # plusieurs résultats dans le même titre)
    titre = re.split(r"\s*\|\s*LinkedIn", titre)[0].strip()
    morceaux = re.split(r"\s+[-–—]\s+", titre)
    nom = morceaux[0].strip() if morceaux else titre
    poste = morceaux[1].strip() if len(morceaux) > 1 else ""
    entreprise = morceaux[2].strip() if len(morceaux) > 2 else ""
    return nom, poste, entreprise


def chercher_contacts(entreprise, roles=None, max_par_role=3, delai=0,
                      max_contacts=3):
    """Cherche les profils LinkedIn de décideurs pour une entreprise, en UNE
    seule requête (rapide). Retourne au plus `max_contacts` profils
    [{entreprise, nom, poste, entreprise_profil, url_linkedin, extrait}].

    `roles` : liste de filtres OR (fusionnés) ; par défaut RH + direction.
    `delai`, `max_par_role` : conservés pour compat, sans effet notable ici.
    """
    filtre = " OR ".join(roles) if roles else ROLE_FILTRE
    requete = f'site:linkedin.com/in "{entreprise}" ({filtre})'
    try:
        with DDGS() as ddgs:
            resultats = ddgs.text(requete, region="fr-fr", max_results=8)
    except Exception as e:
        print(f"    [LinkedIn] recherche impossible pour {entreprise} : {e}")
        return []

    contacts = []
    vus = set()
    mots_cles = _mots_cles_entreprise(entreprise)
    for r in resultats or []:
        url = r.get("href", "")
        if not _RE_LINKEDIN_IN.search(url):
            continue
        url_propre = _normaliser_url(url)
        if url_propre in vus:
            continue
        nom, poste, entreprise_profil = _parser_titre(r.get("title", ""))
        if not nom or _normaliser_texte(nom) in vus:
            continue
        # Pertinence : le nom de l'entreprise doit apparaître dans le titre
        # ou l'extrait du profil, sinon c'est un faux positif.
        texte_profil = _normaliser_texte(
            (r.get("title") or "") + " " + (r.get("body") or "")
        )
        if not any(mot in texte_profil for mot in mots_cles):
            continue
        vus.add(url_propre)
        vus.add(_normaliser_texte(nom))
        contacts.append({
            "entreprise": entreprise,
            "nom": nom,
            "poste": poste,
            "entreprise_profil": entreprise_profil,
            "url_linkedin": url_propre,
            "extrait": (r.get("body") or "")[:300],
        })
        if len(contacts) >= max_contacts:
            break
    return contacts
