# =====================================================================
#  Skaelia — Mise en ligne du correctif + import de l'historique
# ---------------------------------------------------------------------
#  Ce script se connecte a ton serveur (ai.skaelia.com) et fait 3 choses :
#    1. Envoie tes fichiers d'historique de recherche vers le serveur
#    2. Les range dans le bon dossier (avec les bons droits)
#    3. Recupere le correctif du bouton + redemarre le site
#
#  Il te demandera :
#    - ton identifiant de connexion au serveur (ex : root ou ubuntu)
#    - ton mot de passe serveur (a taper 2 fois, quand SSH le demande)
# =====================================================================

$ErrorActionPreference = "Stop"
$serveur = "164.132.109.33"
$slug    = "gabriel-praud-skaelia-com-b27bb57d"
$local   = Join-Path $PSScriptRoot "resultats\$slug"

Write-Host ""
Write-Host "=== Skaelia : mise en ligne + import historique ===" -ForegroundColor Cyan
Write-Host ""

# --- Verification des fichiers a envoyer ---
$fichiers = Get-ChildItem -Path $local -Filter "prospection_*.xlsx" -ErrorAction SilentlyContinue
if (-not $fichiers) {
    Write-Host "Aucun fichier d'historique trouve dans :" -ForegroundColor Yellow
    Write-Host "  $local"
    Write-Host "Rien a importer. Le script continue quand meme pour le deploiement."
} else {
    Write-Host ("{0} recherche(s) a importer :" -f $fichiers.Count) -ForegroundColor Green
    $fichiers | ForEach-Object { Write-Host ("   - " + $_.Name) }
}
Write-Host ""

# --- Identifiant de connexion ---
$utilisateur = Read-Host "Ton identifiant de connexion au serveur (ex : root ou ubuntu)"
$cible = "$utilisateur@$serveur"
$dossierServeur = "/opt/skaelia/resultats/$slug"

# --- 1. Envoi de l'historique ---
if ($fichiers) {
    Write-Host ""
    Write-Host "=== 1/3  Envoi de ton historique (tape ton mot de passe serveur) ===" -ForegroundColor Cyan
    scp "$local\*.xlsx" "${cible}:/tmp/"
    if ($LASTEXITCODE -ne 0) { throw "L'envoi des fichiers a echoue." }
}

# --- 2. Rangement + 3. Deploiement, en une seule connexion ---
Write-Host ""
Write-Host "=== 2/3 + 3/3  Rangement + deploiement du correctif (mot de passe serveur) ===" -ForegroundColor Cyan
$commandesDistantes = @(
    "sudo mkdir -p $dossierServeur",
    "if ls /tmp/prospection_*.xlsx >/dev/null 2>&1; then sudo mv /tmp/prospection_*.xlsx $dossierServeur/; fi",
    "sudo chown -R skaelia:skaelia $dossierServeur",
    "cd /opt/skaelia && sudo -u skaelia git pull",
    "sudo systemctl restart skaelia-app",
    "echo '--- Historique present sur le serveur ---'",
    "ls -1 $dossierServeur"
) -join " && "

ssh -t $cible $commandesDistantes
if ($LASTEXITCODE -ne 0) { throw "Le deploiement sur le serveur a echoue." }

Write-Host ""
Write-Host "=== Termine ! ===" -ForegroundColor Green
Write-Host "Ouvre https://ai.skaelia.com et connecte-toi : le bouton doit marcher"
Write-Host "et ton historique de recherches doit apparaitre."
Write-Host ""
Read-Host "Appuie sur Entree pour fermer"
