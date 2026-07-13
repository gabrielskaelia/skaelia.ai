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

  // L'application demande si une session LinkedIn est ouverte dans ce Chrome,
  // et QUI est connecté. Le cookie « li_at » n'existe que connecté ; le nom est
  // récupéré via l'API interne LinkedIn (voyager), avec le jeton CSRF issu du
  // cookie JSESSIONID. Si le nom échoue, on renvoie quand même connecte:true.
  if (msg.type === "CHECK_LINKEDIN") {
    (async () => {
      let connecte = false;
      try {
        const cookie = await chrome.cookies.get(
          { url: "https://www.linkedin.com/", name: "li_at" });
        connecte = !!(cookie && cookie.value);
      } catch (e) { /* on tente le repli réseau */ }
      if (!connecte) {
        try {
          const r = await fetch("https://www.linkedin.com/feed/",
                                { credentials: "include", redirect: "follow" });
          const u = (r.url || "").toLowerCase();
          connecte = r.ok && !u.includes("/login") && !u.includes("authwall")
                          && !u.includes("uas/") && !u.includes("checkpoint");
        } catch (e) { sendResponse({ connecte: false, error: e.message }); return; }
      }
      let nom = "";
      if (connecte) {
        try {
          const js = await chrome.cookies.get(
            { url: "https://www.linkedin.com/", name: "JSESSIONID" });
          const csrf = js ? js.value.replace(/"/g, "") : "";
          const rep = await fetch("https://www.linkedin.com/voyager/api/me", {
            credentials: "include",
            headers: { "csrf-token": csrf, "accept": "application/json" },
          });
          if (rep.ok) {
            const d = await rep.json();
            const prof = (d.included || []).find((x) => x.firstName && x.lastName);
            if (prof) nom = (prof.firstName + " " + prof.lastName).trim();
          }
        } catch (e) { /* nom indisponible : on garde connecte:true */ }
      }
      sendResponse({ connecte, nom });
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
