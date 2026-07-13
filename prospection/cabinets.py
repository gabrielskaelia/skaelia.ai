# -*- coding: utf-8 -*-
"""Offres publiées par des cabinets de recrutement / agences d'intérim :
tente de retrouver l'entreprise CLIENTE (« demandeuse ») à partir du texte
de l'annonce, pour prospecter la bonne entreprise avec le bon contact.

Beaucoup d'annonces de cabinets sont anonymes (« notre client, acteur majeur
de… ») : dans ce cas l'offre est écartée comme avant. Quand le client est
nommé (« pour notre client Legrand », « le groupe SEB recrute »), l'offre est
réattribuée à ce client.
"""
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from curl_cffi import requests

from .companies import _normaliser

# Plafond d'annonces téléchargées par recherche (une requête HTTP par annonce)
MAX_ANNONCES = 25

FICHIER_CONFIG = Path(__file__).parent.parent / "config.json"

# Mots qui indiquent que la « capture » n'est pas un nom d'entreprise
_MOTS_GENERIQUES = {
    "un", "une", "notre", "leur", "ce", "cette", "la", "le",
    "societe", "entreprise", "groupe", "structure", "acteur", "leader",
    "specialiste", "specialise", "specialisee", "pme", "eti", "startup",
    "client", "clients", "final", "grand", "grande", "important", "importante",
    "industriel", "industrielle", "francais", "francaise", "international",
    "internationale", "belle", "beau", "cabinet", "agence", "filiale",
    "reconnu", "reconnue", "majeur", "majeure", "dynamique", "innovant",
    "innovante", "base", "basee", "situe", "situee", "implante", "implantee",
}

# Indices qu'un nom d'employeur est un cabinet / une agence (en plus de la
# liste d'exclusions configurée)
_RE_CABINET = re.compile(
    r"recrutement|recruteur|recruitment|interim|intérim|staffing|headhunt"
    r"|executive search|talents?\b|conseil rh|cabinet|\brh\b", re.I)

_NOM = r"([A-ZÉÈÀÇ][\w&'’\-.]*(?:\s+(?:[A-ZÉÈÀÇ&][\w&'’\-.]*|et|de|du|des|d'|&)){0,3})"
_ART_SOCIETE = r"(?:[Ll]a\s+societe|[Ll]a\s+société|[Ll][’']entreprise|[Ll]e\s+groupe)?\s*"
_MOTIFS = [
    # « pour notre client X », « chez son client X », « auprès de son client X »
    re.compile(r"(?:pour|chez|aupres\s+d[e'’]|auprès\s+d[e'’])\s+"
               r"(?:notre|son|sa|un\s+de\s+nos|l[ea])?\s*clients?\s*[,:]?\s+"
               + _ART_SOCIETE + _NOM),
    # « pour le compte de X »
    re.compile(r"[Ll]e\s+compte\s+d[e'’]\s*" + _ART_SOCIETE + _NOM),
    # « recrute pour (la société) X », « recrutons pour X »
    re.compile(r"recrut(?:e|ons)\s+pour\s+" + _ART_SOCIETE + _NOM),
    # « la société X recherche / recrute »
    re.compile(r"(?:[Ll]a\s+societe|[Ll]a\s+société|[Ll]e\s+groupe|[Ll][’']entreprise)\s+"
               + _NOM + r"\s+(?:recherche|recrute)"),
]


def _sans_accents(texte):
    t = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def est_cabinet(nom, exclusions_norm):
    """True si `nom` ressemble à un cabinet / une agence (liste configurée
    dans les Réglages + mots-clés usuels du métier)."""
    cle = _normaliser(nom or "")
    if not cle:
        return False
    if any(cle == ex or cle.startswith(ex + " ") for ex in exclusions_norm if ex):
        return True
    return bool(_RE_CABINET.search(nom))


def _texte_annonce(url):
    r = requests.get(url, impersonate="chrome", timeout=25)
    r.raise_for_status()
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
    texte = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", texte)


def _nettoyer_nom(brut, nom_cabinet=""):
    """Garde les mots jusqu'au premier terme générique ; rejette les captures
    qui ne sont pas des noms d'entreprise (ou qui citent le cabinet lui-même)."""
    mots = brut.strip(" ,.;:!?").split()
    # Article de tête toléré (« La Banque Postale » -> « Banque Postale »)
    while mots and _sans_accents(mots[0]).strip("'’-.") in ("la", "le", "les", "l", "un", "une"):
        mots = mots[1:]
    retenus = []
    for mot in mots:
        if _sans_accents(mot).strip("'’-.") in _MOTS_GENERIQUES:
            break
        retenus.append(mot)
    nom = " ".join(retenus).strip(" ,.;:!?-")
    if len(nom) < 2:
        return None
    # La capture doit être un nom propre, pas une phrase
    if len(retenus) > 4:
        return None
    # Ne pas « retrouver » le cabinet lui-même
    if nom_cabinet and _normaliser(nom) and _normaliser(nom) in _normaliser(nom_cabinet):
        return None
    return nom


def _client_nomme(texte, nom_cabinet=""):
    """Nom de l'entreprise cliente EXPLICITEMENT citée dans l'annonce, ou None."""
    for motif in _MOTIFS:
        for m in motif.finditer(texte):
            nom = _nettoyer_nom(m.group(1), nom_cabinet)
            if nom:
                return nom
    return None


def deviner_client(url, nom_cabinet=""):
    """Nom de l'entreprise cliente citée dans l'annonce, ou None."""
    try:
        texte = _texte_annonce(url)
    except Exception:
        return None
    return _client_nomme(texte, nom_cabinet)


# --- Estimation IA de l'entreprise derrière une annonce anonyme -------------
# Beaucoup de cabinets (ex. Skaelia) publient sans nommer leur client
# (« notre client, une société de conseil de 160 collaborateurs à Levallois… »).
# Quand aucun nom n'est cité, on demande à Claude de PROPOSER l'entreprise la
# plus probable à partir des indices (secteur, effectif, lieu, certifications…).
# Nécessite une clé dans config.json → "anthropic": {"api_key": "..."}.

_ENDPOINT_IA = "https://api.anthropic.com/v1/messages"
_MODELE_IA_DEFAUT = "claude-opus-4-8"
_CONFIANCES = ("haute", "moyenne", "faible")


def _config_ia():
    try:
        c = json.loads(FICHIER_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return c.get("anthropic") or {}


def ia_active():
    """True si une clé d'API Claude est configurée (estimation possible)."""
    return bool(_config_ia().get("api_key"))


def _extraire_json(txt):
    """Isole le premier objet JSON d'une réponse (au cas où le modèle enrobe)."""
    debut = txt.find("{")
    fin = txt.rfind("}")
    if debut == -1 or fin == -1 or fin < debut:
        return "{}"
    return txt[debut:fin + 1]


def estimer_client_ia(texte, nom_cabinet=""):
    """Estimation IA de l'entreprise cliente derrière une annonce anonyme.
    Retourne {"nom": ..., "confiance": "haute|moyenne|faible"} ou None."""
    cfg = _config_ia()
    cle = cfg.get("api_key")
    if not cle:
        return None
    modele = cfg.get("modele") or _MODELE_IA_DEFAUT
    extrait = (texte or "")[:6000]
    prompt = (
        "Tu es analyste en intelligence économique. Le texte ci-dessous est une "
        "annonce d'emploi publiée par un cabinet de recrutement ou une agence, "
        "qui NE nomme PAS explicitement l'entreprise cliente pour laquelle il "
        "recrute. À partir des indices concrets (secteur, effectif, chiffre "
        "d'affaires, localisation précise, certifications, marchés, produits, "
        "clients cités, historique…), propose le nom de l'entreprise française "
        "la PLUS PROBABLE derrière cette annonce.\n\n"
        f"Cabinet qui publie : {nom_cabinet or 'inconnu'}\n"
        f'Annonce :\n"""{extrait}"""\n\n'
        "Réponds UNIQUEMENT par un objet JSON, sans texte autour :\n"
        '{"entreprise": "<nom probable, ou null si aucun indice suffisant>", '
        '"confiance": "haute|moyenne|faible", "indices": "<courte justification>"}\n\n'
        "Ne propose un nom que si des indices concrets le permettent. En cas de "
        'doute réel, mets "entreprise": null. Ne devine jamais au hasard.')
    try:
        r = requests.post(
            _ENDPOINT_IA,
            headers={"x-api-key": cle,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": modele, "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=45)
        r.raise_for_status()
        blocs = r.json().get("content", [])
        txt = "".join(b.get("text", "") for b in blocs if b.get("type") == "text")
        data = json.loads(_extraire_json(txt))
    except Exception:
        return None
    nom = (data.get("entreprise") or "")
    nom = nom.strip() if isinstance(nom, str) else ""
    if not nom or nom.lower() in ("null", "none", "inconnu", "inconnue", "n/a"):
        return None
    # Ne pas « estimer » le cabinet lui-même
    if nom_cabinet and _normaliser(nom) and _normaliser(nom) in _normaliser(nom_cabinet):
        return None
    conf = str(data.get("confiance") or "faible").strip().lower()
    if conf not in _CONFIANCES:
        conf = "faible"
    return {"nom": nom, "confiance": conf}


def _analyser_annonce(url, nom_cabinet, avec_ia):
    """Retrouve l'entreprise cliente d'une annonce de cabinet.
    Retourne {"client", "estime": bool, "confiance"} ou None."""
    try:
        texte = _texte_annonce(url)
    except Exception:
        return None
    # 1. client nommé explicitement -> fiable
    nom = _client_nomme(texte, nom_cabinet)
    if nom:
        return {"client": nom, "estime": False, "confiance": None}
    # 2. client anonyme -> estimation IA (si configurée)
    if avec_ia:
        est = estimer_client_ia(texte, nom_cabinet)
        if est:
            return {"client": est["nom"], "estime": True, "confiance": est["confiance"]}
    return None


def reattribuer(offres, exclusions, log=print):
    """Mode « Offre de cabinet » : ne renvoie QUE les offres opaques (publiées
    par un cabinet). Pour chacune, tente de retrouver le client final (nommé
    dans l'annonce, ou estimé par IA) ; le nom du cabinet est conservé dans
    `via_cabinet`. Les offres à employeur direct sont écartées."""
    exclusions_norm = {_normaliser(e) for e in (exclusions or []) if e}
    de_cabinets = [o for o in offres
                   if est_cabinet(o.get("entreprise", ""), exclusions_norm)]
    if not de_cabinets:
        log("Cabinets : aucune offre de cabinet dans les résultats.")
        return []
    a_analyser = de_cabinets[:MAX_ANNONCES]
    avec_ia = ia_active()
    detail = " (client nommé + estimation IA des annonces anonymes)" if avec_ia else ""
    log(f"Cabinets : analyse de {len(a_analyser)} annonce(s) pour retrouver l'entreprise cliente{detail}…")

    resultats = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futurs = {ex.submit(_analyser_annonce, o["url"], o.get("entreprise", ""), avec_ia): o
                  for o in a_analyser}
        for f, o in futurs.items():
            try:
                resultats[o["url"]] = f.result()
            except Exception:
                resultats[o["url"]] = None

    # Mode cabinet : on ne garde QUE les offres opaques (publiées par un
    # cabinet). Les offres à employeur direct sont écartées — l'intérêt du
    # bouton est justement de ne remonter que ces annonces masquées.
    # Le nom du cabinet est toujours affiché ; le client réel (nommé ou estimé)
    # prend sa place, sinon « client non identifié » (non prospecté).
    gardees, nommees, estimees, inconnues = [], 0, 0, 0
    for o in de_cabinets:
        o["via_cabinet"] = o.get("entreprise", "")
        o.pop("client_estime", None)
        o.pop("client_confiance", None)
        o.pop("client_inconnu", None)
        res = resultats.get(o["url"])
        if res:
            o["entreprise"] = res["client"]
            if res["estime"]:
                o["client_estime"] = True
                o["client_confiance"] = res["confiance"]
                estimees += 1
            else:
                nommees += 1
        else:
            # client anonyme non identifié : on garde l'offre pour l'affichage,
            # mais entreprise vide -> ignorée par la consolidation (pas prospectée)
            o["entreprise"] = ""
            o["client_inconnu"] = True
            inconnues += 1
        gardees.append(o)
    log(f"Cabinets : {nommees} client(s) nommé(s), {estimees} estimé(s) par IA, "
        f"{inconnues} cabinet(s) affiché(s) sans client identifié")
    return gardees
