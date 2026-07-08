# -*- coding: utf-8 -*-
"""Collecte des offres d'emploi sur HelloWork."""
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi import requests

BASE = "https://www.hellowork.com"


def _get(url):
    r = requests.get(url, impersonate="chrome", timeout=30)
    r.raise_for_status()
    return r.text


def rechercher_offres(poste, lieu="", pages=2, delai=2.0):
    """Retourne une liste d'offres [{titre, entreprise, lieu, contrat, url, source}]."""
    offres = []
    for page in range(1, pages + 1):
        url = f"{BASE}/fr-fr/emploi/recherche.html?k={quote(poste)}"
        if lieu:
            url += f"&l={quote(lieu)}"
        if page > 1:
            url += f"&p={page}"
        try:
            html = _get(url)
        except Exception as e:
            print(f"  [HelloWork] page {page} inaccessible : {e}")
            break

        soup = BeautifulSoup(html, "lxml")
        cartes = soup.select('[data-cy="serpCard"]')
        if not cartes:
            break

        for carte in cartes:
            lien = carte.select_one('[data-cy="offerTitle"]')
            if not lien:
                continue
            # title = "Commercial H/F - Kooi Security France"
            titre_complet = lien.get("title", "")
            href = lien.get("href", "")
            paragraphes = lien.select("h3 p")
            if len(paragraphes) >= 2:
                titre = paragraphes[0].get_text(strip=True)
                entreprise = paragraphes[1].get_text(strip=True)
            elif " - " in titre_complet:
                titre, entreprise = titre_complet.rsplit(" - ", 1)
            else:
                titre, entreprise = titre_complet, ""

            loc = carte.select_one('[data-cy="localisationCard"]')
            contrat = carte.select_one('[data-cy="contractCard"]')

            # Date de publication : "il y a 4 jours", "il y a 23 heures"...
            # (dans la carte ou son conteneur parent)
            date = ""
            for zone in (carte, carte.parent):
                if zone is None:
                    continue
                m = re.search(r"(il y a\s+[^<\n]{1,30}?|aujourd'hui|hier)\s*<",
                              str(zone), re.I)
                if m:
                    date = m.group(1).strip()
                    break

            offres.append({
                "titre": titre.strip(),
                "entreprise": entreprise.strip(),
                "lieu": loc.get_text(strip=True) if loc else "",
                "contrat": contrat.get_text(strip=True) if contrat else "",
                "salaire": "",
                "date": date,
                "url": BASE + href if href.startswith("/") else href,
                "source": "HelloWork",
            })

        if page < pages:
            time.sleep(delai)
    return offres
