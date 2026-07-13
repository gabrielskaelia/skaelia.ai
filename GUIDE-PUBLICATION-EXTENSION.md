# Publier l'extension sur le Chrome Web Store — guide pas à pas

Objectif : que tes collègues installent l'extension **en un clic** (lien
« Ajouter à Chrome ») et qu'elle se mette à jour **toute seule**.

Tout est déjà préparé. Tu n'as qu'à suivre les étapes et copier-coller les
textes fournis.

## Ce qui est prêt (dans ton dossier de prospection)

| Fichier | À quoi ça sert |
|---|---|
| `extension-skaelia-store.zip` | **Le paquet à envoyer** à Google |
| `extension-skaelia-store-capture.png` | La capture d'écran (1280×800) demandée |
| Icône | Déjà incluse dans le zip (le « S » bleu) |
| Page confidentialité | En ligne : `https://ai.skaelia.com/confidentialite-extension` |

> ⚠️ La page de confidentialité doit être **en ligne** avant de soumettre :
> déploie le site d'abord (`Terminer le deploiement.ps1`), puis vérifie que
> `https://ai.skaelia.com/confidentialite-extension` s'ouvre bien.

---

## Étape 1 — Créer le compte développeur (5 $, une fois)

1. Va sur **https://chrome.google.com/webstore/devconsole**
2. Connecte-toi avec **gabriel.praud@skaelia.com**
3. Accepte les conditions et paie les **5 $ d'inscription** (carte bancaire, une seule fois pour toujours)

## Étape 2 — Créer l'élément et envoyer le zip

1. Clique **« + Nouvel élément »**
2. Envoie le fichier **`extension-skaelia-store.zip`**
3. Une fois analysé, tu arrives sur la fiche à remplir.

## Étape 3 — Remplir la fiche (« Store listing »)

- **Description courte** (à coller) :
  ```
  Envoie tes messages LinkedIn en un clic depuis l'outil de prospection Skaelia. Tout se passe dans ton navigateur.
  ```

- **Description détaillée** (à coller) :
  ```
  Extension interne au cabinet de recrutement Skaelia.

  Depuis l'application de prospection ai.skaelia.com, elle permet d'envoyer un
  message LinkedIn en un clic, dans votre propre session LinkedIn : l'extension
  ouvre le profil, écrit le message que vous avez préparé et l'envoie.

  Elle affiche aussi, dans l'application, si vous êtes connecté à LinkedIn et
  avec quel compte.

  Confidentialité : l'extension n'agit que sur ai.skaelia.com et linkedin.com,
  et n'envoie aucune donnée à un tiers. Tout se passe dans votre navigateur.
  ```

- **Catégorie** : « Workflow et planification » (ou « Productivité »)
- **Langue** : Français
- **Capture d'écran** : envoie `extension-skaelia-store-capture.png`
- **Icône** : déjà dans le zip, rien à faire.

## Étape 4 — Confidentialité (« Privacy »)

C'est l'onglet le plus important pour la validation. À remplir ainsi :

- **Objectif unique (single purpose)** — à coller :
  ```
  Envoyer, depuis l'application Skaelia (ai.skaelia.com), des messages dans la session LinkedIn de l'utilisateur, et afficher l'état de connexion LinkedIn.
  ```

- **Justification des autorisations** (une par ligne demandée) :
  - `cookies` :
    ```
    Détecter si l'utilisateur est connecté à LinkedIn (cookie de session) et afficher le nom de son compte dans l'application.
    ```
  - `storage` :
    ```
    Mémoriser temporairement l'envoi en cours pendant les changements de page LinkedIn.
    ```
  - Accès au site `linkedin.com` :
    ```
    Ouvrir la messagerie et envoyer le message sur LinkedIn.
    ```
  - Accès au site `ai.skaelia.com` :
    ```
    Recevoir les demandes d'envoi depuis l'application de prospection.
    ```

- **Code à distance (remote code)** : répondre **Non**, l'extension n'exécute aucun code externe.

- **Utilisation des données** : coche que l'extension **ne collecte pas** de
  données personnelles pour les revendre/partager. Puis coche les trois
  attestations en bas (ne pas vendre, usage conforme à l'objectif unique, etc.).

- **URL de la politique de confidentialité** (à coller) :
  ```
  https://ai.skaelia.com/confidentialite-extension
  ```

## Étape 5 — Visibilité

Pour un outil interne, choisis **« Non répertoriée » (Unlisted)** :
- l'extension n'apparaît PAS dans les recherches publiques du store ;
- seuls les gens à qui tu donnes le lien peuvent l'installer.

(Tu peux passer en « Public » plus tard si tu veux.)

## Étape 6 — Envoyer pour validation

Clique **« Envoyer pour examen »**. Google vérifie (souvent quelques heures à
2-3 jours). Tu reçois un email quand c'est validé.

## Après validation

- Tu obtiens un lien du type `https://chrome.google.com/webstore/detail/xxxx`.
- Partage-le à tes collègues : ils cliquent **« Ajouter à Chrome »**, et c'est
  installé. Plus de mode développeur, plus de rechargement manuel.
- Les futures mises à jour se déploieront automatiquement chez tout le monde.

---

## Plus tard : modifier l'extension (oui, à volonté)

Quand on améliore l'extension :
1. On modifie le code (comme d'habitude)
2. On augmente le numéro de version dans `manifest.json`
3. On regénère le zip
4. Sur le dashboard : « Package » → « Importer un nouveau package » → envoie le zip → « Envoyer pour examen »

Les 5 $ ne sont payés qu'une fois. Les mises à jour sont gratuites et illimitées.
