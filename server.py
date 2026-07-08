# -*- coding: utf-8 -*-
"""Interface web de l'automatisation de prospection Skaelia.

Lancement :  python server.py   puis ouvrir http://localhost:5173
Accès protégé par comptes : demande d'accès -> validation par
gabriel.praud@skaelia.com -> choix du mot de passe -> connexion.
"""
import json
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from prospection import auth, mailer, pipeline

RACINE = Path(__file__).parent
FICHIER_CONFIG = RACINE / "config.json"

app = Flask(__name__)
app.secret_key = auth.cle_secrete()
app.permanent_session_lifetime = 60 * 60 * 24 * 30  # 30 jours

# État du job en cours (une seule recherche à la fois)
JOB = {"etat": "inactif", "logs": [], "resultats": None, "erreur": "", "titre": ""}
VERROU = threading.Lock()


def _config():
    try:
        return json.loads(FICHIER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _ecrire_config(config):
    FICHIER_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- accès

ROUTES_PUBLIQUES = ("/connexion", "/api/connexion", "/api/demande-acces",
                    "/valider/", "/definir-mdp/", "/api/definir-mdp", "/static/")


@app.before_request
def garde_acces():
    chemin = request.path
    if any(chemin == r or chemin.startswith(r) for r in ROUTES_PUBLIQUES):
        return None
    if session.get("email"):
        return None
    if chemin.startswith("/api/"):
        return jsonify({"erreur": "Non connecté"}), 401
    return redirect(url_for("page_connexion"))


@app.get("/connexion")
def page_connexion():
    if session.get("email"):
        return redirect("/")
    return render_template("connexion.html")


@app.post("/api/connexion")
def api_connexion():
    donnees = request.get_json(force=True)
    ok, erreur = auth.verifier_connexion(donnees.get("email"), donnees.get("mot_de_passe"))
    if not ok:
        return jsonify({"erreur": erreur}), 401
    session.permanent = True
    session["email"] = (donnees.get("email") or "").strip().lower()
    return jsonify({"ok": True})


@app.post("/api/demande-acces")
def api_demande_acces():
    donnees = request.get_json(force=True)
    email = (donnees.get("email") or "").strip().lower()
    nom = (donnees.get("nom") or "").strip()
    ok, message = auth.creer_demande(email, nom)
    if not ok:
        return jsonify({"erreur": message}), 400

    lien = request.host_url.rstrip("/") + "/valider/" + auth.jeton_validation(email)
    corps, sujet = mailer.email_validation_admin(email, nom, lien)
    envoye, erreur_envoi = mailer.envoyer(auth.ADMIN_EMAIL, sujet, corps)
    if envoye:
        return jsonify({"ok": True, "message":
                        f"Demande envoyée : {auth.ADMIN_EMAIL} doit maintenant valider votre accès."})
    # SMTP absent ou en panne : on affiche le lien de validation à transmettre
    print(f"[ACCÈS] Demande de {email} — lien de validation : {lien}")
    return jsonify({"ok": True, "sans_email": True,
                    "message": ("Demande enregistrée, mais l'envoi d'email n'est pas configuré. "
                                f"Transmettez ce lien de validation à {auth.ADMIN_EMAIL} :"),
                    "lien": lien})


@app.get("/valider/<jeton>")
def page_valider(jeton):
    email, erreur = auth.valider_demande(jeton)
    if not email:
        return render_template("message.html", titre="Validation impossible",
                               message=erreur, lien_mdp=""), 400
    lien_mdp = request.host_url.rstrip("/") + "/definir-mdp/" + auth.jeton_mot_de_passe(email)
    corps, sujet = mailer.email_definir_mdp(lien_mdp)
    envoye, _ = mailer.envoyer(email, sujet, corps)
    if envoye:
        return render_template("message.html", titre="Compte validé ✓",
                               message=(f"Le compte {email} est validé. Un email vient de lui être "
                                        "envoyé pour choisir son mot de passe."), lien_mdp="")
    print(f"[ACCÈS] Compte {email} validé — lien mot de passe : {lien_mdp}")
    return render_template("message.html", titre="Compte validé ✓",
                           message=(f"Le compte {email} est validé. L'envoi d'email n'étant pas "
                                    "configuré, transmettez-lui ce lien pour choisir son mot de passe :"),
                           lien_mdp=lien_mdp)


@app.get("/definir-mdp/<jeton>")
def page_definir_mdp(jeton):
    return render_template("definir_mdp.html", jeton=jeton)


@app.post("/api/definir-mdp")
def api_definir_mdp():
    donnees = request.get_json(force=True)
    email, erreur = auth.definir_mot_de_passe(donnees.get("jeton"), donnees.get("mot_de_passe"))
    if not email:
        return jsonify({"erreur": erreur}), 400
    session.permanent = True
    session["email"] = email
    return jsonify({"ok": True})


@app.post("/api/deconnexion")
def api_deconnexion():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/changer-mdp")
def api_changer_mdp():
    donnees = request.get_json(force=True)
    ok, erreur = auth.changer_mot_de_passe(
        session["email"], donnees.get("ancien"), donnees.get("nouveau"))
    if not ok:
        return jsonify({"erreur": erreur}), 400
    return jsonify({"ok": True})


@app.get("/api/moi")
def api_moi():
    infos = auth.infos_utilisateur(session["email"]) or {"email": session["email"], "nom": ""}
    return jsonify(infos)


# ---------------------------------------------------------------- pages

@app.get("/")
def accueil():
    return render_template("index.html")


# ---------------------------------------------------------------- réglages

@app.get("/api/reglages")
def lire_reglages():
    config = _config()
    cle = config.get("usebouncer_api_key", "")
    return jsonify({
        "usebouncer_configuree": bool(cle),
        "exclusions_cabinets": config.get("exclusions_cabinets", []),
        "smtp_configure": mailer.smtp_configure(),
    })


@app.post("/api/reglages")
def ecrire_reglages():
    donnees = request.get_json(force=True)
    config = _config()
    if donnees.get("usebouncer_api_key"):
        config["usebouncer_api_key"] = donnees["usebouncer_api_key"].strip()
    if "exclusions_cabinets" in donnees:
        config["exclusions_cabinets"] = [
            e.strip() for e in donnees["exclusions_cabinets"] if e.strip()]
    if "smtp" in donnees:
        smtp = donnees["smtp"] or {}
        existant = config.get("smtp") or {}
        config["smtp"] = {
            "hote": (smtp.get("hote") or "").strip(),
            "port": int(smtp.get("port") or 587),
            "utilisateur": (smtp.get("utilisateur") or "").strip(),
            "mot_de_passe": (smtp.get("mot_de_passe") or "").strip()
                            or existant.get("mot_de_passe", ""),
            "expediteur": (smtp.get("utilisateur") or "").strip(),
        }
    _ecrire_config(config)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- exécution

def _executer_en_fond(params):
    def log(message):
        JOB["logs"].append({"heure": datetime.now().strftime("%H:%M:%S"),
                            "texte": str(message)})
    try:
        JOB["resultats"] = pipeline.executer(params, log=log)
        JOB["etat"] = "termine"
    except Exception as e:
        JOB["erreur"] = str(e)
        JOB["etat"] = "erreur"
        log(f"Erreur : {e}")
        traceback.print_exc()


@app.post("/api/lancer")
def lancer():
    with VERROU:
        if JOB["etat"] == "en_cours":
            return jsonify({"erreur": "Une recherche est déjà en cours"}), 409
        donnees = request.get_json(force=True)
        poste = (donnees.get("poste") or "").strip()
        if not poste:
            return jsonify({"erreur": "Indiquez le poste recherché"}), 400

        config = _config()
        params = {
            "poste": poste,
            "lieu": (donnees.get("lieu") or "").strip(),
            "exclusions": config.get("exclusions_cabinets", []),
            "usebouncer_api_key": config.get("usebouncer_api_key", ""),
        }
        JOB.update({"etat": "en_cours", "logs": [], "resultats": None,
                    "erreur": "", "titre": poste + (f" — {params['lieu']}" if params["lieu"] else "")})
        threading.Thread(target=_executer_en_fond, args=(params,), daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/statut")
def statut():
    reponse = {"etat": JOB["etat"], "titre": JOB["titre"],
               "logs": JOB["logs"], "erreur": JOB["erreur"]}
    if JOB["etat"] == "termine" and JOB["resultats"]:
        r = JOB["resultats"]
        reponse["synthese"] = {
            "nb_offres": len(r["offres"]),
            "nb_entreprises": len(r["entreprises"]),
            "nb_contacts": len(r["contacts"]),
            "nb_nouvelles": r["nb_nouvelles"],
        }
    return jsonify(reponse)


@app.get("/api/resultats")
def resultats():
    if JOB["etat"] != "termine" or not JOB["resultats"]:
        return jsonify({"erreur": "Aucun résultat disponible"}), 404
    r = JOB["resultats"]
    return jsonify({
        "offres": r["offres"],
        "entreprises": r["entreprises"],
        "contacts": r["contacts"],
        "nb_nouvelles": r["nb_nouvelles"],
        "fichier": Path(r["fichier"]).name if r["fichier"] else "",
    })


@app.get("/api/telecharger")
def telecharger():
    if not (JOB["resultats"] and JOB["resultats"].get("fichier")):
        return jsonify({"erreur": "Aucun fichier disponible"}), 404
    chemin = Path(JOB["resultats"]["fichier"])
    if not chemin.exists():
        return jsonify({"erreur": "Fichier introuvable"}), 404
    return send_file(chemin, as_attachment=True, download_name=chemin.name)


if __name__ == "__main__":
    print("Interface disponible sur http://localhost:5173")
    app.run(host="127.0.0.1", port=5173, debug=False)
