# -*- coding: utf-8 -*-
"""Orchestration du pipeline de prospection, pilotable par le CLI ou l'interface web.

Paramètres acceptés par `executer()` (dict `params`) :
    poste (str)                  — obligatoire
    lieu (str)                   — ville / département / vide = toute la France
    sources (list)               — ["hellowork", "indeed"]
    pages (int)                  — pages collectées par source
    anciennete_jours (int)       — âge max des offres Indeed (0 = sans limite)
    rayon_km (int)               — rayon de recherche Indeed autour du lieu
    contrats (list)              — ["CDI", "CDD", "Intérim", "Alternance", "Stage", "Indépendant"]
                                   (vide = tous)
    garder_contrat_inconnu (bool)— garder les offres sans type de contrat détecté
    teletravail_uniquement (bool)
    chercher_contacts (bool)
    max_entreprises (int)        — nb d'entreprises pour lesquelles chercher des contacts
    contacts_max_par_role (int)
    roles_cibles (list)          — requêtes de rôles (syntaxe moteur de recherche)
    exclusions (list)            — cabinets / agences à exclure
    verifier_emails (bool)
    usebouncer_api_key (str)
"""
import json
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from . import companies, emails, export_excel, jobs_hellowork, jobs_indeed, linkedin_contacts

RACINE = Path(__file__).parent.parent
DOSSIER_DONNEES = RACINE / "data"
DOSSIER_RESULTATS = RACINE / "resultats"
_VERROU_HISTORIQUE = threading.Lock()

CONTRATS_CONNUS = ["CDI", "CDD", "Intérim", "Alternance", "Stage", "Indépendant"]

DEFAUTS = {
    "lieu": "",
    "sources": ["hellowork", "indeed"],
    "pages": 2,
    "anciennete_jours": 14,
    "rayon_km": 25,
    "contrats": [],
    "garder_contrat_inconnu": True,
    "teletravail_uniquement": False,
    "chercher_contacts": True,
    "max_entreprises": 15,
    "contacts_max_par_role": 2,
    "roles_cibles": None,
    "exclusions": [],
    "verifier_emails": True,
    "usebouncer_api_key": "",
}


def _norm(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return texte.lower()


def _contrat_de(offre):
    """Type(s) de contrat normalisé(s) détecté(s) dans une offre."""
    texte = _norm(offre.get("contrat", "") + " " + offre.get("titre", ""))
    trouves = []
    correspondances = {
        "CDI": ["cdi"],
        "CDD": ["cdd"],
        "Intérim": ["interim", "travail temporaire"],
        "Alternance": ["alternance", "apprentissage", "contrat pro"],
        "Stage": ["stage"],
        "Indépendant": ["independant", "freelance", "franchise"],
    }
    for nom, mots in correspondances.items():
        if any(m in texte for m in mots):
            trouves.append(nom)
    return trouves


def _filtrer_contrats(offres, contrats, garder_inconnu=True):
    if not contrats:
        return offres
    voulus = set(contrats)
    gardees = []
    for o in offres:
        types = _contrat_de(o)
        if not types:
            if garder_inconnu:
                gardees.append(o)
        elif voulus & set(types):
            gardees.append(o)
    return gardees


def _filtrer_teletravail(offres):
    gardees = []
    for o in offres:
        texte = _norm(o.get("titre", "") + " " + o.get("lieu", "") + " " + o.get("contrat", ""))
        if "teletravail" in texte or "remote" in texte or "home office" in texte:
            gardees.append(o)
    return gardees


def _signature_recherche(poste, lieu):
    return re.sub(r"[^a-z0-9]+", "-", _norm(f"{poste} {lieu}")).strip("-")


def _marquer_nouveautes(offres, signature):
    """Marque 'Oui' les offres jamais vues pour cette recherche, et met à jour
    l'historique (data/historique.json)."""
    DOSSIER_DONNEES.mkdir(exist_ok=True)
    chemin = DOSSIER_DONNEES / "historique.json"
    with _VERROU_HISTORIQUE:
        historique = {}
        if chemin.exists():
            try:
                historique = json.loads(chemin.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                historique = {}
        vues = historique.setdefault(signature, {})
        premiere_fois = not vues
        maintenant = datetime.now().isoformat(timespec="seconds")
        nb_nouvelles = 0
        for o in offres:
            url = o.get("url", "")
            if url and url not in vues:
                # Au tout premier passage, tout serait "nouveau" : on n'affiche
                # le badge qu'à partir de la deuxième exécution.
                o["nouveau"] = "" if premiere_fois else "Oui"
                if not premiere_fois:
                    nb_nouvelles += 1
                vues[url] = maintenant
            else:
                o["nouveau"] = ""
        chemin.write_text(json.dumps(historique, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if premiere_fois else nb_nouvelles


def executer(params, log=print):
    """Exécute le pipeline complet et retourne
    {offres, entreprises, contacts, fichier, nb_nouvelles}."""
    p = {**DEFAUTS, **{k: v for k, v in params.items() if v is not None}}
    poste = (p.get("poste") or "").strip()
    if not poste:
        raise ValueError("Le poste recherché est obligatoire.")
    lieu = (p.get("lieu") or "").strip()
    sources = [s.lower() for s in p["sources"]] or ["hellowork", "indeed"]

    # --- 1. Collecte -------------------------------------------------------
    offres = []
    if "hellowork" in sources:
        log(f"Collecte HelloWork : « {poste} » ({lieu or 'toute la France'})…")
        hw = jobs_hellowork.rechercher_offres(poste, lieu, pages=int(p["pages"]))
        log(f"→ {len(hw)} offres HelloWork")
        offres += hw
    if "indeed" in sources:
        log("Collecte Indeed…")
        ind = jobs_indeed.rechercher_offres(
            poste, lieu,
            pages=int(p["pages"]),
            anciennete_jours=int(p["anciennete_jours"]) or None,
        )
        log(f"→ {len(ind)} offres Indeed")
        offres += ind

    # --- Filtres -----------------------------------------------------------
    avant = len(offres)
    offres = _filtrer_contrats(offres, p["contrats"], p["garder_contrat_inconnu"])
    if len(offres) != avant:
        log(f"Filtre contrats ({', '.join(p['contrats'])}) : {len(offres)}/{avant} offres gardées")
    if p["teletravail_uniquement"]:
        avant = len(offres)
        offres = _filtrer_teletravail(offres)
        log(f"Filtre télétravail : {len(offres)}/{avant} offres gardées")

    if not offres:
        log("Aucune offre après collecte/filtres.")
        return {"offres": [], "entreprises": [], "contacts": [], "fichier": "", "nb_nouvelles": 0}

    nb_nouvelles = _marquer_nouveautes(offres, _signature_recherche(poste, lieu))
    if nb_nouvelles:
        log(f"★ {nb_nouvelles} offre(s) jamais vue(s) depuis la dernière recherche")

    # --- 2. Entreprises ----------------------------------------------------
    entreprises = companies.consolider_entreprises(offres, p["exclusions"])
    log(f"{len(entreprises)} entreprises uniques (cabinets/intérim exclus)")

    # --- 3. Décideurs + emails ---------------------------------------------
    contacts = []
    if p["chercher_contacts"]:
        cibles = entreprises[: int(p["max_entreprises"])]
        log(f"Recherche des décideurs pour {len(cibles)} entreprises…")
        api_key = p["usebouncer_api_key"] if p["verifier_emails"] else ""
        if p["verifier_emails"] and not api_key:
            log("(pas de clé UseBouncer : les emails seront générés mais non vérifiés)")
        for i, ent in enumerate(cibles, 1):
            nom_ent = ent["entreprise"]
            log(f"[{i}/{len(cibles)}] {nom_ent}")
            trouves = linkedin_contacts.chercher_contacts(
                nom_ent,
                roles=p["roles_cibles"],
                max_par_role=int(p["contacts_max_par_role"]),
            )
            if trouves:
                domaine = emails.trouver_domaine(nom_ent)
                ent["domaine"] = domaine
                for c in trouves:
                    c["email"], c["statut_email"] = emails.meilleur_email(
                        c["nom"], domaine, api_key or None
                    )
                log(f"    {len(trouves)} contact(s)" + (f" — domaine {domaine}" if domaine else ""))
            else:
                log("    aucun contact trouvé")
            contacts += trouves
    else:
        log("Recherche de contacts désactivée.")

    # --- 4. Export ----------------------------------------------------------
    DOSSIER_RESULTATS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    nom_base = _signature_recherche(poste, lieu) or "recherche"
    fichier = DOSSIER_RESULTATS / f"prospection_{nom_base}_{horodatage}.xlsx"
    export_excel.exporter(str(fichier), offres, entreprises, contacts)
    log(f"Fichier Excel : {fichier.name}")

    return {
        "offres": offres,
        "entreprises": entreprises,
        "contacts": contacts,
        "fichier": str(fichier),
        "nb_nouvelles": nb_nouvelles,
    }
