# =====================================================================
#  Skaelia — Diagnostic : Indeed marche-t-il depuis le serveur ?
# ---------------------------------------------------------------------
#  Se connecte au serveur et tente une vraie recherche Indeed avec le
#  code de l'application. Affiche le nombre d'offres trouvees, ou
#  l'erreur exacte si Indeed bloque l'IP du serveur.
#  Ne modifie RIEN : lecture seule.
# =====================================================================

$ErrorActionPreference = "Stop"
$serveur = "164.132.109.33"

Write-Host ""
Write-Host "=== Diagnostic Indeed depuis le serveur ===" -ForegroundColor Cyan
$utilisateur = Read-Host "Ton identifiant de connexion au serveur"
$cible = "$utilisateur@$serveur"

$distant = @'
APP=/opt/skaelia
OWNER=$(stat -c "%U" "$APP/server.py")
cd "$APP" || exit 1
sudo -u "$OWNER" .venv/bin/python - <<PYEOF
import sys
sys.path.insert(0, ".")
print("== Test 1 : acces brut a fr.indeed.com ==")
try:
    from curl_cffi import requests
    r = requests.get("https://fr.indeed.com/jobs?q=commercial&l=Nantes",
                     impersonate="chrome", timeout=25)
    print("   statut HTTP :", r.status_code, "-", len(r.text), "caracteres")
    if "mosaic-provider-jobcards" in r.text:
        print("   donnees offres PRESENTES : Indeed repond normalement")
    elif "cf-" in r.text.lower() or "challenge" in r.text.lower() or r.status_code == 403:
        print("   BLOCAGE Cloudflare detecte : IP du serveur refusee par Indeed")
    else:
        print("   page inhabituelle : blocage probable")
except Exception as e:
    print("   ERREUR :", e)

print("== Test 2 : recherche complete avec le code de l application ==")
try:
    from prospection.jobs_indeed import rechercher_offres
    offres = rechercher_offres("commercial", "Nantes", pages=1)
    print("   offres trouvees :", len(offres))
    for o in offres[:3]:
        print("   -", o["titre"], "|", o["entreprise"])
except Exception as e:
    print("   ERREUR :", e)
PYEOF
'@

$bytes = [System.Text.Encoding]::UTF8.GetBytes($distant)
$b64   = [System.Convert]::ToBase64String($bytes)

Write-Host ""
Write-Host "=== Connexion (tape ton mot de passe serveur) ===" -ForegroundColor Cyan
ssh -t $cible "echo $b64 | base64 -d | bash"

Write-Host ""
Read-Host "Copie-colle le resultat a Claude, puis appuie sur Entree pour fermer"
