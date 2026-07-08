# -*- coding: utf-8 -*-
"""Recherche du domaine email d'une entreprise, génération des formats
d'adresses probables et vérification via l'API UseBouncer."""
import re
import time
import unicodedata
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests
from ddgs import DDGS

# Domaines qui ne sont jamais le site officiel d'une entreprise
DOMAINES_IGNORES = {
    "linkedin.com", "fr.linkedin.com", "indeed.com", "fr.indeed.com",
    "hellowork.com", "societe.com", "pappers.fr", "verif.com",
    "pagesjaunes.fr", "wikipedia.org", "fr.wikipedia.org", "facebook.com",
    "instagram.com", "youtube.com", "glassdoor.fr", "welcometothejungle.com",
    "kompass.com", "infogreffe.fr", "annuaire-entreprises.data.gouv.fr",
}

FORMATS_EMAIL = [
    "{prenom}.{nom}",
    "{p}{nom}",
    "{prenom}",
    "{p}.{nom}",
    "{prenom}{nom}",
    "{nom}.{prenom}",
]


def _sans_accents(texte):
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c))


def _chercher_domaine_une_fois(nom, delai):
    try:
        with DDGS() as ddgs:
            resultats = ddgs.text(f'"{nom}" site officiel', region="fr-fr", max_results=8)
    except Exception as e:
        print(f"    [Domaine] recherche impossible pour {nom} : {e}")
        return "", False
    finally:
        time.sleep(delai)

    mots = [m for m in re.split(r"[^a-z0-9]+", _sans_accents(nom).lower())
            if len(m) >= 4]
    candidats = []
    for r in resultats or []:
        url = r.get("href", "")
        domaine = urlparse(url).netloc.lower().removeprefix("www.")
        if not domaine or any(domaine == d or domaine.endswith("." + d) for d in DOMAINES_IGNORES):
            continue
        candidats.append(domaine)

    for domaine in candidats:
        if any(mot in domaine.replace("-", "") or mot in domaine for mot in mots):
            return domaine, True  # correspondance forte nom <-> domaine
    return (candidats[0] if candidats else ""), False


def trouver_domaine(entreprise, delai=3.0):
    """Cherche le site officiel de l'entreprise et retourne son domaine.

    On privilégie un domaine qui contient un mot du nom de l'entreprise
    (ex. "trecobat" -> trecobat-groupe.fr). Les sites d'offres d'emploi
    ajoutent souvent la ville au nom ("MBWAY Angers") : si la recherche du nom
    complet ne donne rien de convaincant, on réessaie sans le dernier mot.
    """
    variantes = [entreprise.strip()]
    mots = entreprise.strip().split()
    if len(mots) >= 2:
        variantes.append(" ".join(mots[:-1]))

    premier_trouve = ""
    for variante in variantes:
        domaine, fort = _chercher_domaine_une_fois(variante, delai)
        if fort:
            return domaine
        if domaine and not premier_trouve:
            premier_trouve = domaine
    return premier_trouve


def generer_emails(nom_complet, domaine):
    """Génère les adresses probables à partir de "Prénom Nom" et du domaine."""
    if not domaine:
        return []
    mots = _sans_accents(nom_complet).lower().split()
    mots = [re.sub(r"[^a-z\-]", "", m) for m in mots if re.sub(r"[^a-z\-]", "", m)]
    if len(mots) < 2:
        return []
    prenom, nom = mots[0], mots[-1]
    emails = []
    for fmt in FORMATS_EMAIL:
        adresse = fmt.format(prenom=prenom, nom=nom, p=prenom[0]) + "@" + domaine
        if adresse not in emails:
            emails.append(adresse)
    return emails


def verifier_email(email, api_key, timeout=30):
    """Vérifie une adresse via UseBouncer. Retourne (statut, raison).

    Statuts UseBouncer : deliverable / risky / undeliverable / unknown.
    """
    try:
        r = curl_requests.get(
            "https://api.usebouncer.com/v1.1/email/verify",
            params={"email": email},
            headers={"x-api-key": api_key},
            timeout=timeout,
        )
        if r.status_code == 402:
            return "credits épuisés", ""
        if r.status_code == 401:
            return "clé API invalide", ""
        r.raise_for_status()
        data = r.json()
        return data.get("status", "unknown"), data.get("reason", "")
    except Exception as e:
        return "erreur", str(e)


def meilleur_email(nom_complet, domaine, api_key=None, max_verifications=4):
    """Retourne (email, statut) : la première adresse 'deliverable', sinon la
    plus probable marquée 'non vérifié' (ou 'risky' si rien de mieux)."""
    if not domaine:
        return "", "site de l'entreprise introuvable"
    candidats = generer_emails(nom_complet, domaine)
    if not candidats:
        return "", "nom du contact incomplet"
    if not api_key:
        return candidats[0], "non vérifié"

    meilleur_risky = ""
    for email in candidats[:max_verifications]:
        statut, _ = verifier_email(email, api_key)
        if statut == "deliverable":
            return email, "deliverable"
        if statut == "risky" and not meilleur_risky:
            meilleur_risky = email
        if statut in ("credits épuisés", "clé API invalide"):
            return candidats[0], statut
        time.sleep(0.5)
    if meilleur_risky:
        return meilleur_risky, "risky"
    return candidats[0], "non vérifié (aucun format confirmé)"
