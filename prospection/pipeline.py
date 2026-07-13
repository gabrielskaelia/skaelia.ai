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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import (companies, enrichment, export_excel, jobs_hellowork,
               jobs_indeed, jobs_linkedin, linkedin_contacts, nicoka)

RACINE = Path(__file__).parent.parent
DOSSIER_DONNEES = RACINE / "data"
DOSSIER_RESULTATS = RACINE / "resultats"
_VERROU_HISTORIQUE = threading.Lock()

CONTRATS_CONNUS = ["CDI", "CDD", "Intérim", "Alternance", "Stage", "Indépendant"]


def _date_absolue(texte, maintenant=None):
    """Convertit une date de publication RELATIVE (« il y a 3 jours »,
    « aujourd'hui », « hier »…) en date ABSOLUE « JJ/MM/AAAA », figée au moment
    de la collecte. Ainsi « il y a 10 h » reste juste 3 jours plus tard.
    Les dates déjà absolues (JJ/MM/AAAA) sont conservées telles quelles."""
    from datetime import timedelta
    t = (texte or "").strip().lower()
    if not t:
        return ""
    maintenant = maintenant or datetime.now()
    # Déjà au format absolu ?
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", t):
        return texte.strip()
    if "aujourd" in t:
        return maintenant.strftime("%d/%m/%Y")
    if t == "hier":
        return (maintenant - timedelta(days=1)).strftime("%d/%m/%Y")
    m = re.search(r"il y a\s+(\d+)\s*(minute|heure|jour|semaine|mois|an)", t)
    if m:
        n = int(m.group(1)); unite = m.group(2)
        delta = {"minute": timedelta(0), "heure": timedelta(0),
                 "jour": timedelta(days=n), "semaine": timedelta(weeks=n),
                 "mois": timedelta(days=30 * n), "an": timedelta(days=365 * n)}[unite]
        return (maintenant - delta).strftime("%d/%m/%Y")
    if re.search(r"il y a\s+(une|un)\s*(heure|minute)", t) or "instant" in t:
        return maintenant.strftime("%d/%m/%Y")
    return texte.strip()  # format inconnu : on garde tel quel

# Recherche améliorée (FullEnrich, payante) : nombre max d'entreprises réellement
# interrogées via FullEnrich par recherche, pour borner le coût (~0,25 crédit par
# décideur). Au-delà, on repasse au gratuit (DuckDuckGo).
PLAFOND_ENTREPRISES_FULLENRICH = 20

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
    "nb_contacts_cible": 0,
    "contacts_max_par_role": 2,
    "roles_cibles": None,
    "recherche_amelioree": False,
    "exclusions": [],
    "clients": [],
    "types_entreprise": ["prospect", "client"],
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
    mode_clients = bool(p.get("mode_clients"))
    if not poste and not mode_clients:
        raise ValueError("Le poste recherché est obligatoire.")
    lieu = (p.get("lieu") or "").strip()
    sources = [s.lower() for s in p["sources"]] or ["hellowork", "indeed"]

    # --- 1. Collecte (sources interrogées en parallèle) --------------------
    pages = int(p["pages"])
    noms = {"hellowork": "HelloWork", "indeed": "Indeed",
            "linkedin": "LinkedIn", "wttj": "Welcome to the Jungle"}
    a_lancer = [s for s in ("hellowork", "indeed", "linkedin", "wttj") if s in sources]

    def _collecter(terme, nb_pages):
        """Interroge une source pour un terme de recherche donné."""
        def _hellowork():
            return jobs_hellowork.rechercher_offres(terme, lieu, pages=nb_pages)

        def _indeed():
            return jobs_indeed.rechercher_offres(
                terme, lieu, pages=nb_pages,
                anciennete_jours=int(p["anciennete_jours"]) or None)

        def _linkedin():
            return jobs_linkedin.rechercher_offres(terme, lieu, pages=nb_pages)

        def _wttj():
            from . import jobs_wttj
            return jobs_wttj.rechercher_offres(terme, lieu, pages=nb_pages,
                                               rayon_km=int(p["rayon_km"]))
        return {"hellowork": _hellowork, "indeed": _indeed,
                "linkedin": _linkedin, "wttj": _wttj}

    offres = []
    if mode_clients:
        # Recherche « Offres de nos clients » : on interroge chaque client Nicoka
        # par son nom, tous secteurs confondus, pour voir lesquels recrutent.
        clients = [c for c in (p.get("clients") or []) if c]
        log(f"Recherche des offres de nos {len(clients)} clients (tous secteurs)…")
        taches = [(cl, s) for cl in clients for s in a_lancer]
        with ThreadPoolExecutor(max_workers=8) as ex:
            futurs = {ex.submit(_collecter(cl, 1)[s]): (cl, s) for cl, s in taches}
            for f, (cl, s) in futurs.items():
                try:
                    offres += f.result()
                except Exception:
                    pass
        log(f"→ {len(offres)} offres collectées auprès des clients")
    else:
        log(f"Collecte de {len(a_lancer)} source(s) en parallèle : « {poste} » ({lieu or 'toute la France'})…")
        collecteurs = _collecter(poste, pages)
        with ThreadPoolExecutor(max_workers=max(1, len(a_lancer))) as ex:
            futurs = {ex.submit(collecteurs[s]): s for s in a_lancer}
            for f, s in futurs.items():
                try:
                    trouvees = f.result()
                    log(f"→ {len(trouvees)} offres {noms[s]}")
                    offres += trouvees
                except Exception as e:
                    log(f"→ {noms[s]} indisponible : {e}")

    # Libellé de recherche pour la signature / l'historique (poste vide en mode clients)
    if not poste:
        poste = "offres de nos clients"

    # Dates de publication : on fige le relatif en date absolue AU MOMENT de la
    # collecte, pour que l'historique reste cohérent dans le temps.
    maintenant = datetime.now()
    for o in offres:
        o["date"] = _date_absolue(o.get("date", ""), maintenant)

    # --- Filtres -----------------------------------------------------------
    avant = len(offres)
    offres = _filtrer_contrats(offres, p["contrats"], p["garder_contrat_inconnu"])
    if len(offres) != avant:
        log(f"Filtre contrats ({', '.join(p['contrats'])}) : {len(offres)}/{avant} offres gardées")
    if p["teletravail_uniquement"]:
        avant = len(offres)
        offres = _filtrer_teletravail(offres)
        log(f"Filtre télétravail : {len(offres)}/{avant} offres gardées")

    # Offres de cabinets : retrouver l'entreprise cliente citée dans l'annonce
    # (opt-in). Sans ce réglage, elles restent exclues à la consolidation.
    if p.get("inclure_cabinets"):
        from . import cabinets
        offres = cabinets.reattribuer(offres, p["exclusions"], log)

    if not offres:
        log("Aucune offre après collecte/filtres.")
        return {"offres": [], "entreprises": [], "contacts": [], "fichier": "", "nb_nouvelles": 0}

    cle_user = p.get("cle_user", "")
    nb_nouvelles = _marquer_nouveautes(
        offres, (cle_user + "_" if cle_user else "") + _signature_recherche(poste, lieu))
    if nb_nouvelles:
        log(f"★ {nb_nouvelles} offre(s) jamais vue(s) depuis la dernière recherche")

    # --- 2. Entreprises (classées client / prospect) -----------------------
    entreprises = companies.consolider_entreprises(offres, p["exclusions"], p["clients"])
    # Filtre sur le type demandé (prospect / client)
    types_voulus = set(p["types_entreprise"]) or {"prospect", "client"}
    if types_voulus != {"prospect", "client"}:
        avant = len(entreprises)
        entreprises = [e for e in entreprises if e.get("type") in types_voulus]
        log(f"Filtre type ({', '.join(sorted(types_voulus))}) : {len(entreprises)}/{avant} entreprises")
    nb_clients = sum(1 for e in entreprises if e.get("type") == "client")
    log(f"{len(entreprises)} entreprises uniques dont {nb_clients} client(s) — cabinets et intérim exclus")
    # Répercuter le type sur les offres (pour l'affichage)
    type_par_ent = {companies._normaliser(e["entreprise"]): e.get("type") for e in entreprises}
    for o in offres:
        o["type"] = type_par_ent.get(companies._normaliser(o.get("entreprise", "")), "")

    # --- 3. Décideurs (sans email : le vrai email + téléphone sont trouvés à
    #        l'ajout du contact, via FullEnrich) — entreprises en parallèle ---
    contacts = []
    if p["chercher_contacts"]:
        cible_nb = int(p.get("nb_contacts_cible") or 0)
        cibles = entreprises[: int(p["max_entreprises"])]
        if cible_nb:
            log(f"Recherche des décideurs jusqu'à {cible_nb} contact(s) (en parallèle)…")
        else:
            log(f"Recherche des décideurs pour {len(cibles)} entreprises (en parallèle)…")
        fait = {"n": 0}
        _fe = {"n": 0}  # nb d'entreprises interrogées via FullEnrich (plafonné)
        verrou = threading.Lock()
        recherche_amelioree = bool(p.get("recherche_amelioree")) and enrichment.est_configure()
        if recherche_amelioree:
            log(f"Recherche améliorée FullEnrich activée (plafond {PLAFOND_ENTREPRISES_FULLENRICH} entreprises, repli DuckDuckGo au-delà).")

        def _pour_entreprise(ent):
            # Entreprise cliente : le contact est déjà dans Nicoka, on le
            # récupère (pas de recherche LinkedIn). Prospect : recherche LinkedIn.
            if ent.get("type") == "client":
                trouves = nicoka.contacts_pour_entreprise(
                    ent["entreprise"], max_contacts=int(p["contacts_max_par_role"]) + 1)
                origine = "Nicoka"
            else:
                origine = "LinkedIn"
                trouves = []
                # Recherche améliorée (FullEnrich, payante) : plafonnée en nombre
                # d'entreprises pour maîtriser les crédits ; repli DuckDuckGo
                # au-delà du plafond ou si FullEnrich ne renvoie rien.
                if recherche_amelioree:
                    with verrou:
                        sous_plafond = _fe["n"] < PLAFOND_ENTREPRISES_FULLENRICH
                        if sous_plafond:
                            _fe["n"] += 1
                    if sous_plafond:
                        trouves = enrichment.rechercher_decideurs(
                            ent["entreprise"], roles=p["roles_cibles"],
                            max_contacts=int(p["contacts_max_par_role"]), log=log)
                        origine = "FullEnrich"
                if not trouves:
                    trouves = linkedin_contacts.chercher_contacts(
                        ent["entreprise"],
                        roles=p["roles_cibles"],
                        max_contacts=int(p["contacts_max_par_role"]) + 1,
                    )
                    if origine == "FullEnrich":
                        origine = "FullEnrich→LinkedIn"
            for c in trouves:
                c.setdefault("email", "")
                c.setdefault("statut_email", "")
                c["type"] = ent.get("type", "")
            with verrou:
                fait["n"] += 1
                log(f"[{fait['n']}] {ent['entreprise']} ({origine}) : "
                    + (f"{len(trouves)} contact(s)" if trouves else "aucun contact"))
            return trouves

        # Toutes les entreprises sont lancées d'un coup ; on encaisse les
        # résultats au fil de l'eau et on s'arrête net dès la cible atteinte.
        ex = ThreadPoolExecutor(max_workers=10)
        futurs = [ex.submit(_pour_entreprise, ent) for ent in cibles]
        try:
            for f in as_completed(futurs):
                contacts += f.result()
                if cible_nb and len(contacts) >= cible_nb:
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        if cible_nb and len(contacts) > cible_nb:
            contacts = contacts[:cible_nb]
        if cible_nb:
            log(f"→ {len(contacts)} contact(s) retenus"
                + (" (cible atteinte)" if len(contacts) >= cible_nb else " (cible non atteinte, tout ratissé)"))
    else:
        log("Recherche de contacts désactivée.")

    # --- 4. Export (dans le dossier du compte) ------------------------------
    dossier = Path(p["dossier_resultats"]) if p.get("dossier_resultats") else DOSSIER_RESULTATS
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    nom_base = _signature_recherche(poste, lieu) or "recherche"
    fichier = dossier / f"prospection_{nom_base}_{horodatage}.xlsx"
    export_excel.exporter(str(fichier), offres, entreprises, contacts)
    log(f"Fichier Excel : {fichier.name}")

    return {
        "offres": offres,
        "entreprises": entreprises,
        "contacts": contacts,
        "fichier": str(fichier),
        "nb_nouvelles": nb_nouvelles,
    }
