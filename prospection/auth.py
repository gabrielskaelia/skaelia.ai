# -*- coding: utf-8 -*-
"""Comptes utilisateurs : demandes d'accès validées par l'administrateur,
mots de passe hachés, jetons signés pour les liens email."""
import json
import secrets
import threading
from datetime import datetime
from pathlib import Path

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

RACINE = Path(__file__).parent.parent
DOSSIER_DONNEES = RACINE / "data"
FICHIER_UTILISATEURS = DOSSIER_DONNEES / "utilisateurs.json"
FICHIER_SECRET = DOSSIER_DONNEES / "secret.txt"

ADMIN_EMAIL = "gabriel.praud@skaelia.com"

_VERROU = threading.Lock()


def cle_secrete():
    """Clé de session/signature persistante (générée au premier lancement)."""
    DOSSIER_DONNEES.mkdir(exist_ok=True)
    if not FICHIER_SECRET.exists():
        FICHIER_SECRET.write_text(secrets.token_hex(32), encoding="utf-8")
    return FICHIER_SECRET.read_text(encoding="utf-8").strip()


def _serialiseur(sel):
    return URLSafeTimedSerializer(cle_secrete(), salt=sel)


def _charger():
    try:
        return json.loads(FICHIER_UTILISATEURS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _sauver(utilisateurs):
    DOSSIER_DONNEES.mkdir(exist_ok=True)
    FICHIER_UTILISATEURS.write_text(
        json.dumps(utilisateurs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _normaliser_email(email):
    return (email or "").strip().lower()


# ------------------------------------------------------------------ demandes

def creer_demande(email, nom=""):
    """Enregistre une demande d'accès. Retourne (ok, message)."""
    email = _normaliser_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        return False, "Adresse email invalide."
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(email)
        if u and u.get("statut") == "actif":
            return False, "Ce compte existe déjà — connectez-vous."
        utilisateurs[email] = {
            "nom": (nom or "").strip(),
            "statut": "en_attente",
            "mdp": u.get("mdp") if u else None,
            "demande_le": datetime.now().isoformat(timespec="seconds"),
        }
        _sauver(utilisateurs)
    return True, "Demande enregistrée."


def jeton_validation(email):
    """Jeton signé envoyé à l'administrateur pour valider un compte."""
    return _serialiseur("validation-acces").dumps(_normaliser_email(email))


def valider_demande(jeton, max_age=7 * 24 * 3600):
    """Valide un compte depuis le lien email admin. Retourne (email|None, erreur)."""
    try:
        email = _serialiseur("validation-acces").loads(jeton, max_age=max_age)
    except SignatureExpired:
        return None, "Ce lien de validation a expiré (7 jours)."
    except BadSignature:
        return None, "Lien de validation invalide."
    with _VERROU:
        utilisateurs = _charger()
        if email not in utilisateurs:
            return None, "Aucune demande trouvée pour cette adresse."
        if utilisateurs[email]["statut"] != "actif":
            utilisateurs[email]["statut"] = "valide"
            utilisateurs[email]["valide_le"] = datetime.now().isoformat(timespec="seconds")
            _sauver(utilisateurs)
    return email, ""


def jeton_mot_de_passe(email):
    """Jeton signé permettant de (re)définir son mot de passe."""
    return _serialiseur("definir-mdp").dumps(_normaliser_email(email))


def definir_mot_de_passe(jeton, mot_de_passe, max_age=7 * 24 * 3600):
    """Définit le mot de passe depuis le lien email. Retourne (email|None, erreur)."""
    if len(mot_de_passe or "") < 8:
        return None, "Le mot de passe doit contenir au moins 8 caractères."
    try:
        email = _serialiseur("definir-mdp").loads(jeton, max_age=max_age)
    except SignatureExpired:
        return None, "Ce lien a expiré — refaites une demande d'accès."
    except BadSignature:
        return None, "Lien invalide."
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(email)
        if not u or u["statut"] not in ("valide", "actif"):
            return None, "Ce compte n'a pas encore été validé."
        u["mdp"] = generate_password_hash(mot_de_passe)
        u["statut"] = "actif"
        _sauver(utilisateurs)
    return email, ""


# ------------------------------------------------------------------ connexion

def verifier_connexion(email, mot_de_passe):
    """Retourne (ok, erreur)."""
    email = _normaliser_email(email)
    u = _charger().get(email)
    if not u or u.get("statut") != "actif" or not u.get("mdp"):
        return False, "Compte inconnu ou non activé."
    if not check_password_hash(u["mdp"], mot_de_passe or ""):
        return False, "Mot de passe incorrect."
    return True, ""


def changer_mot_de_passe(email, ancien, nouveau):
    """Change le mot de passe d'un utilisateur connecté. Retourne (ok, erreur)."""
    email = _normaliser_email(email)
    if len(nouveau or "") < 8:
        return False, "Le nouveau mot de passe doit contenir au moins 8 caractères."
    ok, erreur = verifier_connexion(email, ancien)
    if not ok:
        return False, "Mot de passe actuel incorrect."
    with _VERROU:
        utilisateurs = _charger()
        utilisateurs[email]["mdp"] = generate_password_hash(nouveau)
        _sauver(utilisateurs)
    return True, ""


def infos_utilisateur(email):
    u = _charger().get(_normaliser_email(email))
    if not u:
        return None
    return {"email": _normaliser_email(email), "nom": u.get("nom", ""), "statut": u.get("statut")}
