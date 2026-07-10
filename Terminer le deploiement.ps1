# =====================================================================
#  Skaelia — Terminer le deploiement (correctif + droits historique)
# ---------------------------------------------------------------------
#  Tes fichiers d'historique sont deja sur le serveur. Ce script :
#    - repare les droits de l'historique (detecte tout seul le bon
#      utilisateur, sans supposer qu'il s'appelle "skaelia")
#    - recupere le correctif du bouton (git pull)
#    - redemarre le site (detecte tout seul le nom du service)
#
#  Il te demandera ton identifiant serveur puis ton mot de passe.
# =====================================================================

$ErrorActionPreference = "Stop"
$serveur = "164.132.109.33"

Write-Host ""
Write-Host "=== Skaelia : fin du deploiement ===" -ForegroundColor Cyan
$utilisateur = Read-Host "Ton identifiant de connexion au serveur (le meme que tout a l'heure)"
$cible = "$utilisateur@$serveur"

# Script execute SUR le serveur (detecte l'utilisateur et le service tout seul).
# NB : on garde des commentaires SANS apostrophe ni parenthese par prudence.
$distant = @'
APP=/opt/skaelia
SLUG=gabriel-praud-skaelia-com-b27bb57d
DEST="$APP/resultats/$SLUG"

if [ ! -f "$APP/server.py" ]; then
  echo "!! Application absente de /opt/skaelia - a verifier."
  exit 1
fi

OWNER=$(stat -c "%U" "$APP/server.py")
echo "== Utilisateur application detecte : $OWNER =="

# Etape 1 - droits historique, non bloquant
sudo chown -R "$OWNER":"$OWNER" "$DEST" 2>/dev/null || sudo chown -R "$OWNER" "$DEST" 2>/dev/null || true
echo "== Historique present sur le serveur : =="
ls -1 "$DEST" 2>/dev/null || echo "dossier vide ou absent"

# Etape 2 - correctif
echo "== git pull =="
cd "$APP" || exit 1
sudo -u "$OWNER" git pull

# Etape 3 - redemarrage service
SVC=$(grep -rl "$APP" /etc/systemd/system/*.service 2>/dev/null | head -1)
if [ -n "$SVC" ]; then
  SVC=$(basename "$SVC")
  echo "== Redemarrage service : $SVC =="
  sudo systemctl restart "$SVC"
  sleep 1
  printf "== Etat service : "; systemctl is-active "$SVC"
else
  echo "!! Service systemd introuvable. Candidats :"
  systemctl list-units --type=service --all | grep -iE "skael|prospect" || echo "aucun"
fi
echo "== Termine cote serveur =="
'@

# Transport blinde : on encode le script en base64 pour qu'aucun guillemet ni
# apostrophe ne soit abime en chemin ; le serveur le decode puis l'execute.
$bytes = [System.Text.Encoding]::UTF8.GetBytes($distant)
$b64   = [System.Convert]::ToBase64String($bytes)

Write-Host ""
Write-Host "=== Connexion + deploiement (tape ton mot de passe serveur) ===" -ForegroundColor Cyan
ssh -t $cible "echo $b64 | base64 -d | bash"
if ($LASTEXITCODE -ne 0) { throw "Le deploiement a echoue (voir les messages ci-dessus)." }

Write-Host ""
Write-Host "=== C'est en ligne ! ===" -ForegroundColor Green
Write-Host "Ouvre https://ai.skaelia.com, connecte-toi, et verifie :"
Write-Host "  - le bouton 'Lancer la prospection' fonctionne"
Write-Host "  - ton historique de recherches apparait"
Write-Host ""
Read-Host "Appuie sur Entree pour fermer"
