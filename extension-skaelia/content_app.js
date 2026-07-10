/* S'exécute sur ai.skaelia.com : pont entre l'application web et l'extension.
   L'app parle par window.postMessage ; l'extension répond de façon asynchrone
   (l'envoi traverse une navigation LinkedIn, donc le résultat arrive plus tard). */
(function () {
  "use strict";

  function annoncerPresence() {
    document.documentElement.setAttribute("data-skaelia-ext", "1");
    window.postMessage({ source: "skaelia-ext", type: "READY" }, "*");
  }
  annoncerPresence();
  window.addEventListener("load", annoncerPresence);

  // Demandes venant de l'application
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== "skaelia-app") return;

    if (data.type === "PING") {
      window.postMessage({ source: "skaelia-ext", type: "READY" }, "*");
    } else if (data.type === "SEND_LINKEDIN") {
      chrome.runtime.sendMessage({
        type: "SEND_LINKEDIN",
        id: data.id,
        profileUrl: data.profileUrl,
        message: data.message,
        subject: data.subject || "",
      });
      // Le résultat final arrivera via un message SEND_RESULT du background.
    } else if (data.type === "CHECK_LINKEDIN") {
      chrome.runtime.sendMessage({ type: "CHECK_LINKEDIN" }, (rep) => {
        window.postMessage({
          source: "skaelia-ext", type: "LINKEDIN_STATUS",
          id: data.id, connecte: !!(rep && rep.connecte),
        }, "*");
      });
    }
  });

  // Résultat final renvoyé par le service worker
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "SEND_RESULT") {
      window.postMessage({
        source: "skaelia-ext", type: "RESULT",
        id: msg.id, ok: msg.ok, error: msg.error,
      }, "*");
    }
  });
})();
