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


def envoyer(destinataire, sujet, corps_html):
    """Envoie un email HTML. Retourne (ok, erreur)."""
    c = _config_smtp()
    if not smtp_configure():
        return False, "SMTP non configuré"
    message = MIMEText(corps_html, "html", "utf-8")
    message["Subject"] = sujet
    message["From"] = c.get("expediteur") or c["utilisateur"]
    message["To"] = destinataire
    try:
        with smtplib.SMTP(c["hote"], int(c.get("port", 587)), timeout=20) as serveur:
            serveur.starttls()
            serveur.login(c["utilisateur"], c["mot_de_passe"])
            serveur.send_message(message)
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
