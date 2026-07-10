# -*- coding: utf-8 -*-
"""Carnet de contacts sauvegardés, par utilisateur.

Stocké dans data/mes_contacts.json :
    { "<email_utilisateur>": [ {contact}, ... ] }

Chaque contact conserve : nom, poste, entreprise, url_linkedin, email,
statut_email, telephone, ajoute_le. La clé d'unicité est l'URL LinkedIn
(sinon "nom@entreprise").
"""
import json
import threading
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).parent.parent
DOSSIER_DONNEES = RACINE / "data"
FICHIER = DOSSIER_DONNEES / "mes_contacts.json"
_VERROU = threading.Lock()


def _charger():
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _sauver(donnees):
    DOSSIER_DONNEES.mkdir(exist_ok=True)
    FICHIER.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def cle_contact(contact):
    url = (contact.get("url_linkedin") or "").split("?")[0].rstrip("/").lower()
    if url:
        return url
    return f"{(contact.get('nom') or '').strip().lower()}@{(contact.get('entreprise') or '').strip().lower()}"


def _nettoyer(contact):
    # Offres de l'entreprise associées au contact (pour retrouver la demande)
    offres = []
    for o in (contact.get("offres") or [])[:6]:
        titre = (o.get("titre") or "").strip()
        url = (o.get("url") or "").strip()
        if titre or url:
            offres.append({"titre": titre, "url": url})
    return {
        "nom": (contact.get("nom") or "").strip(),
        "poste": (contact.get("poste") or "").strip(),
        "entreprise": (contact.get("entreprise") or "").strip(),
        "url_linkedin": (contact.get("url_linkedin") or "").strip(),
        "email": (contact.get("email") or "").strip(),
        "statut_email": (contact.get("statut_email") or "").strip(),
        "telephone": (contact.get("telephone") or "").strip(),
        "offres": offres,
        "nicoka": contact.get("nicoka") or {},
        "enrichissement": (contact.get("enrichissement") or "").strip(),
    }


def lister(email_utilisateur):
    return _charger().get(email_utilisateur, [])


def ajouter(email_utilisateur, contacts):
    """Ajoute un ou plusieurs contacts. Retourne le nombre réellement ajoutés
    (les doublons sont ignorés) et la liste à jour."""
    with _VERROU:
        donnees = _charger()
        actuels = donnees.setdefault(email_utilisateur, [])
        cles_existantes = {cle_contact(c) for c in actuels}
        ajoutes = 0
        for brut in contacts:
            contact = _nettoyer(brut)
            cle = cle_contact(contact)
            if not contact["nom"] or cle in cles_existantes:
                continue
            contact["ajoute_le"] = datetime.now().isoformat(timespec="seconds")
            actuels.append(contact)
            cles_existantes.add(cle)
            ajoutes += 1
        _sauver(donnees)
        return ajoutes, actuels


def supprimer(email_utilisateur, cles):
    """Supprime les contacts dont la clé est dans `cles`. Retourne la liste à jour."""
    cibles = set(cles)
    with _VERROU:
        donnees = _charger()
        actuels = donnees.get(email_utilisateur, [])
        restants = [c for c in actuels if cle_contact(c) not in cibles]
        donnees[email_utilisateur] = restants
        _sauver(donnees)
        return restants


def maj_nicoka_tous(email_utilisateur, calcul):
    """Recalcule le statut Nicoka de tous les contacts de l'utilisateur.
    `calcul(contact)` renvoie le dict nicoka. Retourne la liste à jour."""
    with _VERROU:
        donnees = _charger()
        for c in donnees.get(email_utilisateur, []):
            c["nicoka"] = calcul(c)
        _sauver(donnees)
        return donnees.get(email_utilisateur, [])


def mettre_a_jour(email_utilisateur, cle, champs):
    """Met à jour certains champs d'un contact (ex. téléphone). Retourne le contact ou None."""
    with _VERROU:
        donnees = _charger()
        for c in donnees.get(email_utilisateur, []):
            if cle_contact(c) == cle:
                for k in ("telephone", "email", "poste", "statut_email",
                          "enrichissement", "email_recherche", "tel_recherche"):
                    if k in champs:
                        c[k] = (champs[k] or "").strip()
                _sauver(donnees)
                return c
    return None
