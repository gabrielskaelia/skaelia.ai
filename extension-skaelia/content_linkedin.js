/* S'exécute sur chaque page linkedin.com. Au chargement, demande au service
   worker s'il y a un envoi en attente pour cet onglet, puis agit selon la
   page (profil -> ouvrir la messagerie ; messagerie -> écrire + envoyer).
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

function trouverBoutonEnvoyer() {
  return document.querySelector("button.msg-form__send-button")
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

async function remplirEtEnvoyer(zone, message) {
  await pause(400);
  ecrireDans(zone, message);
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

(async function init() {
  let pending = null;
  try {
    pending = await new Promise((res) => chrome.runtime.sendMessage({ type: "GET_PENDING" }, res));
  } catch (e) { return; }
  if (!pending) return;  // navigation normale de l'utilisateur : ne rien faire

  try {
    if (location.href.includes("/messaging/")) {
      // Page de messagerie : écrire et envoyer
      const zone = await attendre(trouverZoneMessage, 15000);
      await remplirEtEnvoyer(zone, pending.message);
      envoyerResultat(true);
      return;
    }

    // Page de profil : ouvrir la messagerie de ce contact
    const lien = await attendre(trouverBoutonMessage, 12000);
    lien.click();

    // Cas 1 : une surimpression s'ouvre sur place -> on l'utilise.
    // Cas 2 : la page navigue vers /messaging/ -> le script se ré-injecte et
    //         c'est la branche ci-dessus qui prendra le relais.
    for (let i = 0; i < 16; i++) {
      await pause(300);
      if (!location.href.includes("/in/")) return; // navigation en cours
      const zone = trouverZoneMessage();
      if (zone) {
        await remplirEtEnvoyer(zone, pending.message);
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
