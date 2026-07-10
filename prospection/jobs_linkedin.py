# -*- coding: utf-8 -*-
"""Collecte des offres d'emploi sur LinkedIn via l'API publique « guest »
(pas de compte requis) : /jobs-guest/jobs/api/seeMoreJobPostings/search.
Renvoie des cartes HTML (titre, société, lieu, lien, date)."""
import re
import time
from datetime import datetime
from urllib.parse import quote

from curl_cffi import requests

BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def _get(url):
    r = requests.get(url, impersonate="chrome", timeout=30)
    r.raise_for_status()
    return r.text


def _extr(motif, texte):
    m = re.search(motif, texte, re.S)
    return m.group(1).strip() if m else ""


def _date_relative(iso):
    """'2025-06-23' -> 'il y a X jours'."""
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    j = (datetime.now() - d).days
    if j <= 0:
        return "aujourd'hui"
    if j == 1:
        return "il y a 1 jour"
    return f"il y a {j} jours"


def rechercher_offres(poste, lieu="", pages=2, delai=2.0):
    """Retourne une liste d'offres [{titre, entreprise, lieu, contrat, salaire,
    date, url, source}]."""
    offres = []
    vus = set()
    for page in range(pages):
        url = f"{BASE}?keywords={quote(poste)}&start={page * 25}"
        if lieu:
            url += f"&location={quote(lieu)}"
        try:
            html = _get(url)
        except Exception as e:
            print(f"  [LinkedIn] page {page + 1} inaccessible : {e}")
            break

        cartes = re.findall(r"<li>.*?</li>", html, re.S)
        if not cartes:
            break

        nouveau = 0
        for c in cartes:
            titre = _extr(r'base-search-card__title">\s*([^<]+)', c)
            societe = (_extr(r'base-search-card__subtitle">\s*<a[^>]*>\s*([^<]+)', c)
                       or _extr(r'hidden-nested-link[^>]*>\s*([^<]+)', c))
            lieu_ = _extr(r'job-search-card__location">\s*([^<]+)', c)
            lien = _extr(r'href="(https://[a-z]+\.linkedin\.com/jobs/view/[^"?]+)', c)
            date = _extr(r'datetime="([^"]+)"', c)
            if not titre or not lien or lien in vus:
                continue
            vus.add(lien)
            offres.append({
                "titre": titre,
                "entreprise": societe,
                "lieu": lieu_,
                "contrat": "",
                "salaire": "",
                "date": _date_relative(date),
                "url": lien,
                "source": "LinkedIn",
            })
            nouveau += 1

        if nouveau == 0:
            break
        if page < pages - 1:
            time.sleep(delai)
    return offres
