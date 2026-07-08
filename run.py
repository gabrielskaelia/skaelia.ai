# -*- coding: utf-8 -*-
"""Pipeline de prospection : offres d'emploi -> entreprises -> décideurs -> emails -> Excel.

Usage :
    python run.py                                   # utilise config.json
    python run.py --poste "développeur" --lieu "Lyon"
    python run.py --sans-contacts                   # collecte seulement offres + entreprises
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from prospection import companies, emails, export_excel, jobs_hellowork, jobs_indeed, linkedin_contacts

RACINE = Path(__file__).parent


def charger_config():
    with open(RACINE / "config.json", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Prospection cabinet de recrutement")
    parser.add_argument("--poste", help="Poste recherché (sinon: config.json)")
    parser.add_argument("--lieu", default="", help="Ville / département")
    parser.add_argument("--sans-contacts", action="store_true",
                        help="Ne pas chercher les décideurs LinkedIn ni les emails")
    parser.add_argument("--sortie", default="", help="Chemin du fichier Excel de sortie")
    args = parser.parse_args()

    config = charger_config()
    recherches = [{"poste": args.poste, "lieu": args.lieu}] if args.poste else config["recherches"]
    api_key = config.get("usebouncer_api_key", "")

    # 1. Collecte des offres
    offres = []
    for rech in recherches:
        poste, lieu = rech["poste"], rech.get("lieu", "")
        print(f"\n=== Recherche : {poste} ({lieu or 'toute la France'}) ===")
        print("[1/4] Collecte HelloWork...")
        hw = jobs_hellowork.rechercher_offres(poste, lieu, pages=config.get("pages_hellowork", 2))
        print(f"      {len(hw)} offres")
        print("[1/4] Collecte Indeed...")
        ind = jobs_indeed.rechercher_offres(
            poste, lieu,
            pages=config.get("pages_indeed", 2),
            anciennete_jours=config.get("anciennete_jours_indeed", 14),
        )
        print(f"      {len(ind)} offres")
        offres.extend(hw + ind)

    if not offres:
        print("\nAucune offre collectée, arrêt.")
        return

    # 2. Consolidation des entreprises (hors cabinets concurrents)
    print(f"\n[2/4] Consolidation : {len(offres)} offres au total")
    entreprises = companies.consolider_entreprises(offres, config.get("exclusions_cabinets", []))
    print(f"      {len(entreprises)} entreprises uniques (cabinets/intérim exclus)")

    # 3. Décideurs + emails
    contacts = []
    if not args.sans_contacts:
        max_ent = config.get("max_entreprises_a_prospecter", 15)
        cibles = entreprises[:max_ent]
        print(f"\n[3/4] Recherche des décideurs pour {len(cibles)} entreprises "
              f"(les {max_ent} avec le plus d'offres)...")
        if not api_key:
            print("      (pas de clé UseBouncer dans config.json : les emails seront "
                  "générés mais non vérifiés)")
        for i, ent in enumerate(cibles, 1):
            nom_ent = ent["entreprise"]
            print(f"  [{i}/{len(cibles)}] {nom_ent}")
            trouves = linkedin_contacts.chercher_contacts(
                nom_ent,
                roles=config.get("roles_cibles"),
                max_par_role=config.get("contacts_max_par_role", 2),
            )
            print(f"        {len(trouves)} profil(s) LinkedIn")
            if trouves:
                domaine = emails.trouver_domaine(nom_ent)
                ent["domaine"] = domaine
                if domaine:
                    print(f"        domaine : {domaine}")
                for contact in trouves:
                    email, statut = emails.meilleur_email(contact["nom"], domaine, api_key)
                    contact["email"] = email
                    contact["statut_email"] = statut
            contacts.extend(trouves)
    else:
        print("\n[3/4] Recherche de contacts désactivée (--sans-contacts)")

    # 4. Export Excel
    nom_fichier = args.sortie or str(RACINE / f"prospection_{date.today().isoformat()}.xlsx")
    export_excel.exporter(nom_fichier, offres, entreprises, contacts)
    print(f"\n[4/4] Terminé : {len(offres)} offres, {len(entreprises)} entreprises, "
          f"{len(contacts)} contacts")
    print(f"      Fichier : {nom_fichier}")


if __name__ == "__main__":
    main()
