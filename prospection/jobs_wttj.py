# -*- coding: utf-8 -*-
"""Collecte des offres d'emploi sur Welcome to the Jungle.

WTTJ est une application React : les offres ne sont pas dans le HTML de la page.
La recherche est propulsée par Algolia (index public `wk_cms_jobs_production`).
La clé de recherche est restreinte par en-tête `Referer` : on envoie donc le
Referer du site WTTJ. API publique et accessible depuis n'importe quelle IP
(contrairement à Indeed).

Recherche par lieu : Algolia ne filtre pas par ville dans cette requête. On
géocode le lieu (API gratuite du gouvernement, sans clé) puis on utilise la
recherche géographique d'Algolia (`aroundLatLng` + rayon).
"""
import unicodedata
from datetime import datetime

from curl_cffi import requests

_APP = "CSEKHVMS53"
_CLE = "4bd8f6215d0cc52b26430765769e65a0"  # clé de recherche publique du front WTTJ
_URL = f"https://{_APP.lower()}-dsn.algolia.net/1/indexes/wk_cms_jobs_production/query"
_ENTETES = {
    "x-algolia-application-id": _APP,
    "x-algolia-api-key": _CLE,
    "Referer": "https://www.welcometothejungle.com/",
    "Origin": "https://www.welcometothejungle.com",
    "Content-Type": "application/json",
}
_GEO = "https://api-adresse.data.gouv.fr/search/"
BASE = "https://www.welcometothejungle.com"

# WTTJ code le type de contrat en anglais ; on le ramène aux libellés utilisés
# ailleurs dans l'outil (comme HelloWork/Indeed).
_CONTRATS = {
    "FULL_TIME": "CDI",
    "PART_TIME": "CDI",
    "TEMPORARY": "CDD",
    "INTERNSHIP": "Stage",
    "APPRENTICESHIP": "Alternance",
    "FREELANCE": "Indépendant",
    "VIE": "VIE",
}


def _norm(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c)).lower()


def _coords(lieu):
    """(lat, lng) du lieu via l'API Adresse (gratuite, sans clé), ou None."""
    lieu = (lieu or "").strip()
    if not lieu:
        return None
    try:
        r = requests.get(_GEO, params={"q": lieu, "limit": 1}, timeout=15)
        feats = r.json().get("features") or []
        if feats:
            lng, lat = feats[0]["geometry"]["coordinates"]
            return lat, lng
    except Exception:
        pass
    return None


def _office(hit):
    return hit.get("office") or (hit.get("offices") or [{}])[0] or {}


def _lieu_texte(office):
    parts = [office.get("city"), office.get("district"), office.get("state")]
    return ", ".join(p for p in parts if p)


def _date(published_at):
    try:
        return datetime.fromisoformat(published_at).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return ""


def _salaire(hit):
    mn, mx = hit.get("salary_minimum"), hit.get("salary_maximum")
    if not mn and not mx:
        return ""
    periode = "/an" if (hit.get("salary_period") or "").lower() == "yearly" else ""
    devise = hit.get("salary_currency") or "EUR"
    montant = f"{mn}–{mx}" if (mn and mx) else str(mn or mx)
    return f"{montant} {devise}{periode}"


def rechercher_offres(poste, lieu="", pages=2, rayon_km=30, delai=0.0):
    """Retourne une liste d'offres
    [{titre, entreprise, lieu, contrat, salaire, date, url, source}]."""
    lieu_norm = _norm(lieu)
    coords = _coords(lieu) if lieu else None
    # Si le lieu n'a pas pu être géocodé, on filtrera côté client sur la ville.
    filtre_client = bool(lieu) and coords is None

    offres, vus = [], set()
    for page in range(pages):
        body = {
            "query": poste or "",
            "hitsPerPage": 40 if filtre_client else 30,
            "page": page,
            "filters": "website.reference:wttj_fr",
        }
        if coords:
            body["aroundLatLng"] = f"{coords[0]},{coords[1]}"
            body["aroundRadius"] = int(rayon_km) * 1000
        try:
            r = requests.post(_URL, headers=_ENTETES, json=body, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [WTTJ] page {page + 1} inaccessible : {e}")
            break

        hits = data.get("hits") or []
        if not hits:
            break
        for hit in hits:
            org = hit.get("organization") or {}
            slug, org_slug = hit.get("slug") or "", org.get("slug") or ""
            if not slug or not org_slug:
                continue
            url = f"{BASE}/fr/companies/{org_slug}/jobs/{slug}"
            if url in vus:
                continue
            office = _office(hit)
            if filtre_client and lieu_norm not in _norm(_lieu_texte(office)):
                continue
            vus.add(url)
            offres.append({
                "titre": (hit.get("name") or "").strip(),
                "entreprise": (org.get("name") or "").strip(),
                "lieu": _lieu_texte(office),
                "contrat": _CONTRATS.get(hit.get("contract_type") or "", ""),
                "salaire": _salaire(hit),
                "date": _date(hit.get("published_at")),
                "url": url,
                "source": "Welcome to the Jungle",
            })
        if page + 1 >= (data.get("nbPages") or 1):
            break
    return offres
