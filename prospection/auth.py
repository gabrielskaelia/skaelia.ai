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

def creer_demande(email, nom="", auth="mot_de_passe"):
    """Enregistre une demande d'accès. Retourne (ok, message).
    `auth` = "mot_de_passe" (choix d'un mot de passe après validation) ou
    "google" (connexion Google, aucun mot de passe à définir)."""
    email = _normaliser_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        return False, "Adresse email invalide."
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(email)
        if u and u.get("statut") == "actif":
            return False, "Ce compte existe déjà — connectez-vous."
        utilisateurs[email] = {
            "nom": (nom or "").strip() or (u.get("nom") if u else ""),
            "statut": "en_attente",
            "auth": auth,
            "mdp": u.get("mdp") if u else None,
            "demande_le": datetime.now().isoformat(timespec="seconds"),
        }
        _sauver(utilisateurs)
    return True, "Demande enregistrée."


def statut_compte(email):
    """Retourne (statut, auth) du compte, ou (None, None) s'il n'existe pas."""
    u = _charger().get(_normaliser_email(email))
    if not u:
        return None, None
    return u.get("statut"), u.get("auth", "mot_de_passe")


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
        u = utilisateurs[email]
        if u["statut"] != "actif":
            # Comptes Google : rien à définir, on active directement.
            # Comptes mot de passe : l'utilisateur devra choisir son mot de passe.
            u["statut"] = "actif" if u.get("auth") == "google" else "valide"
            u["valide_le"] = datetime.now().isoformat(timespec="seconds")
            _sauver(utilisateurs)
    return email, ""


def valider_connexion_google(email):
    """Autorise une connexion Google. Retourne (ok, statut) :
    - (True, 'actif') si le compte est validé et peut se connecter,
    - (False, 'en_attente'|'valide') si en attente de validation admin,
    - (False, None) si aucun compte (le serveur créera alors une demande)."""
    statut, auth = statut_compte(email)
    if statut == "actif":
        return True, "actif"
    return False, statut


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


# ------------------------------------------------------- suivi & administration

def enregistrer_connexion(email):
    """Comptabilise une connexion réussie (nombre par jour + dernière date)."""
    email = _normaliser_email(email)
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(email)
        if not u:
            return
        jour = datetime.now().strftime("%Y-%m-%d")
        cnx = u.setdefault("connexions", {})
        cnx[jour] = cnx.get(jour, 0) + 1
        u["derniere_connexion"] = datetime.now().isoformat(timespec="seconds")
        _sauver(utilisateurs)


def lister_utilisateurs():
    """Liste complète des comptes (pour l'espace d'administration)."""
    comptes = []
    for email, u in sorted(_charger().items()):
        comptes.append({
            "email": email,
            "nom": u.get("nom", ""),
            "statut": u.get("statut", ""),
            "auth": u.get("auth", "mot_de_passe"),
            "demande_le": u.get("demande_le", ""),
            "valide_le": u.get("valide_le", ""),
            "derniere_connexion": u.get("derniere_connexion", ""),
            "connexions": u.get("connexions", {}),
        })
    return comptes


def admin_changer_mdp(email, nouveau):
    """L'administrateur définit directement le mot de passe d'un compte."""
    if len(nouveau or "") < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(_normaliser_email(email))
        if not u:
            return False, "Compte introuvable."
        u["mdp"] = generate_password_hash(nouveau)
        u["auth"] = "mot_de_passe"
        if u.get("statut") in ("valide", "en_attente"):
            u["statut"] = "actif"
        _sauver(utilisateurs)
    return True, ""


def supprimer_utilisateur(email):
    """Supprime un compte (le compte administrateur est protégé)."""
    email = _normaliser_email(email)
    if email == ADMIN_EMAIL:
        return False, "Impossible de supprimer le compte administrateur."
    with _VERROU:
        utilisateurs = _charger()
        if email not in utilisateurs:
            return False, "Compte introuvable."
        del utilisateurs[email]
        _sauver(utilisateurs)
    return True, ""


# ------------------------------------------------------- connexion Gmail/SMTP

def lire_smtp_perso(email):
    """Réglages d'envoi d'emails propres à CE compte (ou {})."""
    u = _charger().get(_normaliser_email(email))
    return (u or {}).get("smtp") or {}


def ecrire_smtp_perso(email, conf):
    """Enregistre la connexion Gmail/SMTP du compte. `conf` peut être {} pour
    débrancher. Le mot de passe vide conserve l'existant."""
    email = _normaliser_email(email)
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(email)
        if not u:
            return False
        if not conf:
            u.pop("smtp", None)
        else:
            existant = u.get("smtp") or {}
            u["smtp"] = {
                "hote": (conf.get("hote") or "smtp.gmail.com").strip(),
                "port": int(conf.get("port") or 587),
                "utilisateur": (conf.get("utilisateur") or "").strip(),
                "mot_de_passe": (conf.get("mot_de_passe") or "").strip()
                                or existant.get("mot_de_passe", ""),
            }
        _sauver(utilisateurs)
    return True


def lire_gmail_oauth(email):
    """Connexion Gmail (OAuth) du compte : {adresse, refresh_token} ou {}."""
    u = _charger().get(_normaliser_email(email))
    return (u or {}).get("gmail_oauth") or {}


def ecrire_gmail_oauth(email, conf):
    """Enregistre (ou retire si `conf` est vide) la connexion Gmail OAuth."""
    email = _normaliser_email(email)
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(email)
        if not u:
            return False
        if not conf:
            u.pop("gmail_oauth", None)
        else:
            u["gmail_oauth"] = {
                "adresse": (conf.get("adresse") or "").strip().lower(),
                "refresh_token": conf.get("refresh_token") or "",
                "relie_le": datetime.now().isoformat(timespec="seconds"),
            }
        _sauver(utilisateurs)
    return True


def onboarding_a_faire(email):
    """True si le compte n'a pas encore vu l'assistant de bienvenue
    (connexion Gmail + LinkedIn à la première connexion)."""
    u = _charger().get(_normaliser_email(email))
    return bool(u) and not u.get("onboarding_vu")


def marquer_onboarding_vu(email):
    """L'assistant de bienvenue a été complété ou passé : ne plus l'afficher."""
    with _VERROU:
        utilisateurs = _charger()
        u = utilisateurs.get(_normaliser_email(email))
        if u:
            u["onboarding_vu"] = True
            _sauver(utilisateurs)


def infos_utilisateur(email):
    u = _charger().get(_normaliser_email(email))
    if not u:
        return None
    return {"email": _normaliser_email(email), "nom": u.get("nom", ""), "statut": u.get("statut")}
