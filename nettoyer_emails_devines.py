# -*- coding: utf-8 -*-
"""Nettoyage ponctuel : retire les emails/téléphones DEVINÉS des contacts
sauvegardés (data/mes_contacts.json).

Une ancienne version de l'outil générait des emails « au pif » par format
(prenom.nom@domaine). Désormais, email et téléphone ne sont renseignés QUE via
« Prendre contact manuellement » (enrichissement FullEnrich à la demande).

Ce script vide email / statut_email / téléphone pour les contacts qui ne sont
NI issus de Nicoka (données réelles du CRM) NI enrichis via FullEnrich
(`enrichissement == "fait"`). Il est sûr à relancer plusieurs fois.

Usage :  python nettoyer_emails_devines.py
"""
import json
from pathlib import Path

FICHIER = Path(__file__).parent / "data" / "mes_contacts.json"


def main():
    if not FICHIER.exists():
        print("Aucun fichier de contacts (data/mes_contacts.json) — rien à faire.")
        return
    donnees = json.loads(FICHIER.read_text(encoding="utf-8"))
    nettoyes = 0
    for contacts in donnees.values():
        for c in contacts:
            # On CONSERVE les coordonnées réelles / vérifiées :
            #   - contacts Nicoka (CRM),
            #   - enrichis via FullEnrich (email/tél ou l'ancien flag global),
            #   - emails déjà VÉRIFIÉS (statut délivrable / incertain).
            verifie = (
                c.get("source_contact") == "nicoka"
                or c.get("enrichissement") == "fait"
                or c.get("email_recherche") == "fait"
                or c.get("tel_recherche") == "fait"
                or c.get("statut_email") in ("deliverable", "risky")
            )
            if verifie:
                continue
            if c.get("email") or c.get("telephone"):
                c["email"] = ""
                c["statut_email"] = ""
                c["telephone"] = ""
                nettoyes += 1
    FICHIER.write_text(json.dumps(donnees, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    print(f"{nettoyes} contact(s) nettoyé(s) : emails/téléphones devinés retirés.")


if __name__ == "__main__":
    main()
