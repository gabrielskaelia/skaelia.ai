# -*- coding: utf-8 -*-
"""Envoi des emails de validation et de définition de mot de passe.

La configuration SMTP se fait dans config.json :
    "smtp": {
        "hote": "smtp.gmail.com",
        "port": 587,
        "utilisateur": "gabriel.praud@skaelia.com",
        "mot_de_passe": "mot de passe d'application",
        "expediteur": "gabriel.praud@skaelia.com"
    }

Si le SMTP n'est pas configuré ou échoue, l'appel retourne (False, lien) et
l'interface affiche le lien à transmettre manuellement — l'outil reste
utilisable sans configuration email.
"""
import json
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

RACINE = Path(__file__).parent.parent
FICHIER_CONFIG = RACINE / "config.json"


def _config_smtp():
    try:
        config = json.loads(FICHIER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return config.get("smtp") or {}


def smtp_configure():
    c = _config_smtp()
    return bool(c.get("hote") and c.get("utilisateur") and c.get("mot_de_passe"))


def _envoyer_via(conf, destinataire, sujet, corps, type_mime="html"):
    """Envoie un email via la configuration SMTP donnée. Retourne (ok, erreur)."""
    if not (conf.get("hote") and conf.get("utilisateur") and conf.get("mot_de_passe")):
        return False, "SMTP non configuré"
    message = MIMEText(corps, type_mime, "utf-8")
    message["Subject"] = sujet
    message["From"] = conf.get("expediteur") or conf["utilisateur"]
    message["To"] = destinataire
    try:
        with smtplib.SMTP(conf["hote"], int(conf.get("port", 587)), timeout=20) as serveur:
            serveur.starttls()
            serveur.login(conf["utilisateur"], conf["mot_de_passe"])
            serveur.send_message(message)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, ("Identifiants refusés par le serveur d'envoi. Pour Gmail, "
                       "utilisez un « mot de passe d'application » "
                       "(myaccount.google.com/apppasswords).")
    except Exception as e:
        return False, str(e)


def envoyer(destinataire, sujet, corps_html):
    """Envoie un email HTML via le SMTP global (emails de compte). Retourne (ok, erreur)."""
    return _envoyer_via(_config_smtp(), destinataire, sujet, corps_html, "html")


def envoyer_pour(conf_perso, destinataire, sujet, corps_texte):
    """Envoie un email TEXTE via la connexion Gmail/SMTP d'un utilisateur."""
    return _envoyer_via(conf_perso or {}, destinataire, sujet, corps_texte, "plain")


# --------------------------------------------------- envoi via l'API Gmail

def _config_google():
    try:
        config = json.loads(FICHIER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return config.get("google") or {}


def envoyer_gmail(conf_oauth, destinataire, sujet, corps_texte):
    """Envoie un email TEXTE via l'API Gmail (compte relié par OAuth).
    `conf_oauth` = {adresse, refresh_token}. Retourne (ok, erreur)."""
    import base64
    from curl_cffi import requests as crequests

    google = _config_google()
    if not (google.get("client_id") and google.get("client_secret")):
        return False, "Connexion Google non configurée sur le serveur."
    if not conf_oauth.get("refresh_token"):
        return False, "Compte Gmail non relié."
    try:
        rep = crequests.post("https://oauth2.googleapis.com/token", data={
            "client_id": google["client_id"],
            "client_secret": google["client_secret"],
            "refresh_token": conf_oauth["refresh_token"],
            "grant_type": "refresh_token",
        }, timeout=20)
        if rep.status_code != 200:
            return False, ("Autorisation Gmail expirée ou révoquée — recliquez sur "
                           "« Connecter son Gmail » dans les Réglages.")
        jeton = rep.json()["access_token"]

        message = MIMEText(corps_texte, "plain", "utf-8")
        message["Subject"] = sujet
        message["From"] = conf_oauth.get("adresse", "")
        message["To"] = destinataire
        brut = base64.urlsafe_b64encode(message.as_bytes()).decode()

        envoi = crequests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": "Bearer " + jeton,
                     "Content-Type": "application/json"},
            json={"raw": brut}, timeout=20)
        if envoi.status_code >= 300:
            return False, f"Gmail a refusé l'envoi ({envoi.status_code})."
        return True, ""
    except Exception as e:
        return False, str(e)


def _gabarit(titre, corps, lien, libelle_bouton):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                background:#f4f4f2;padding:32px;border-radius:12px;color:#2a2a2a;">
      <p style="margin:0 0 24px 0;">
        <span style="font-size:20px;font-weight:800;letter-spacing:-0.02em;">Skaelia</span>
        <span style="background:#2263FF;color:#ffffff;font-size:11px;font-weight:800;
              padding:3px 7px;border-radius:6px;">AI</span>
      </p>
      <h2 style="margin-top:0;">{titre}</h2>
      <p style="line-height:1.6;">{corps}</p>
      <p style="margin:28px 0;">
        <a href="{lien}" style="background:#2263FF;color:#ffffff;text-decoration:none;
           padding:12px 24px;border-radius:8px;font-weight:bold;">{libelle_bouton}</a>
      </p>
      <p style="font-size:13px;color:#777;">Si le bouton ne fonctionne pas, copiez ce lien :<br>{lien}</p>
      <p style="font-size:13px;color:#777;">Skaelia AI — outil de prospection</p>
    </div>"""


def email_validation_admin(email_demandeur, nom, lien_validation):
    sujet = f"Demande d'accès à l'outil de prospection — {email_demandeur}"
    corps = (f"<strong>{nom or email_demandeur}</strong> ({email_demandeur}) demande "
             f"l'accès à l'outil de prospection Skaelia.<br><br>"
             f"Cliquez pour valider ce compte. La personne recevra ensuite un lien "
             f"pour choisir son mot de passe.")
    return _gabarit("Nouvelle demande d'accès", corps, lien_validation, "Valider ce compte"), sujet


def email_definir_mdp(lien_mdp):
    sujet = "Votre accès à l'outil de prospection Skaelia est validé"
    corps = ("Votre demande d'accès a été validée.<br><br>"
             "Cliquez ci-dessous pour choisir votre mot de passe et accéder à l'outil.")
    return _gabarit("Accès validé ✓", corps, lien_mdp, "Choisir mon mot de passe"), sujet
