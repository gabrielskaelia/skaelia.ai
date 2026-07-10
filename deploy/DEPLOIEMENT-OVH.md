# Déploiement sur un serveur OVH (Ubuntu 24.04)

Objectif : faire tourner l'outil sur un VPS société (indépendant du PC de
Gabriel), avec croisia.me pointant dessus via le tunnel Cloudflare.

> ⚠️ **Avant de tout migrer** : tester que le scraping fonctionne depuis l'IP
> du VPS (voir étape 4). Les IP de datacenter sont parfois bloquées par
> HelloWork / Indeed / DuckDuckGo. Si c'est bloqué → prévoir un proxy résidentiel.

---

## 1. Commander le VPS

- OVH → **VPS**, le moins cher (2 Go RAM suffisent), **Ubuntu 24.04**.
- Récupérer l'**IP publique** et se connecter en SSH :
  ```bash
  ssh ubuntu@IP_DU_VPS      # ou root@IP_DU_VPS selon OVH
  ```

## 2. Préparer le système

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3 python3-venv python3-pip git
# Utilisateur dédié
sudo useradd -m -s /bin/bash skaelia || true
sudo mkdir -p /opt/skaelia && sudo chown skaelia:skaelia /opt/skaelia
```

## 3. Installer l'application

```bash
sudo -u skaelia -H bash
cd /opt/skaelia
git clone https://github.com/gabrielskaelia/skaelia.ai .
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Créer la config à partir de l'exemple, puis coller les clés
cp config.example.json config.json
nano config.json     # remplir usebouncer, smtp, nicoka, google, (fullenrich)…
exit
```

## 4. TESTER LE SCRAPING depuis le VPS (étape clé)

```bash
sudo -u skaelia /opt/skaelia/.venv/bin/python - <<'PY'
from curl_cffi import requests
for nom, url in [("HelloWork","https://www.hellowork.com/fr-fr/emploi/recherche.html?k=commercial&l=Nantes+44"),
                 ("Indeed","https://fr.indeed.com/jobs?q=commercial&l=Nantes")]:
    try:
        r = requests.get(url, impersonate="chrome", timeout=25)
        print(nom, r.status_code, len(r.text), "chars")
    except Exception as e:
        print(nom, "ERREUR", e)
from ddgs import DDGS
try:
    n = len(DDGS().text('site:linkedin.com/in "Skaelia"', max_results=3) or [])
    print("DuckDuckGo:", n, "résultats")
except Exception as e:
    print("DuckDuckGo ERREUR", e)
PY
```

- **HelloWork/Indeed 200 + beaucoup de caractères, DuckDuckGo > 0** → tout va bien, continuer.
- **403 / 0 résultat / blocage** → me prévenir : on branche un proxy résidentiel
  (ex. via une variable de proxy dans les requêtes).

## 5. Déplacer le tunnel Cloudflare sur le VPS

Depuis le PC de Gabriel, copier les identifiants du tunnel existant :
`~/.cloudflared/*.json`, `~/.cloudflared/cert.pem`, `~/.cloudflared/config.yml`
vers `/opt/skaelia/.cloudflared/` sur le VPS (via `scp`). Puis sur le VPS :

```bash
# Installer cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
sudo install /tmp/cloudflared /usr/local/bin/cloudflared
# Adapter le chemin credentials-file dans /opt/skaelia/.cloudflared/config.yml
#   -> /opt/skaelia/.cloudflared/<TUNNEL_ID>.json
```

(Alternative : recréer un tunnel propre au nom de l'entreprise avec
`cloudflared tunnel login` puis `cloudflared tunnel create`.)

## 6. Services systemd (démarrage automatique)

```bash
sudo cp /opt/skaelia/deploy/skaelia-app.service /etc/systemd/system/
sudo cp /opt/skaelia/deploy/skaelia-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now skaelia-app skaelia-tunnel
sudo systemctl status skaelia-app skaelia-tunnel
```

L'app tourne (127.0.0.1:5173) et le tunnel expose croisia.me. Le VPS redémarre ?
Tout repart tout seul.

## 7. Vérifier

```bash
curl -I https://croisia.me/connexion      # doit répondre 200/302 via cloudflare
```

## Mises à jour futures

```bash
cd /opt/skaelia && sudo -u skaelia git pull
sudo -u skaelia .venv/bin/pip install -r requirements.txt
sudo systemctl restart skaelia-app
```

## Données à conserver

`config.json`, `data/` (comptes, contacts, Nicoka, historique) et `resultats/`
restent sur le VPS et ne sont pas versionnés. Prévoir une sauvegarde régulière
de `data/` (contacts sauvegardés, comptes).
