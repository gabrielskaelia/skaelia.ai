# -*- coding: utf-8 -*-
"""Enrichissement des contacts via FullEnrich : trouve le vrai email
professionnel (vérifié) et le numéro de téléphone à partir de l'URL LinkedIn
(ou nom + entreprise).

L'API FullEnrich est asynchrone (« waterfall » sur plusieurs sources) :
  1. POST /contact/enrich/bulk  -> renvoie un enrichment_id
  2. GET  /contact/enrich/bulk/{id} (polling) -> status FINISHED + résultats

La clé API est dans config.json -> "fullenrich_api_key".
"""
import json
import re
import time
from pathlib import Path

from curl_cffi import requests

RACINE = Path(__file__).parent.parent
FICHIER_CONFIG = RACINE / "config.json"
BASE = "https://app.fullenrich.com/api/v2"

# Traduction des statuts email FullEnrich vers nos statuts internes
_STATUTS = {
    "DELIVERABLE": "deliverable",
    "HIGH_PROBABILITY": "risky",
    "CATCH_ALL": "risky",
    "INVALID": "undeliverable",
    "INVALID_DOMAIN": "undeliverable",
}


def _cle_api():
    try:
        c = json.loads(FICHIER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    return (c.get("fullenrich_api_key") or "").strip()


def est_configure():
    return bool(_cle_api())


def _prenom_nom(nom_complet):
    parts = (nom_complet or "").strip().split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return (nom_complet or "").strip(), ""


def enrichir_lot(contacts, timeout=240, log=lambda m: None):
    """Enrichit une liste de contacts.

    `contacts` : liste de dicts {nom, entreprise, url_linkedin, domaine}.
    Retourne une liste (même ordre) de dicts {email, statut_email, telephone}
    — chaîne vide si non trouvé. Liste vide si non configuré ou erreur.
    """
    cle = _cle_api()
    if not cle or not contacts:
        return []

    data = []
    for c in contacts:
        prenom, nom = _prenom_nom(c.get("nom"))
        item = {
            "first_name": prenom,
            "last_name": nom,
            "enrich_fields": ["contact.work_emails", "contact.phones"],
        }
        if c.get("url_linkedin"):
            item["linkedin_url"] = c["url_linkedin"].split("?")[0]
        if c.get("entreprise"):
            item["company_name"] = c["entreprise"]
        if c.get("domaine"):
            item["domain"] = c["domaine"]
        data.append(item)

    entetes = {"Authorization": "Bearer " + cle, "Content-Type": "application/json"}
    try:
        rep = requests.post(BASE + "/contact/enrich/bulk",
                            json={"name": "Skaelia prospection", "data": data},
                            headers=entetes, timeout=30)
        if rep.status_code == 401:
            log("FullEnrich : clé API invalide")
            return []
        rep.raise_for_status()
        eid = rep.json().get("enrichment_id")
    except Exception as e:
        log(f"FullEnrich POST erreur : {e}")
        return []
    if not eid:
        return []

    debut = time.time()
    while time.time() - debut < timeout:
        time.sleep(6)
        try:
            r = requests.get(f"{BASE}/contact/enrich/bulk/{eid}", headers=entetes, timeout=30)
            r.raise_for_status()
            d = r.json()
        except Exception:
            continue
        statut = d.get("status")
        if statut == "CREDITS_INSUFFICIENT":
            log("FullEnrich : crédits insuffisants")
            return []
        if statut in ("FINISHED", "CANCELED", "RATE_LIMIT", "UNKNOWN"):
            return _extraire(d.get("data", []), len(contacts))
    log("FullEnrich : délai dépassé")
    return []


def _extraire(lignes, n):
    """Transforme la réponse FullEnrich en liste alignée sur l'ordre d'entrée."""
    resultats = []
    for item in lignes:
        ci = item.get("contact_info") or {}
        email_obj = ci.get("most_probable_work_email") or {}
        email = email_obj.get("email", "") or ""
        statut = _STATUTS.get(email_obj.get("status", ""), "")
        phone = (ci.get("most_probable_phone") or {}).get("number", "") or ""
        resultats.append({"email": email, "statut_email": statut, "telephone": phone})
    # Sécurité : aligner sur le nombre de contacts d'entrée
    while len(resultats) < n:
        resultats.append({"email": "", "statut_email": "", "telephone": ""})
    return resultats[:n]


# --- Recherche de décideurs (FullEnrich People Search) -----------------------
# La recherche coûte ~0,25 crédit par personne renvoyée (l'enrichissement
# email/téléphone se fait séparément, à la demande). Utilisée uniquement quand
# l'option « recherche améliorée » est cochée, en repli du gratuit (DuckDuckGo).

TITRES_DECIDEURS_DEFAUT = [
    "responsable recrutement", "chargé de recrutement", "talent acquisition",
    "DRH", "RRH", "responsable ressources humaines",
    "directeur général", "CEO", "gérant", "fondateur", "président",
]


def _titres_depuis_roles(roles):
    """Transforme des filtres façon moteur de recherche
    (['"a" OR "b"', 'c OR d']) en liste d'intitulés simples pour FullEnrich."""
    titres = []
    for bloc in roles or []:
        for t in re.split(r"\s+OR\s+", bloc):
            t = t.strip().strip('"').strip()
            if t and t.lower() not in [x.lower() for x in titres]:
                titres.append(t)
    return titres


def rechercher_decideurs(entreprise, roles=None, max_contacts=2, log=lambda m: None):
    """Trouve des décideurs d'une entreprise via FullEnrich People Search.
    Retourne [{entreprise, nom, poste, entreprise_profil, url_linkedin, extrait}]
    (même format que linkedin_contacts.chercher_contacts).
    Coûte ~0,25 crédit par personne renvoyée. Liste vide si non configuré/erreur."""
    cle = _cle_api()
    entreprise = (entreprise or "").strip()
    if not cle or not entreprise:
        return []
    titres = _titres_depuis_roles(roles) or TITRES_DECIDEURS_DEFAUT
    limite = max(1, int(max_contacts))
    corps = {
        "limit": limite,
        "offset": 0,
        # OU sur les intitulés, ET avec l'entreprise (logique FullEnrich).
        "current_company_names": [{"value": entreprise, "exact_match": False}],
        "current_position_titles": [{"value": t, "exact_match": False} for t in titres],
    }
    entetes = {"Authorization": "Bearer " + cle, "Content-Type": "application/json"}
    try:
        rep = requests.post(BASE + "/people/search", json=corps, headers=entetes, timeout=30)
        if rep.status_code == 401:
            log("FullEnrich Search : clé API invalide")
            return []
        rep.raise_for_status()
        data = rep.json()
    except Exception as e:
        log(f"FullEnrich Search erreur ({entreprise}) : {e}")
        return []

    contacts = []
    for pers in (data.get("people") or [])[:limite]:
        emploi = (pers.get("employment") or {}).get("current") or {}
        reseau = (pers.get("social_profiles") or {}).get("professional_network") or {}
        nom = (pers.get("full_name")
               or " ".join(x for x in [pers.get("first_name"), pers.get("last_name")] if x))
        contacts.append({
            "entreprise": entreprise,
            "nom": (nom or "").strip(),
            "poste": (emploi.get("title") or "").strip(),
            "entreprise_profil": ((emploi.get("company") or {}).get("name") or "").strip(),
            "url_linkedin": (reseau.get("url") or "").split("?")[0],
            "extrait": "",
        })
    return [c for c in contacts if c["nom"]]
