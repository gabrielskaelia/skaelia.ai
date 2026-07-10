/* Service worker : orchestre l'envoi en survivant à la navigation LinkedIn.
   L'état est stocké dans chrome.storage.session, indexé par onglet, car le
   content script est ré-injecté (et perd sa mémoire) à chaque changement de page. */
"use strict";

const CLE = (tabId) => `pending_${tabId}`;

async function lirePending(tabId) {
  const o = await chrome.storage.session.get(CLE(tabId));
  return o[CLE(tabId)] || null;
}
async function ecrirePending(tabId, val) {
  await chrome.storage.session.set({ [CLE(tabId)]: val });
}
async function effacerPending(tabId) {
  await chrome.storage.session.remove(CLE(tabId));
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // Demande d'envoi émise par l'application (onglet ai.skaelia.com)
  if (msg.type === "SEND_LINKEDIN") {
    (async () => {
      const appTabId = sender.tab.id;
      const tab = await chrome.tabs.create({ url: msg.profileUrl, active: true });
      await ecrirePending(tab.id, {
        id: msg.id, appTabId,
        message: msg.message,
        subject: msg.subject || "",   // objet InMail (comptes Premium)
      });
      sendResponse({ ok: true, queued: true });
    })();
    return true;
  }

  // L'application demande si une session LinkedIn est ouverte dans ce Chrome
  if (msg.type === "CHECK_LINKEDIN") {
    (async () => {
      try {
        const r = await fetch("https://www.linkedin.com/feed/", {
          credentials: "include", redirect: "follow",
        });
        const u = (r.url || "").toLowerCase();
        const connecte = r.ok && !u.includes("/login") && !u.includes("authwall")
                              && !u.includes("uas/") && !u.includes("checkpoint");
        sendResponse({ connecte });
      } catch (e) {
        sendResponse({ connecte: false, error: e.message });
      }
    })();
    return true;
  }

  // Le content script LinkedIn demande s'il a une tâche en attente
  if (msg.type === "GET_PENDING") {
    (async () => sendResponse(await lirePending(sender.tab.id)))();
    return true;
  }

  // Résultat final de l'envoi
  if (msg.type === "DO_RESULT") {
    (async () => {
      const p = await lirePending(sender.tab.id);
      await effacerPending(sender.tab.id);
      if (p) {
        try {
          chrome.tabs.sendMessage(p.appTabId, {
            type: "SEND_RESULT", id: p.id, ok: msg.ok, error: msg.error,
          });
        } catch (e) { /* onglet app fermé */ }
        // Referme l'onglet LinkedIn après un court instant
        setTimeout(() => chrome.tabs.remove(sender.tab.id).catch(() => {}), 1800);
      }
      sendResponse({ ok: true });
    })();
    return true;
  }
});
