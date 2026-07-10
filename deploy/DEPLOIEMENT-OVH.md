# Déploiement sur un serveur OVH — ai.skaelia.com

Objectif : faire tourner l'outil sur un VPS société (indépendant du PC de
Gabriel), accessible en permanence sur **https://ai.skaelia.com**.

Architecture (simple, tout chez OVH) :

```
Ton PC (tu codes)  ──git push──►  GitHub  ──git pull──►  VPS OVH
                                                          │
   ai.skaelia.com ──DNS OVH──► IP du VPS ──► Caddy (HTTPS) ──► app Flask (localhost:5173)
```

Pas de tunnel Cloudflare : le VPS a une vraie IP publique, donc on pointe
`ai.skaelia.com` directement dessus et **Caddy** gère le certificat HTTPS
automatiquement (Let's Encrypt).

> ⚠️ **Avant de tout migrer** : tester que le scraping fonctionne depuis l'IP
> du VPS (étape 4). Les IP de datacenter sont parfois bloquées par
> HelloWork / Indeed / DuckDuckGo. Si c'est bloqué → prévoir un proxy résidentiel.

---

## 1. Commander le VPS

- OVH → **VPS**, le moins cher (2 Go RAM suffisent), **Ubuntu 24.04**.
- Récupérer l'**IP publique** (ex. `51.75.xx.xx`) et se connecter en SSH :
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

- **HelloWork/Indeed 200 + beaucoup de caractères, DuckDuckGo > 0** → tout va bien.
- **403 / 0 résultat / blocage** → me prévenir : on branche un proxy résidentiel.

## 5. Pointer ai.skaelia.com vers le VPS (DNS OVH)

Dans l'espace client OVH → **Noms de domaine → skaelia.com → Zone DNS** →
**Ajouter une entrée** :

| Type | Sous-domaine | Cible          |
|------|--------------|----------------|
| A    | `ai`         | `IP_DU_VPS`    |

C'est **la seule** ligne à ajouter. **Ne touche à rien d'autre** — surtout pas
les entrées **MX / TXT** (elles font marcher les emails Google Workspace de
`@skaelia.com`). La propagation prend de quelques minutes à ~1 h.

Vérifier depuis ton PC : `nslookup ai.skaelia.com` doit renvoyer l'IP du VPS.

## 6. Installer Caddy (HTTPS automatique)

Sur le VPS :

```bash
sudo apt -y install debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt -y install caddy
```

Puis remplacer le contenu de `/etc/caddy/Caddyfile` par (voir aussi
`deploy/Caddyfile` dans le dépôt) :

```
ai.skaelia.com {
    reverse_proxy 127.0.0.1:5173
}
```

```bash
sudo cp /opt/skaelia/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Caddy obtient tout seul le certificat Let's Encrypt pour `ai.skaelia.com`.
(Le port 80 et 443 doivent être ouverts — c'est le cas par défaut sur un VPS OVH ;
si un pare-feu `ufw` est actif : `sudo ufw allow 80,443/tcp`.)

## 7. Lancer l'app au démarrage (systemd)

```bash
sudo cp /opt/skaelia/deploy/skaelia-app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now skaelia-app
sudo systemctl status skaelia-app
```

L'app tourne sur `127.0.0.1:5173`, Caddy l'expose en HTTPS sur `ai.skaelia.com`.
Le VPS redémarre ? App + Caddy repartent tout seuls.

## 8. Google OAuth (login Google)

Dans **Google Cloud Console → Credentials → client OAuth → Authorized redirect
URIs**, ajouter :

```
https://ai.skaelia.com/connexion/google/callback
```

(retirer les anciennes lignes croisia.me).

## 9. Vérifier

```bash
curl -I https://ai.skaelia.com/connexion      # doit répondre 200/302 en HTTPS
```

Puis dans le navigateur : https://ai.skaelia.com

## 10. Extension Chrome

Le `manifest.json` cible désormais `ai.skaelia.com`. Dans Chrome →
`chrome://extensions` → recharger l'extension (↻).

---

## Mises à jour futures (ta question « je pourrai toujours push ? » → OUI)

Sur ton PC, tu codes puis :
```bash
git push
```
Puis sur le VPS :
```bash
cd /opt/skaelia && sudo -u skaelia git pull
sudo -u skaelia .venv/bin/pip install -r requirements.txt   # si requirements a changé
sudo systemctl restart skaelia-app
```

## Données à conserver

`config.json`, `data/` (comptes, contacts, Nicoka, historique) et `resultats/`
restent sur le VPS et ne sont pas versionnés. **Au départ**, copier le `data/`
de ton PC vers le VPS (`scp -r data ubuntu@IP_DU_VPS:/tmp/` puis le déplacer dans
`/opt/skaelia/data` avec les bons droits). Prévoir une sauvegarde régulière de
`data/`.
