# Automatisation prospection — cabinet de recrutement

Pipeline qui détecte les entreprises en train de recruter et identifie les
décideurs à contacter :

1. **Collecte des offres** publiées sur **HelloWork** et **Indeed** pour un
   poste et un lieu donnés.
2. **Consolidation des entreprises** : déduplication et exclusion automatique
   des cabinets de recrutement / agences d'intérim (concurrents).
3. **Recherche des décideurs** : profils LinkedIn (Talent Acquisition, RH,
   direction) trouvés par recherche web ciblée `site:linkedin.com/in` —
   sans scraper LinkedIn directement, donc sans risque pour un compte.
4. **Emails** : détection du domaine de l'entreprise, génération des formats
   probables (`prenom.nom@…`) et vérification via **UseBouncer** (si clé API
   renseignée).
5. **Export Excel** : un classeur à 3 onglets (Offres / Entreprises /
   Contacts) avec liens cliquables et filtres.

## Utilisation — interface web (recommandé)

Double-cliquer sur **`Lancer la prospection.bat`** : le serveur démarre et le
navigateur s'ouvre sur <http://localhost:5173>.

- **Recherche simple** : un poste + un lieu (facultatif), bouton Rechercher.
- **Résultats centrés contacts** : chaque ligne relie le décideur (nom, poste,
  profil LinkedIn, email) à son entreprise et aux offres qu'elle publie en ce
  moment (liens cliquables vers HelloWork/Indeed).
- **Nouveautés** : à partir de la 2ᵉ exécution d'une même recherche, les
  offres jamais vues sont marquées « NOUVEAU » (historique dans
  `data/historique.json`).
- **Réglages** (en haut à droite) : clé API UseBouncer, cabinets concurrents
  exclus, et configuration SMTP pour l'envoi des emails de validation.
- Les fichiers Excel sont créés dans le dossier `resultats/`.

## Comptes et accès

L'outil est protégé par comptes :

1. Un nouvel utilisateur clique sur « Demander un accès » (nom + email).
2. Un email de validation part vers **gabriel.praud@skaelia.com** (administrateur).
3. Quand l'administrateur clique sur « Valider ce compte », l'utilisateur
   reçoit un email avec un lien pour **choisir son mot de passe**, puis accède
   à l'outil.
4. Une fois connecté : déconnexion et changement de mot de passe dans l'en-tête.

**Envoi des emails** : configurer le SMTP dans Réglages (pour Gmail/Google
Workspace : serveur `smtp.gmail.com`, port 587, et un « mot de passe
d'application » créé sur <https://myaccount.google.com/apppasswords>).
Tant que le SMTP n'est pas configuré, les liens de validation et de mot de
passe s'affichent à l'écran pour être transmis à la main — l'outil reste
utilisable.

Les comptes sont stockés dans `data/utilisateurs.json` (mots de passe hachés).

## Utilisation — ligne de commande

```powershell
python run.py --poste "développeur web" --lieu "Lyon"
python run.py --poste "comptable" --lieu "Rennes" --sans-contacts
```

## Configuration (`config.json`)

| Clé | Rôle |
|---|---|
| `recherches` | Liste de couples poste/lieu lancés par défaut |
| `pages_hellowork` / `pages_indeed` | Nombre de pages collectées par source (~30 et ~15 offres/page) |
| `anciennete_jours_indeed` | Ne garder que les offres Indeed récentes (jours) |
| `max_entreprises_a_prospecter` | Nombre d'entreprises pour lesquelles chercher des contacts |
| `contacts_max_par_role` | Nombre de profils gardés par famille de rôles |
| `usebouncer_api_key` | Clé API UseBouncer pour vérifier les emails (sinon : emails générés mais non vérifiés) |
| `roles_cibles` | Familles de décideurs recherchées (syntaxe moteur de recherche) |
| `exclusions_cabinets` | Cabinets / agences à exclure des prospects — à enrichir au fil de l'eau |

## Clé UseBouncer

1. Créer un compte sur <https://usebouncer.com> (100 vérifications gratuites).
2. Copier la clé API (Dashboard → API).
3. La coller dans `config.json` → `"usebouncer_api_key"`.

Statuts renvoyés : `deliverable` (adresse sûre), `risky` (incertaine),
`non vérifié` (pas de clé ou aucun format confirmé).

## Limites connues

- Indeed bloque parfois la 2ᵉ page de résultats ; la 1ʳᵉ passe presque
  toujours. Relancer plus tard si besoin.
- La recherche de contacts repose sur un moteur de recherche public : environ
  2 à 6 profils par entreprise, parfois aucun pour les petites structures.
- Les emails « non vérifiés » sont des déductions de format : à utiliser avec
  un outil de vérification avant tout envoi en masse.

## Installation

```powershell
winget install Python.Python.3.12
pip install -r requirements.txt
copy config.example.json config.json   # puis remplir les clés (SMTP, UseBouncer)
python server.py
```

`config.json`, `data/` (comptes, historique) et `resultats/` (fichiers Excel)
restent locaux et ne sont pas versionnés (voir `.gitignore`) : ils contiennent
des secrets et des données de prospection.
