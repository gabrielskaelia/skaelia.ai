# -*- coding: utf-8 -*-
"""Offres publiées par des cabinets de recrutement / agences d'intérim :
tente de retrouver l'entreprise CLIENTE (« demandeuse ») à partir du texte
de l'annonce, pour prospecter la bonne entreprise avec le bon contact.

Beaucoup d'annonces de cabinets sont anonymes (« notre client, acteur majeur
de… ») : dans ce cas l'offre est écartée comme avant. Quand le client est
nommé (« pour notre client Legrand », « le groupe SEB recrute »), l'offre est
réattribuée à ce client.
"""
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests

from .companies import _normaliser

# Plafond d'annonces téléchargées par recherche (une requête HTTP par annonce)
MAX_ANNONCES = 25

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


def deviner_client(url, nom_cabinet=""):
    """Nom de l'entreprise cliente citée dans l'annonce, ou None."""
    try:
        texte = _texte_annonce(url)
    except Exception:
        return None
    for motif in _MOTIFS:
        for m in motif.finditer(texte):
            nom = _nettoyer_nom(m.group(1), nom_cabinet)
            if nom:
                return nom
    return None


def reattribuer(offres, exclusions, log=print):
    """Pour chaque offre publiée par un cabinet : tente de retrouver le client
    final et réattribue l'offre à ce client (champ `via_cabinet` conservé).
    Les offres de cabinets restées anonymes sont écartées, comme avant."""
    exclusions_norm = {_normaliser(e) for e in (exclusions or []) if e}
    de_cabinets = [o for o in offres
                   if est_cabinet(o.get("entreprise", ""), exclusions_norm)]
    if not de_cabinets:
        return offres
    a_analyser = de_cabinets[:MAX_ANNONCES]
    log(f"Cabinets : analyse de {len(a_analyser)} annonce(s) pour retrouver l'entreprise cliente…")

    devines = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futurs = {ex.submit(deviner_client, o["url"], o.get("entreprise", "")): o
                  for o in a_analyser}
        for f, o in futurs.items():
            try:
                devines[o["url"]] = f.result()
            except Exception:
                devines[o["url"]] = None

    gardees, retrouvees = [], 0
    for o in offres:
        if o not in de_cabinets:
            gardees.append(o)
            continue
        client = devines.get(o["url"])
        if client:
            o["via_cabinet"] = o.get("entreprise", "")
            o["entreprise"] = client
            gardees.append(o)
            retrouvees += 1
        # sinon : annonce anonyme -> écartée (comportement historique)
    log(f"Cabinets : {retrouvees} entreprise(s) cliente(s) retrouvée(s) "
        f"sur {len(a_analyser)} annonce(s), {len(de_cabinets) - retrouvees} écartée(s) (client anonyme)")
    return gardees
