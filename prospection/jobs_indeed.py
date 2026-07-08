# -*- coding: utf-8 -*-
"""Collecte des offres d'emploi sur Indeed (fr.indeed.com).

Les données sont extraites du JSON embarqué dans la page de résultats
(window.mosaic.providerData["mosaic-provider-jobcards"]).
"""
import json
import re
import time
from urllib.parse import quote

from curl_cffi import requests

BASE = "https://fr.indeed.com"
_RE_MOSAIC = re.compile(
    r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});',
    re.S,
)


def _get(url):
    r = requests.get(url, impersonate="chrome", timeout=30)
    r.raise_for_status()
    return r.text


def rechercher_offres(poste, lieu="", pages=2, anciennete_jours=14, delai=3.0):
    """Retourne une liste d'offres [{titre, entreprise, lieu, contrat, url, source}]."""
    offres = []
    for page in range(pages):
        url = f"{BASE}/jobs?q={quote(poste)}&sort=date"
        if lieu:
            url += f"&l={quote(lieu)}"
        if anciennete_jours:
            url += f"&fromage={anciennete_jours}"
        if page > 0:
            url += f"&start={page * 10}"
        try:
            html = _get(url)
        except Exception as e:
            print(f"  [Indeed] page {page + 1} inaccessible : {e}")
            break

        m = _RE_MOSAIC.search(html)
        if not m:
            print(f"  [Indeed] page {page + 1} : données introuvables (blocage possible)")
            break
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            break

        resultats = (
            data.get("metaData", {})
            .get("mosaicProviderJobCardsModel", {})
            .get("results", [])
        )
        if not resultats:
            break

        for r in resultats:
            salaire = ""
            snippet = r.get("salarySnippet") or {}
            if snippet.get("text"):
                salaire = snippet["text"]
            offres.append({
                "titre": r.get("title", ""),
                "entreprise": r.get("company", ""),
                "lieu": r.get("formattedLocation", ""),
                "contrat": ", ".join(r.get("jobTypes") or []),
                "salaire": salaire,
                "date": r.get("formattedRelativeTime", ""),
                "url": f"{BASE}/viewjob?jk={r.get('jobkey', '')}",
                "source": "Indeed",
            })

        if page < pages - 1:
            time.sleep(delai)
    return offres
