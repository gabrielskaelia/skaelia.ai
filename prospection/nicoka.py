# -*- coding: utf-8 -*-
"""Intégration Nicoka (ATS/CRM) — lecture seule.

- Synchronise les contacts Nicoka dans un cache local (data/nicoka_cache.json).
- Fournit le statut d'un contact (déjà en base ? contacté il y a moins de N jours ?)
  pour filtrer nos recherches.
- Alimente l'onglet « Nicoka » (recherche + filtre « possible prospection »).

Le jeton (lecture seule) et l'URL sont dans config.json → "nicoka".
"""
import json
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from curl_cffi import requests

RACINE = Path(__file__).parent.parent
FICHIER_CONFIG = RACINE / "config.json"
DOSSIER_DONNEES = RACINE / "data"
FICHIER_CACHE = DOSSIER_DONNEES / "nicoka_cache.json"
FICHIER_REFS = DOSSIER_DONNEES / "nicoka_references.json"

_VERROU = threading.Lock()
# État de synchronisation (pour l'affichage de la progression)
SYNC = {"en_cours": False, "message": "", "total": 0, "recus": 0, "erreur": ""}


def _config():
    try:
        c = json.loads(FICHIER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return c.get("nicoka") or {}


def est_configure():
    c = _config()
    return bool(c.get("token") and c.get("base_url"))


def jours_prospection():
    return int(_config().get("jours_prospection", 50))


def _norm(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(ch for ch in texte if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()


def _get(path, params=None):
    c = _config()
    url = c["base_url"].rstrip("/") + "/" + path.lstrip("/")
    r = requests.get(url, params=params or {},
                     headers={"Authorization": "Bearer " + c["token"],
                              "Accept": "application/json"},
                     timeout=40)
    r.raise_for_status()
    return r.json()


def _linkedin_depuis(reseau_json):
    """social_networks = '{"2":"pseudo"}' -> https://www.linkedin.com/in/pseudo (type 2 = LinkedIn)."""
    try:
        d = json.loads(reseau_json) if reseau_json else {}
    except (json.JSONDecodeError, TypeError):
        return ""
    pseudo = d.get("2") or d.get(2)
    if not pseudo:
        return ""
    if pseudo.startswith("http"):
        return pseudo
    return "https://www.linkedin.com/in/" + pseudo.strip("/")


def _simplifier(c):
    nom = (c.get("label") or f"{c.get('first_name') or ''} {c.get('last_name') or ''}").strip()
    tel = c.get("phone1") or c.get("phone2") or ""
    return {
        "id": c.get("id"),
        "nom": nom,
        "email": (c.get("email") or "").strip(),
        "email2": (c.get("email2") or "").strip(),
        "telephone": tel,
        "poste": (c.get("jobtitle") or c.get("headline") or "").strip(),
        "customerid": c.get("customerid"),
        "last_action_on": c.get("last_action_on") or "",
        # Dates par TYPE d'interaction, pour reconstituer le « dernier échange »
        "last_email_sent_on": c.get("last_email_sent_on") or "",
        "last_email_received_on": c.get("last_email_received_on") or "",
        "last_phone_call_on": c.get("last_phone_call_on") or "",
        "last_meeting_on": c.get("last_meeting_on") or "",
        "last_note_on": c.get("last_note_on") or "",
        "linkedin": _linkedin_depuis(c.get("social_networks")),
        "url_nicoka": f"{_config().get('base_url','').replace('/api','')}/#/contacts/{c.get('id')}",
    }


# Libellé lisible du dernier échange, dans l'ordre chronologique inverse.
_TYPES_ECHANGE = [
    ("email envoyé", "last_email_sent_on"),
    ("email reçu", "last_email_received_on"),
    ("appel", "last_phone_call_on"),
    ("réunion", "last_meeting_on"),
    ("note", "last_note_on"),
]


def dernier_echange(contact):
    """Type + date de la dernière interaction connue avec un contact Nicoka.
    Renvoie {"type": "email envoyé"|…, "date": "AAAA-MM-JJ …"} ou {} si aucune."""
    candidats = [(lib, contact.get(champ)) for lib, champ in _TYPES_ECHANGE if contact.get(champ)]
    if not candidats:
        d = contact.get("last_action_on")
        return {"type": "", "date": d} if d else {}
    lib, date = max(candidats, key=lambda x: x[1])
    return {"type": lib, "date": date}


_TYPE_ACTIVITE = {1: "note", 2: "appel", 3: "email", 4: "réunion", 5: "tâche", 6: "SMS"}


def _texte_propre(html):
    """Retire les balises HTML et compacte les espaces."""
    if not html:
        return ""
    txt = re.sub(r"<[^>]+>", " ", str(html))
    txt = txt.replace("&nbsp;", " ").replace("&#39;", "'").replace("&amp;", "&")
    return re.sub(r"\s+", " ", txt).strip()


def dernier_echange_detaille(nicoka_id):
    """Récupère À LA DEMANDE la dernière ACTIVITÉ d'un contact Nicoka (le contenu
    réel affiché dans « Dernière action » : type, sujet, corps, date, auteur).
    Renvoie {} si aucune activité ou en cas d'erreur."""
    if not nicoka_id:
        return {}
    try:
        rep = _get(f"contacts/{int(nicoka_id)}/activities", {})
    except Exception:
        return {}
    lot = rep if isinstance(rep, list) else rep.get("data", [])
    if not lot:
        return {}
    # La plus récente d'abord
    lot = sorted(lot, key=lambda a: (a.get("date") or a.get("cdate") or ""), reverse=True)
    a = lot[0]
    corps = _texte_propre(a.get("comments") or "")
    return {
        "type": _TYPE_ACTIVITE.get(a.get("type"), "échange"),
        "sujet": (a.get("subject") or "").strip(),
        "corps": corps[:2000],
        "date": a.get("date") or a.get("cdate") or "",
        "auteur": _texte_propre(a.get("label") or ""),
    }


def synchroniser(log=lambda m: None):
    """Récupère tous les contacts Nicoka (paginé) et met à jour le cache local.
    Retourne le nombre de contacts synchronisés."""
    if not est_configure():
        raise RuntimeError("Nicoka n'est pas configuré (jeton manquant).")
    with _VERROU:
        if SYNC["en_cours"]:
            raise RuntimeError("Une synchronisation est déjà en cours.")
        SYNC.update({"en_cours": True, "message": "Connexion à Nicoka…",
                     "total": 0, "recus": 0, "erreur": ""})
    contacts = []
    vus = set()
    try:
        # L'API Nicoka pagine avec `offset` (le paramètre `page` est ignoré).
        limite = 200
        offset = 0
        while True:
            data = _get("contacts", {"limit": limite, "offset": offset})
            lot = data.get("data", [])
            if not lot:
                break
            nouveaux = 0
            for c in lot:
                if c.get("id") in vus:
                    continue
                vus.add(c.get("id"))
                contacts.append(_simplifier(c))
                nouveaux += 1
            SYNC["total"] = data.get("total", 0)
            SYNC["recus"] = len(contacts)
            SYNC["message"] = f"Récupération : {len(contacts)}/{SYNC['total']} contacts…"
            log(SYNC["message"])
            # Fin : lot incomplet, ou plus aucun nouveau contact (sécurité)
            if len(lot) < limite or nouveaux == 0:
                break
            offset += limite

        # Index pour recherche rapide
        index_email = {}
        index_nom = {}
        for ct in contacts:
            for mail in (ct["email"], ct["email2"]):
                if mail:
                    index_email[mail.lower()] = ct["id"]
            cle_nom = _norm(ct["nom"])
            if cle_nom:
                index_nom.setdefault(cle_nom, ct["id"])

        cache = {
            "synced_at": datetime.now().isoformat(timespec="seconds"),
            "jours_prospection": jours_prospection(),
            "total": len(contacts),
            "contacts": contacts,
            "index_email": index_email,
            "index_nom": index_nom,
        }
        DOSSIER_DONNEES.mkdir(exist_ok=True)
        FICHIER_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        SYNC["message"] = f"Synchronisation terminée : {len(contacts)} contacts."
        log(SYNC["message"])
        return len(contacts)
    except Exception as e:
        SYNC["erreur"] = str(e)
        raise
    finally:
        SYNC["en_cours"] = False


_CACHE_MEM = {"mtime": None, "data": None}


def _nom_client_propre(nom):
    """Nettoie le nom d'un client Nicoka ; renvoie "" si manifestement mal saisi
    (phrase, description, nom à rallonge) pour ne pas l'afficher dans un message."""
    nom = (nom or "").split("\n")[0].strip()
    nom = re.sub(r"\s+", " ", nom)
    if not nom or len(nom) > 40 or len(nom.split()) > 5:
        return ""
    # Fragments qui trahissent une saisie « phrase » plutôt qu'un nom d'entreprise
    if re.search(r"\b(on passant|en passant| at | via | chez | pour )\b", " " + nom.lower() + " "):
        return ""
    return nom


def type_compte_client():
    """Valeur du champ `type` d'un compte Nicoka correspondant au statut
    « Client » (configurable dans config.json → nicoka.type_client ; 1 par défaut)."""
    return int(_config().get("type_client", 1))


def synchroniser_references(log=lambda m: None):
    """Construit la liste des CLIENTS et des « références » (client + rôle) pour
    enrichir les messages de prospection.

    Source des clients : les COMPTES (endpoint `customers`) marqués « Client »
    (champ type = type_compte_client()). Le compte des missions se résout aussi
    via `customers` (et non `companies`). Retourne le nombre de références."""
    if not est_configure():
        return 0

    # 1. Comptes (customers) : id -> nom, et repérage des comptes « Client »
    type_client = type_compte_client()
    noms = {}
    clients = set()       # noms des comptes au statut « Client »
    clients_ids = set()   # leurs identifiants (pour rattacher les missions)
    offset = 0
    while True:
        d = _get("customers", {"limit": 200, "offset": offset})
        lot = d.get("data", [])
        if not lot:
            break
        for c in lot:
            nom = (c.get("label") or c.get("company_name") or "").strip()
            noms[c.get("id")] = nom
            if c.get("type") == type_client and nom:
                clients.add(nom)
                clients_ids.add(c.get("id"))
        if len(lot) < 200:
            break
        offset += 200

    # 2. Références (client + rôle) : missions des comptes clients uniquement
    refs = []
    offset = 0
    while True:
        d = _get("jobs", {"limit": 200, "offset": offset})
        lot = d.get("data", [])
        if not lot:
            break
        for j in lot:
            cid = j.get("customerid")
            if cid in clients_ids:
                client = _nom_client_propre(noms.get(cid, ""))
                role = (j.get("label") or "").strip()
                if client and role:
                    refs.append({"role": role, "client": client,
                                 "ville": (j.get("city") or "").strip()})
        if len(lot) < 200:
            break
        offset += 200

    DOSSIER_DONNEES.mkdir(exist_ok=True)
    FICHIER_REFS.write_text(json.dumps(
        {"synced_at": datetime.now().isoformat(timespec="seconds"),
         "references": refs, "clients": sorted(clients)},
        ensure_ascii=False), encoding="utf-8")
    log(f"{len(clients)} comptes « Client » et {len(refs)} références synchronisés")
    return len(refs)


def liste_clients():
    """Noms des entreprises déjà clientes (issues des missions Nicoka),
    pour les exclure du sourcing."""
    data = charger_references()
    return data.get("clients", []) if data else []


def charger_references():
    try:
        return json.loads(FICHIER_REFS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


_MOTS_ENT_VIDES = {"france", "groupe", "group", "sas", "sarl", "sa", "sasu",
                   "eurl", "the", "and", "les", "des", "international", "conseil",
                   "consulting", "solutions", "services", "technologies"}


def _tokens_entreprise(nom):
    """Mots significatifs d'un nom d'entreprise (pour comparer à un domaine email)."""
    n = _norm(nom)
    return [m for m in re.split(r"[^a-z0-9]+", n)
            if len(m) >= 3 and m not in _MOTS_ENT_VIDES]


def _domaine_email(email):
    """Cœur du domaine d'un email : 'jean@abb-france.com' -> 'abbfrance'."""
    if not email or "@" not in email:
        return ""
    dom = email.split("@")[1].split(".")[0].lower()
    return re.sub(r"[^a-z0-9]+", "", dom)


def _domaine_correspond(tokens, domaine):
    """Le domaine email correspond-il à l'un des mots de l'entreprise ?"""
    if not domaine:
        return False
    for t in tokens:
        if domaine == t:
            return True
        if len(t) >= 4 and len(domaine) >= 4 and (domaine.startswith(t) or t.startswith(domaine)):
            return True
    return False


def contacts_pour_entreprise(nom_entreprise, max_contacts=3):
    """Récupère dans Nicoka les contacts déjà enregistrés qui travaillent DANS
    l'entreprise (rapprochement sur le domaine de leur email professionnel).
    Retourne une liste au même format que les contacts LinkedIn, du plus
    récemment travaillé au plus ancien."""
    cache = charger_cache()
    if not cache:
        return []
    tokens = _tokens_entreprise(nom_entreprise)
    if not tokens:
        return []
    trouves = []
    for c in cache.get("contacts", []):
        email = c.get("email", "") or c.get("email2", "")
        if _domaine_correspond(tokens, _domaine_email(email)):
            trouves.append(c)
    trouves.sort(key=lambda c: c.get("last_action_on") or "", reverse=True)
    resultat = []
    for c in trouves[:max_contacts]:
        email = c.get("email", "") or c.get("email2", "")
        resultat.append({
            "entreprise": nom_entreprise,
            "nom": c.get("nom", ""),
            "poste": c.get("poste", ""),
            "entreprise_profil": "",
            "url_linkedin": c.get("linkedin", ""),
            "email": email,
            "telephone": c.get("telephone", ""),
            "statut_email": "",
            "extrait": "",
            "source_contact": "nicoka",
            "url_nicoka": c.get("url_nicoka", ""),
        })
    return resultat


_MOTS_VIDES = {"h", "f", "hf", "junior", "senior", "confirme", "stage", "cdi",
               "cdd", "alternance", "poste", "de", "en", "et", "la", "le", "les",
               "un", "une", "des", "du", "recherche", "recherché", "profil"}

# Mots « niveau de poste » (pas un secteur) : ils ne suffisent PAS à rapprocher
# deux métiers. Ex. « Ingénieur Commercial » et « Ingénieur ERP » partagent
# « ingénieur » mais ne sont pas le même secteur.
_MOTS_GENERIQUES = {
    "ingenieur", "ingenieure", "consultant", "consultante", "responsable",
    "charge", "chargee", "assistant", "assistante", "technicien", "technicienne",
    "chef", "cheffe", "directeur", "directrice", "manager", "adjoint", "adjointe",
    "coordinateur", "coordinatrice", "gestionnaire", "specialiste", "expert",
    "experte", "conseiller", "conseillere", "agent", "operateur", "stagiaire",
    "alternant", "alternante", "business", "officer", "leader", "lead",
}


def references_pour(poste, n=2):
    """Retourne jusqu'à `n` références clients dont le rôle est dans le MÊME
    métier que le poste recherché. Ne rapproche que sur des mots de secteur
    (pas sur un simple « ingénieur »/« consultant »), pour éviter les
    rapprochements sans rapport. Renvoie [] si rien de pertinent."""
    data = charger_references()
    if not data:
        return []
    mots = [m for m in _norm(poste).split() if len(m) >= 3 and m not in _MOTS_VIDES]
    # On ne garde que les mots « métier/secteur » (hors mots génériques de niveau)
    mots_secteur = [m for m in mots if m not in _MOTS_GENERIQUES]
    if not mots_secteur:
        return []  # que des mots génériques -> aucun rapprochement fiable
    scored = []
    for r in data.get("references", []):
        rn = _norm(r["role"])
        score = sum(1 for m in mots_secteur if m in rn)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    vus, sortie = set(), []
    for _, r in scored:
        cle = r["client"].lower()
        if cle in vus:
            continue
        vus.add(cle)
        sortie.append(r)
        if len(sortie) >= n:
            break
    return sortie


def charger_cache():
    """Charge le cache Nicoka, en mémorisant le résultat tant que le fichier
    n'a pas changé (évite de relire plusieurs Mo de JSON à chaque appel)."""
    try:
        mtime = FICHIER_CACHE.stat().st_mtime
    except FileNotFoundError:
        return None
    if _CACHE_MEM["mtime"] == mtime and _CACHE_MEM["data"] is not None:
        return _CACHE_MEM["data"]
    try:
        data = json.loads(FICHIER_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    # Index id -> contact pour un accès O(1)
    data["_par_id"] = {c["id"]: c for c in data.get("contacts", [])}
    _CACHE_MEM["mtime"] = mtime
    _CACHE_MEM["data"] = data
    return data


def _jours_depuis(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(date_str[:19], fmt)
            return (datetime.now() - d).days
        except ValueError:
            continue
    return None


def statut_pour(email="", nom="", cache=None):
    """Retourne le statut Nicoka d'un contact :
    {en_base, jours_depuis_action, recent} — recent = contacté il y a < N jours."""
    cache = cache or charger_cache()
    if not cache:
        return {"en_base": False, "jours_depuis_action": None, "recent": False, "connu": False}
    cid = None
    if email:
        cid = cache["index_email"].get(email.lower())
    if not cid and nom:
        cid = cache["index_nom"].get(_norm(nom))
    if not cid:
        return {"en_base": False, "jours_depuis_action": None, "recent": False, "connu": True}
    contact = cache.get("_par_id", {}).get(cid) or next(
        (c for c in cache["contacts"] if c["id"] == cid), None)
    jours = _jours_depuis(contact["last_action_on"]) if contact else None
    seuil = cache.get("jours_prospection", 50)
    recent = jours is not None and jours < seuil
    echange = dernier_echange(contact) if contact else {}
    return {"en_base": True, "jours_depuis_action": jours, "recent": recent,
            "connu": True, "id": cid,
            "last_action_on": contact["last_action_on"] if contact else "",
            "dernier_echange": echange,
            "url_nicoka": contact["url_nicoka"] if contact else ""}


def annoter_contacts(contacts):
    """Ajoute à chaque contact de nos recherches un champ `nicoka` (statut)."""
    cache = charger_cache()
    for c in contacts:
        c["nicoka"] = statut_pour(c.get("email", ""), c.get("nom", ""), cache)
    return contacts


def lister(recherche="", possible_prospection=False, page=1, par_page=50):
    """Liste paginée des contacts du cache, avec recherche texte et filtre
    « possible prospection » (dernière action nulle ou > N jours)."""
    cache = charger_cache()
    if not cache:
        return {"contacts": [], "total": 0, "page": 1, "pages": 0,
                "synced_at": None, "jours": jours_prospection()}
    seuil = cache.get("jours_prospection", 50)
    contacts = cache["contacts"]

    if recherche:
        q = _norm(recherche)
        contacts = [c for c in contacts
                    if q in _norm(c["nom"]) or q in _norm(c["email"]) or q in _norm(c["poste"])]

    if possible_prospection:
        filtres = []
        for c in contacts:
            j = _jours_depuis(c["last_action_on"])
            if j is None or j >= seuil:
                filtres.append(c)
        contacts = filtres

    # Tri : plus ancienne action d'abord (les plus « froids » en tête)
    contacts = sorted(contacts, key=lambda c: c["last_action_on"] or "")

    total = len(contacts)
    pages = max(1, (total + par_page - 1) // par_page)
    page = max(1, min(page, pages))
    debut = (page - 1) * par_page
    lot = contacts[debut:debut + par_page]
    # Ajouter le nombre de jours pour l'affichage
    for c in lot:
        c = c  # (déjà des dict du cache, on n'écrit pas dedans durablement)
    enrichis = []
    for c in lot:
        j = _jours_depuis(c["last_action_on"])
        enrichis.append({**c, "jours_depuis_action": j,
                         "a_prospecter": j is None or j >= seuil})

    return {"contacts": enrichis, "total": total, "page": page, "pages": pages,
            "synced_at": cache.get("synced_at"), "jours": seuil,
            "total_base": cache.get("total", 0)}
