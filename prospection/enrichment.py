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
