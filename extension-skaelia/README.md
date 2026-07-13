# Extension Skaelia — Envoi LinkedIn

Cette petite extension Chrome permet, depuis l'outil de prospection
(ai.skaelia.com), d'envoyer un message **LinkedIn** en un clic dans ta propre
session LinkedIn.

> **Rappel :** l'extension ne sert QU'À LinkedIn. Pour les **emails**, rien à
> installer — il suffit de cliquer « Connecter son Gmail » sur le site.

## Installation (une seule fois, ~2 minutes)

1. Ouvre Chrome et va sur **`chrome://extensions`** (à taper dans la barre d'adresse)
2. En haut à droite, active le **« Mode développeur »**
3. Clique sur **« Charger l'extension non empaquetée »**
4. Sélectionne le dossier **`extension-skaelia`** (celui qui contient ce fichier)
5. La carte « Skaelia Prospection — Envoi LinkedIn » apparaît dans la liste.

**Vérification :** sur ai.skaelia.com → **Réglages** → la ligne **LinkedIn** doit
afficher **« connecté ✓ »** (recharge la page après l'installation). Si elle
affiche « extension à recharger », clique sur l'icône **↻** de la carte dans
`chrome://extensions`.

## Mettre à jour l'extension

Quand une nouvelle version est fournie : va sur `chrome://extensions` et clique
sur l'icône **↻** (recharger) de la carte Skaelia. Le numéro de version doit
changer. **C'est l'oubli le plus fréquent** quand « ça ne marche pas ».

## Utilisation

1. Sois **connecté à LinkedIn** dans le même navigateur.
2. Dans « Mes contacts » → **« Prendre contact »** → **« Envoyer sur LinkedIn → »**
   (ou « Tout prospecter »).
3. L'extension ouvre le profil, écrit le message pré-rédigé et l'**envoie**.

## Important

- Pour écrire à quelqu'un qui n'est **pas** dans tes relations (cas de la
  prospection), LinkedIn exige un abonnement **Premium / InMail**. Sans ça, il
  affiche « avec Premium » et l'extension le signalera.
- Reste raisonnable sur le volume : LinkedIn limite les messages par jour ; un
  envoi trop massif peut faire restreindre le compte.

## Pour éviter le « Mode développeur » à tes collègues (option)

L'installation ci-dessus fonctionne mais reste technique. Pour un déploiement
propre où chaque collègue installe l'extension **en un clic** (et où elle se met
à jour toute seule), on peut la **publier sur le Chrome Web Store** :

- il faut un compte développeur Google (frais uniques ~5 $) et une courte
  validation par Google (souvent 1 à quelques jours) ;
- ensuite tu partages un simple lien « Ajouter à Chrome ». Plus de mode
  développeur, plus de dossier à charger.

Dis-le-moi si tu veux qu'on parte là-dessus : je prépare le paquet et je te
guide pas à pas pour la mise en ligne.

## Confidentialité

L'extension n'agit que sur `ai.skaelia.com` et `linkedin.com`, et n'envoie
aucune donnée ailleurs. Tout se passe dans ton navigateur.
