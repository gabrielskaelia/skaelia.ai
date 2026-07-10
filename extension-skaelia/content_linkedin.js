/* S'exécute sur chaque page linkedin.com. Au chargement, demande au service
   worker s'il y a un envoi en attente pour cet onglet, puis agit selon la
   page (profil -> ouvrir la messagerie ; messagerie -> écrire + envoyer).
   Gère aussi la fenêtre InMail des comptes Premium (champ Objet en plus).
   Le script étant ré-injecté à chaque navigation, l'état vit côté background. */
"use strict";

function pause(ms) { return new Promise((r) => setTimeout(r, ms)); }

function attendre(fn, timeout = 12000, intervalle = 300) {
  return new Promise((resolve, reject) => {
    const debut = Date.now();
    (function boucle() {
      let v; try { v = fn(); } catch (e) { v = null; }
      if (v) return resolve(v);
      if (Date.now() - debut > timeout) return reject(new Error("Élément LinkedIn introuvable (page modifiée ?)"));
      setTimeout(boucle, intervalle);
    })();
  });
}

/* Lien/bouton "Message" DU PROFIL (souvent un <a> vers messaging/compose),
   en excluant la barre de navigation (« Messagerie »). */
function trouverBoutonMessage() {
  const nav = document.querySelector("header.global-nav, #global-nav, .global-nav, header[role='banner']");
  return [...document.querySelectorAll("a, button")].find((el) => {
    if (el.offsetParent === null) return false;
    if (nav && nav.contains(el)) return false;
    const href = (el.getAttribute("href") || "").toLowerCase();
    const aria = (el.getAttribute("aria-label") || "").toLowerCase();
    const txt = (el.innerText || "").trim().toLowerCase();
    if (href.includes("messaging/compose") || href.includes("messaging/thread/new")) return true;
    return txt === "message" || txt === "envoyer un message"
        || aria.startsWith("message ") || aria.includes("envoyer un message");
  });
}

function trouverZoneMessage() {
  return document.querySelector('div.msg-form__contenteditable[contenteditable="true"]')
      || document.querySelector('.msg-form [contenteditable="true"]')
      || document.querySelector('[role="textbox"][contenteditable="true"]');
}

/* Champ « Objet » de la fenêtre InMail (comptes Premium). Absent pour un
   message classique entre relations : on ne le remplit que s'il existe. */
function trouverChampObjet() {
  return document.querySelector('.msg-form input[name="subject"]')
      || document.querySelector('input[name="subject"]')
      || document.querySelector('.msg-form input[placeholder*="bjet" i]')
      || document.querySelector('.msg-form input[aria-label*="bjet" i]')
      || document.querySelector('.msg-form input[placeholder*="ubject" i]');
}

/* Fenêtre « Envoyez un message à X avec Premium » : LinkedIn refuse le
   message et propose un abonnement. On la détecte pour renvoyer une erreur
   claire au lieu d'attendre dans le vide. */
function trouverUpsellPremium() {
  const modale = [...document.querySelectorAll(".artdeco-modal, [role='dialog'], [data-test-modal]")]
    .find((m) => m.offsetParent !== null);
  if (!modale) return null;
  const txt = (modale.innerText || "").toLowerCase();
  const parlePremium = txt.includes("premium") || txt.includes("inmail");
  const pasDeZone = !modale.querySelector('[contenteditable="true"]');
  return parlePremium && pasDeZone ? modale : null;
}

function trouverBoutonEnvoyer() {
  return document.querySelector("button.msg-form__send-button")
      || document.querySelector('button[type="submit"].msg-form__send-btn')
      || [...document.querySelectorAll("button")].find((b) => {
           const t = (b.innerText || "").trim().toLowerCase();
           const a = (b.getAttribute("aria-label") || "").toLowerCase();
           return t === "envoyer" || t === "send" || a === "envoyer" || a === "send";
         });
}

function ecrireDans(zone, texte) {
  zone.focus();
  document.execCommand("selectAll", false, null);
  document.execCommand("delete", false, null);
  texte.split("\n").forEach((ligne, i) => {
    if (i > 0) document.execCommand("insertParagraph", false, null);
    if (ligne) document.execCommand("insertText", false, ligne);
  });
  zone.dispatchEvent(new Event("input", { bubbles: true }));
}

/* Remplit le champ Objet (InMail) à la manière d'une vraie saisie, pour que
   LinkedIn active le bouton Envoyer. */
function ecrireObjet(champ, texte) {
  champ.focus();
  champ.select();
  document.execCommand("insertText", false, texte);
  champ.dispatchEvent(new Event("input", { bubbles: true }));
  champ.dispatchEvent(new Event("change", { bubbles: true }));
}

async function remplirEtEnvoyer(zone, pending) {
  await pause(400);
  // InMail (Premium) : un champ Objet est requis avant l'envoi.
  const objet = trouverChampObjet();
  if (objet && !objet.value) {
    ecrireObjet(objet, pending.subject || "Prise de contact — Skaelia");
    await pause(300);
  }
  ecrireDans(zone, pending.message);
  await pause(700);
  const bouton = await attendre(() => {
    const b = trouverBoutonEnvoyer();
    return b && !b.disabled ? b : null;
  }, 10000);
  bouton.click();
  await pause(1000);
}

function envoyerResultat(ok, error) {
  try { chrome.runtime.sendMessage({ type: "DO_RESULT", ok, error: error || "" }); } catch (e) {}
}

const ERREUR_PREMIUM =
  "LinkedIn demande un abonnement Premium (InMail) pour écrire à ce profil. "
  + "Vérifie ton abonnement ou tes crédits InMail.";

/* Attend soit la zone de message, soit la fenêtre d'upsell Premium. */
function attendreZoneOuUpsell(timeout = 15000) {
  return attendre(() => {
    const upsell = trouverUpsellPremium();
    if (upsell) return { upsell };
    const zone = trouverZoneMessage();
    if (zone) return { zone };
    return null;
  }, timeout);
}

(async function init() {
  let pending = null;
  try {
    pending = await new Promise((res) => chrome.runtime.sendMessage({ type: "GET_PENDING" }, res));
  } catch (e) { return; }
  if (!pending) return;  // navigation normale de l'utilisateur : ne rien faire

  try {
    if (location.href.includes("/messaging/")) {
      // Page de messagerie : écrire et envoyer (ou détecter le blocage Premium)
      const r = await attendreZoneOuUpsell(15000);
      if (r.upsell) { envoyerResultat(false, ERREUR_PREMIUM); return; }
      await remplirEtEnvoyer(r.zone, pending);
      envoyerResultat(true);
      return;
    }

    // Page de profil : ouvrir la messagerie de ce contact
    const lien = await attendre(trouverBoutonMessage, 12000);
    lien.click();

    // Cas 1 : une surimpression s'ouvre sur place -> on l'utilise.
    // Cas 2 : la page navigue vers /messaging/ -> le script se ré-injecte et
    //         c'est la branche ci-dessus qui prendra le relais.
    // Cas 3 : fenêtre Premium -> erreur claire.
    for (let i = 0; i < 16; i++) {
      await pause(300);
      if (!location.href.includes("/in/")) return; // navigation en cours
      if (trouverUpsellPremium()) { envoyerResultat(false, ERREUR_PREMIUM); return; }
      const zone = trouverZoneMessage();
      if (zone) {
        await remplirEtEnvoyer(zone, pending);
        envoyerResultat(true);
        return;
      }
    }
    // Ni surimpression ni navigation : on tente d'aller directement au lien
    const href = lien.getAttribute("href");
    if (href) location.href = href.startsWith("http") ? href : "https://www.linkedin.com" + href;
  } catch (e) {
    envoyerResultat(false, e.message);
  }
})();
