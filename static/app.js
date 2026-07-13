/* Skaelia Prospection — logique client */
"use strict";

// Garde-fou de session : on se déconnecte quand l'onglet/navigateur a été fermé
// puis rouvert (le cookie peut être restauré par le navigateur, mais pas ce
// marqueur d'onglet). Un simple rafraîchissement conserve la session.
(function () {
  try {
    if (sessionStorage.getItem("se_actif")) return;         // onglet déjà actif
    if (window.__frais) { sessionStorage.setItem("se_actif", "1"); return; }  // connexion fraîche
    // Onglet rouvert / session restaurée par le navigateur : on déconnecte.
    document.documentElement.style.visibility = "hidden";
    fetch("/api/deconnexion", { method: "POST" }).finally(() => location.replace("/"));
  } catch (e) { /* sessionStorage indisponible : on ne bloque pas */ }
})();

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

// Lien d'installation de l'extension sur le Chrome Web Store (ID stable de
// l'extension). Fonctionne une fois l'extension validée/publiée par Google.
const LIEN_EXTENSION = "https://chromewebstore.google.com/detail/dgfooifdbhgjddidgdpcjknjbmpmccco";

let sondage = null;
let resultats = null;
let tableActive = "contacts";
let mesContacts = [];
let clesSauvegardees = new Set();
let _sondageEnrich = null;

/* ---------------- utilitaires ---------------- */

function toast(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3600);
}

async function api(url, options) {
  const r = await fetch(url, options);
  if (r.status === 401) { location.href = "/connexion"; throw new Error("Non connecté"); }
  const donnees = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(donnees.erreur || `Erreur ${r.status}`);
  return donnees;
}

function post(url, corps) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps || {}),
  });
}

function echapper(texte) {
  const div = document.createElement("div");
  div.textContent = texte == null ? "" : String(texte);
  return div.innerHTML;
}

function prenomDe(nom) {
  return (nom || "").trim().split(/\s+/)[0] || "";
}

/* Message pré-rédigé, personnalisé à partir du contact, de l'offre publiée et
   de références clients Nicoka (preuve sociale) pertinentes selon le poste. */
function messageProspection(c, refs) {
  const prenom = prenomDe(c.nom);
  const entreprise = c.entreprise || "votre entreprise";
  const offre = (c.offres && c.offres[0] && c.offres[0].titre)
    ? c.offres[0].titre.replace(/\s*[HF]\/[HF]\s*$/i, "").trim() : "";
  const role = c.poste ? c.poste.split("|")[0].trim() : "";

  let reference = "";
  if (refs && refs.length) {
    const clients = refs.map((r) => r.client).slice(0, 2);
    const liste = clients.length === 2 ? `${clients[0]} et ${clients[1]}` : clients[0];
    reference = ` Nous accompagnons d'ailleurs des entreprises comme ${liste} sur ce type de profils.`;
  }

  // Accroche adaptée au rôle du contact (issu de son profil LinkedIn)
  const intro = role
    ? `Je me permets de vous écrire directement : en tant que ${role}, vous êtes sûrement en première ligne sur les recrutements de ${entreprise}.`
    : `Je me permets de vous contacter au sujet des recrutements de ${entreprise}.`;

  const besoin = offre
    ? `J'ai justement vu que ${entreprise} recherche un profil ${offre}.`
    : `J'ai vu que ${entreprise} recrute en ce moment.`;

  return `Bonjour ${prenom},\n\n`
    + `${intro}\n\n`
    + `${besoin} Je travaille chez Skaelia, cabinet de recrutement, et c'est précisément le type de poste `
    + `sur lequel nous pouvons vous faire gagner du temps.${reference}\n\n`
    + `Auriez-vous 15 minutes cette semaine pour en échanger ?\n\n`
    + `Bien à vous,`;
}

/* Récupère les références clients pertinentes puis compose le message. */
async function messagePersonnalise(c) {
  let refs = [];
  const role = (c.offres && c.offres[0] && c.offres[0].titre) || c.poste || "";
  if (role) {
    try { refs = await api("/api/references?poste=" + encodeURIComponent(role)); }
    catch { refs = []; }
  }
  return messageProspection(c, refs);
}

/* Identifiant public LinkedIn extrait de l'URL du profil */
function idLinkedin(url) {
  const m = (url || "").match(/\/in\/([^/?#]+)/i);
  return m ? decodeURIComponent(m[1]) : "";
}

/* Ouvre la fenêtre de messagerie LinkedIn vers le contact (mode manuel). */
function ouvrirMessagerieLinkedin(c) {
  const id = idLinkedin(c.url_linkedin);
  const url = id
    ? `https://www.linkedin.com/messaging/compose/?recipient=${encodeURIComponent(id)}`
    : c.url_linkedin;
  window.open(url, "_blank", "noopener");
}

/* ---- Pont avec l'extension Skaelia (envoi LinkedIn automatique) ---- */

let extensionPresente = false;
const _attentesExt = new Map();

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  const d = event.data;
  if (!d || d.source !== "skaelia-ext") return;
  if (d.type === "READY") {
    extensionPresente = true;
    document.body.classList.add("ext-ok");
    majChipsConnexions();
  } else if ((d.type === "RESULT" || d.type === "LINKEDIN_STATUS") && _attentesExt.has(d.id)) {
    _attentesExt.get(d.id)(d);
    _attentesExt.delete(d.id);
  }
});

// Détection au démarrage (l'extension pose aussi un attribut sur <html>)
function detecterExtension() {
  if (document.documentElement.getAttribute("data-skaelia-ext") === "1") extensionPresente = true;
  window.postMessage({ source: "skaelia-app", type: "PING" }, "*");
}

/* Envoie le message via l'extension. Retourne une promesse {ok, error}.
   `subject` sert d'objet InMail pour les comptes LinkedIn Premium. */
function envoyerViaExtension(profileUrl, message, subject) {
  return new Promise((resolve) => {
    const id = "e" + Date.now() + Math.random().toString(16).slice(2);
    _attentesExt.set(id, resolve);
    window.postMessage({ source: "skaelia-app", type: "SEND_LINKEDIN", id, profileUrl, message,
                         subject: subject || "Prise de contact — Skaelia" }, "*");
    setTimeout(() => {
      if (_attentesExt.has(id)) { _attentesExt.delete(id); resolve({ ok: false, error: "délai dépassé" }); }
    }, 45000);
  });
}

/* Demande à l'extension si une session LinkedIn est ouverte dans ce Chrome.
   `repondu` distingue une extension à jour (qui répond) d'une trop ancienne
   (présente mais sans le support de cette vérification → à recharger). */
function verifierSessionLinkedin() {
  return new Promise((resolve) => {
    if (!extensionPresente) return resolve({ connecte: false, extension: false, repondu: false });
    const id = "lk" + Date.now() + Math.random().toString(16).slice(2);
    _attentesExt.set(id, (d) => resolve({ connecte: !!d.connecte, nom: d.nom || "", extension: true, repondu: true }));
    window.postMessage({ source: "skaelia-app", type: "CHECK_LINKEDIN", id }, "*");
    setTimeout(() => {
      if (_attentesExt.has(id)) { _attentesExt.delete(id); resolve({ connecte: false, nom: "", extension: true, repondu: false }); }
    }, 6000);
  });
}

/* ---- Pastilles d'état des connexions (en-tête) ---- */

let emailPersoConfigure = false;
let emailPersoAdresse = "";
let sessionLinkedinOk = null;   // null = pas encore vérifié

function peindreChip(el, etat) {  // etat : "ok" | "ko" | "inconnu"
  if (el) el.dataset.etat = etat;
}

async function majChipsConnexions() {
  peindreChip($("#chipGmail"), emailPersoConfigure ? "ok" : "ko");
  if (!extensionPresente) { peindreChip($("#chipLinkedin"), "ko"); return; }
  const r = await verifierSessionLinkedin();
  sessionLinkedinOk = r.connecte;
  peindreChip($("#chipLinkedin"), r.connecte ? "ok" : "ko");
}

$("#chipsConnexions")?.addEventListener("click", () => $("#btnReglages").click());

async function copier(texte) {
  try { await navigator.clipboard.writeText(texte); return true; }
  catch { return false; }
}

/* ---------------- lancement & suivi ---------------- */

// Raccourcis de profondeur (propositions cliquables)
document.querySelectorAll("#suggestionsContacts .chip-offre").forEach((b) =>
  b.addEventListener("click", () => { $("#fNbContacts").value = b.dataset.val; })
);

function optionsRecherche() {
  // Nombre de contacts VISÉ (obligatoire) : on ratisse assez d'entreprises
  // (~1 contact utile par entreprise en moyenne) et on s'arrête dès la cible.
  const nbContacts = parseInt($("#fNbContacts")?.value, 10);
  // Nombre d'entreprises : saisi par l'utilisateur (doit rester inférieur au
  // nombre de contacts), sinon vivier automatique assez large pour atteindre
  // la cible même quand le marché est mince.
  const nbEntSaisi = parseInt($("#fNbEntreprises")?.value, 10);
  const maxEnt = nbEntSaisi > 0 ? nbEntSaisi : Math.max(4, Math.ceil((nbContacts || 40) * 1.4));
  return {
    contrats: $$("#fContrats input:checked").map((c) => c.value),
    region: $("#fRegion")?.value || "",
    anciennete_jours: $("#fAnciennete")?.value,
    nb_contacts_cible: nbContacts,
    pages: Math.min(6, Math.max(1, Math.ceil(maxEnt / 25))),
    max_entreprises: maxEnt,
    sources: $$("#fSources input:checked").map((c) => c.value),
    types_entreprise: $$("#fTypes input:checked").map((c) => c.value),
    recherche_amelioree: $("#fRechercheAmelioree")?.checked || false,
    inclure_cabinets: $("#fInclureCabinets")?.checked || false,
  };
}

async function lancerRecherche() {
  const secteur = $("#fSecteur")?.value || "";
  const motsCles = ($("#fMotsCles")?.value || "").trim();
  if (!secteur && !motsCles) {
    toast("Indique un poste / des mots-clés, ou choisis un secteur.");
    $("#fMotsCles")?.focus(); return;
  }
  const nbContacts = parseInt($("#fNbContacts")?.value, 10);
  if (!nbContacts || nbContacts < 1) {
    toast("Indique le nombre de contacts recherché (obligatoire).");
    $("#fNbContacts")?.focus(); return;
  }
  const nbEnt = parseInt($("#fNbEntreprises")?.value, 10);
  if ($("#fNbEntreprises")?.value && (!nbEnt || nbEnt < 1)) {
    toast("Nombre d'entreprises invalide."); $("#fNbEntreprises")?.focus(); return;
  }
  if (nbEnt && nbEnt >= nbContacts) {
    toast("Le nombre d'entreprises doit être inférieur au nombre de contacts.");
    $("#fNbEntreprises")?.focus(); return;
  }
  const opts = optionsRecherche();
  if (!opts.sources.length) { toast("Choisis au moins une source (HelloWork/Indeed)."); return; }
  if (!opts.types_entreprise.length) { toast("Coche au moins un type : Prospects ou Clients."); return; }
  try {
    await post("/api/lancer", { secteur, poste: motsCles, ...opts });
  } catch (e) { toast(e.message); return; }

  $("#btnLancer").disabled = true;
  $("#vueResultats").hidden = true;
  const regionLabel = $("#fRegion")?.selectedOptions?.[0]?.textContent?.trim() || "";
  const lieu = regionLabel && regionLabel !== "Toute la France" ? regionLabel : "";
  $("#suiviTitre").textContent = `Recherche : ${motsCles || secteur}${lieu ? " — " + lieu : ""}`;
  $("#blocSuivi").hidden = false;
  $("#journal").innerHTML = "";
  $("#suiviSpinner").style.display = "";
  if (sondage) clearInterval(sondage);
  sondage = setInterval(interrogerStatut, 1500);
}

$("#btnLancer").addEventListener("click", lancerRecherche);

async function interrogerStatut() {
  let statut;
  try { statut = await api("/api/statut"); } catch { return; }

  const journal = $("#journal");
  journal.innerHTML = statut.logs.map((l) =>
    `<div class="journal-ligne"><span class="journal-heure">${l.heure}</span>
     <span>${echapper(l.texte)}</span></div>`).join("");
  journal.scrollTop = journal.scrollHeight;

  if (statut.etat === "termine" || statut.etat === "erreur") {
    clearInterval(sondage); sondage = null;
    $("#suiviSpinner").style.display = "none";
    $("#btnLancer").disabled = false;
    if (statut.etat === "termine") await afficherResultats(statut);
    else toast("Erreur : " + statut.erreur);
  }
}

/* ---------------- résultats de recherche ---------------- */

async function afficherResultats(statut) {
  resultats = await api("/api/resultats");
  const s = statut.synthese;
  $("#blocSuivi").hidden = true;
  $("#statsResultats").innerHTML = `
    <div class="stat"><span class="stat-nombre">${s.nb_contacts}</span><span class="stat-libelle">contacts</span></div>
    <div class="stat"><span class="stat-nombre">${s.nb_entreprises}</span><span class="stat-libelle">entreprises</span></div>
    <div class="stat"><span class="stat-nombre">${s.nb_offres}</span><span class="stat-libelle">offres</span></div>
    <div class="stat"><span class="stat-nombre">${s.nb_nouvelles}</span><span class="stat-libelle">nouvelles offres</span></div>`;
  tableActive = "contacts";
  $$(".onglet").forEach((b) => b.classList.toggle("actif", b.dataset.table === tableActive));
  dessinerTable();
  $("#vueResultats").hidden = false;
  chargerHistorique();
}

/* ---------------- recherches enregistrées ---------------- */

async function chargerHistorique() {
  let liste;
  try { liste = await api("/api/historique"); } catch { return; }
  const bloc = $("#blocHistorique");
  const grille = $("#grilleHistorique");
  if (!liste || !liste.length) { bloc.hidden = true; return; }
  grille.innerHTML = liste.map((h) => `
    <div class="carte-histo-conteneur">
      <button class="carte-histo" data-fichier="${echapper(h.fichier)}">
        <span class="histo-titre">${echapper(h.titre)}</span>
        <span class="histo-date">${echapper(h.date)}</span>
        <span class="histo-stats"><b>${h.nb_contacts}</b> contacts · <b>${h.nb_entreprises}</b> entreprises · <b>${h.nb_offres}</b> offres</span>
      </button>
      <button class="histo-suppr" data-suppr="${echapper(h.fichier)}" title="Supprimer cette recherche">✕</button>
    </div>`).join("");
  grille.querySelectorAll(".carte-histo").forEach((b) =>
    b.addEventListener("click", () => ouvrirHistorique(b.dataset.fichier))
  );
  grille.querySelectorAll(".histo-suppr").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      await api("/api/historique/" + encodeURIComponent(b.dataset.suppr), { method: "DELETE" });
      chargerHistorique();
    })
  );
  bloc.hidden = false;
}

async function ouvrirHistorique(fichier) {
  try {
    resultats = await api("/api/historique/" + encodeURIComponent(fichier));
  } catch (e) { toast(e.message); return; }
  $("#statsResultats").innerHTML = `
    <div class="stat"><span class="stat-nombre">${resultats.contacts.length}</span><span class="stat-libelle">contacts</span></div>
    <div class="stat"><span class="stat-nombre">${resultats.entreprises.length}</span><span class="stat-libelle">entreprises</span></div>
    <div class="stat"><span class="stat-nombre">${resultats.offres.length}</span><span class="stat-libelle">offres</span></div>
    <div class="stat"><span class="stat-nombre">${resultats.nb_nouvelles}</span><span class="stat-libelle">nouvelles offres</span></div>`;
  tableActive = resultats.contacts.length ? "contacts" : "offres";
  $$(".onglet").forEach((b) => b.classList.toggle("actif", b.dataset.table === tableActive));
  $("#barreContacts").hidden = tableActive !== "contacts";
  dessinerTable();
  $("#blocSuivi").hidden = true;
  $("#vueResultats").hidden = false;
  $("#vueResultats").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#btnViderHistorique")?.addEventListener("click", async () => {
  if (!confirm("Supprimer toutes les recherches enregistrées ?")) return;
  await api("/api/historique", { method: "DELETE" });
  chargerHistorique();
  toast("Recherches supprimées");
});

$$(".onglet").forEach((b) =>
  b.addEventListener("click", () => {
    $$(".onglet").forEach((x) => x.classList.remove("actif"));
    b.classList.add("actif");
    tableActive = b.dataset.table;
    $("#barreContacts").hidden = tableActive !== "contacts";
    dessinerTable();
  })
);

function offresDeLEntreprise(nomEntreprise) {
  const offres = resultats.offres.filter((o) => o.entreprise === nomEntreprise);
  if (!offres.length) return "";
  return offres.slice(0, 4).map((o) =>
    `<div class="offre-ligne">
       <a class="offre-lien" href="${echapper(o.url)}" target="_blank" rel="noopener">
         ${echapper(o.titre)}
       </a>${o.date ? `<span class="offre-date">${echapper(o.date)}</span>` : ""}
     </div>`).join("") + (offres.length > 4 ? `<span class="badge badge-neutre">+${offres.length - 4} autres</span>` : "");
}

function badgeType(type) {
  if (type === "client") return ' <span class="badge badge-client">Client</span>';
  if (type === "prospect") return ' <span class="badge badge-prospect">Prospect</span>';
  return "";
}

function dessinerTable() {
  const table = $("#tableResultats");
  if (!resultats) return;

  if (tableActive === "contacts") {
    $("#barreContacts").hidden = false;
    if (!resultats.contacts.length) {
      $("#barreContacts").hidden = true;
      table.innerHTML = "<tbody><tr><td style='padding:24px'>Aucun contact dans cette recherche.</td></tr></tbody>";
      return;
    }
    const visibles = resultats.contacts.map((c, i) => ({ c, i }));
    table.innerHTML =
      "<thead><tr><th></th><th>Contact</th><th>Poste du contact</th><th>Entreprise</th><th>Recrute actuellement</th><th>LinkedIn</th><th></th></tr></thead><tbody>" +
      visibles.map(({ c, i }) => {
        const dansCarnet = clesSauvegardees.has(cleContact(c));
        return `<tr>
        <td>${dansCarnet
            ? '<span class="badge badge-ok">ajouté ✓</span>'
            : `<button class="btn-ajout" data-idx="${i}">+ Ajouter</button>`}</td>
        <td><strong>${echapper(c.nom)}</strong></td>
        <td>${echapper(c.poste)}</td>
        <td>${echapper(c.entreprise)}${badgeType(c.type)}</td>
        <td class="cellule-postes">${offresDeLEntreprise(c.entreprise)}</td>
        <td><a href="${echapper(c.url_linkedin)}" target="_blank" rel="noopener">Profil</a></td>
        <td><button class="btn-suppr" data-suppr="${i}" title="Retirer ce contact">✕</button></td></tr>`;
      }).join("") +
      "</tbody>";
    table.querySelectorAll(".btn-ajout").forEach((b) =>
      b.addEventListener("click", () => ajouterContacts([resultats.contacts[+b.dataset.idx]]))
    );
    table.querySelectorAll(".btn-suppr").forEach((b) =>
      b.addEventListener("click", () => {
        resultats.contacts.splice(+b.dataset.suppr, 1);
        dessinerTable();
      })
    );
  } else {
    $("#barreContacts").hidden = true;
    table.innerHTML =
      "<thead><tr><th>Poste</th><th>Entreprise</th><th>Lieu</th><th>Contrat</th><th>Salaire</th><th>Publiée</th><th>Source</th></tr></thead><tbody>" +
      resultats.offres.map((o) => `<tr>
        <td><a href="${echapper(o.url)}" target="_blank" rel="noopener">${echapper(o.titre)}</a></td>
        <td>${echapper(o.entreprise)}${badgeType(o.type)}${o.via_cabinet ? ` <span class="badge badge-neutre" title="Annonce publiée par ${echapper(o.via_cabinet)}">via cabinet</span>` : ""}</td><td>${echapper(o.lieu)}</td>
        <td>${echapper(o.contrat)}</td><td>${echapper(o.salaire)}</td>
        <td>${echapper(o.date)}${o.nouveau ? ' <span class="tag-nouveau">nouveau</span>' : ""}</td><td>${echapper(o.source)}</td></tr>`).join("") +
      "</tbody>";
  }
}

$("#btnRetourRecherche")?.addEventListener("click", () => {
  $("#vueResultats").hidden = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
});

/* ---------------- compte ---------------- */

$("#btnDeconnexion").addEventListener("click", async () => {
  await post("/api/deconnexion");
  location.href = "/connexion";
});

/* ---------------- réglages (mot de passe + envoi d'emails) ---------------- */

$("#btnValiderMdp").addEventListener("click", async () => {
  const ancien = $("#mAncien").value, nouveau = $("#mNouveau").value;
  if (!ancien && !nouveau) return;   // rien à changer
  try {
    await post("/api/changer-mdp", { ancien, nouveau });
    $("#mAncien").value = ""; $("#mNouveau").value = "";
    $("#msgMdp").hidden = true;
    toast("Mot de passe changé ✓");
  } catch (e) {
    const msg = $("#msgMdp");
    msg.textContent = e.message; msg.hidden = false;
  }
});

let fullenrichConfiguree = false;

async function chargerReglages() {
  const r = await api("/api/reglages");
  fullenrichConfiguree = !!r.fullenrich_configuree;
  emailPersoConfigure = !!r.email_perso_configure;
  emailPersoAdresse = r.email_perso_adresse || "";
  gmailOauth = !!r.gmail_oauth;
  // Boutons Gmail : « Connecter » si non relié, sinon « Changer de compte »
  if ($("#btnConnecterGmail")) $("#btnConnecterGmail").hidden = gmailOauth;
  if ($("#btnChangerGmail")) $("#btnChangerGmail").hidden = !gmailOauth;
  // Configuration SMTP manuelle : proposée seulement sans connexion Google
  $("#zoneGmail").hidden = gmailOauth;
  $("#rSmtpUtilisateur").value = gmailOauth ? "" : (r.email_perso_adresse || "");
  $("#rSmtpHote").value = r.email_perso_hote || "smtp.gmail.com";
  $("#rSmtpPort").value = r.email_perso_port || 587;
  majChipsConnexions();
  return r;
}

/* États affichés dans le bloc « Connexions » de la modale Réglages */
async function majBlocConnexions() {
  const badge = (ok, texteOk, texteKo) =>
    `<span class="badge ${ok ? "badge-ok" : "badge-erreur"}">${ok ? texteOk : texteKo}</span>`;
  $("#cnxGmailEtat").outerHTML = `<span id="cnxGmailEtat">${
    badge(emailPersoConfigure, "connecté ✓" + (emailPersoAdresse ? " — " + echapper(emailPersoAdresse) : ""), "non connecté")}</span>`;
  const btnInstall = $("#btnInstallerExtension");
  if (!extensionPresente) {
    $("#cnxLinkedinEtat").outerHTML = `<span id="cnxLinkedinEtat">${badge(false, "", "extension non installée")}</span>`;
    $("#cnxLinkedinAide").textContent = "Installez l'extension Chrome Skaelia en un clic, puis rechargez la page.";
    if (btnInstall) btnInstall.hidden = false;
    if ($("#btnConnecterLinkedin")) $("#btnConnecterLinkedin").hidden = true;
    if ($("#btnChangerLinkedin")) $("#btnChangerLinkedin").hidden = true;
    return;
  }
  if (btnInstall) btnInstall.hidden = true;
  const r = await verifierSessionLinkedin();
  const btnConn = $("#btnConnecterLinkedin"), btnChg = $("#btnChangerLinkedin");
  if (!r.repondu) {   // extension présente mais trop ancienne
    $("#cnxLinkedinEtat").outerHTML = `<span id="cnxLinkedinEtat">${badge(false, "", "extension à recharger")}</span>`;
    $("#cnxLinkedinAide").textContent =
      "Votre extension Skaelia est trop ancienne. Allez sur chrome://extensions, cliquez sur ↻ (recharger) sur la carte Skaelia, puis rechargez cette page.";
    if (btnConn) btnConn.hidden = false;
    if (btnChg) btnChg.hidden = true;
    return;
  }
  const libelleOk = "connecté ✓" + (r.nom ? " — " + echapper(r.nom) : "");
  $("#cnxLinkedinEtat").outerHTML = `<span id="cnxLinkedinEtat">${
    badge(r.connecte, libelleOk, "session LinkedIn fermée")}</span>`;
  $("#cnxLinkedinAide").textContent = r.connecte
    ? "L'envoi direct des messages LinkedIn est actif."
    : "Ouvrez linkedin.com dans un onglet et connectez-vous, puis revenez ici.";
  // Connecté → « Changer de compte » ; sinon → « Connecter son LinkedIn »
  if (btnConn) btnConn.hidden = r.connecte;
  if (btnChg) btnChg.hidden = !r.connecte;
}

$("#btnReglages").addEventListener("click", async () => {
  await chargerReglages();
  $("#mAncien").value = ""; $("#mNouveau").value = ""; $("#msgMdp").hidden = true;
  $("#rSmtpMdp").value = "";
  // Sections repliées à l'ouverture (zoneGmail est gérée par chargerReglages)
  ["#zoneLinkedin", "#zoneMdp"].forEach((s) => { $(s).hidden = true; });
  $("#voileReglages").hidden = false;
  majBlocConnexions();
});
$("#btnFermerReglages").addEventListener("click", () => { $("#voileReglages").hidden = true; });

/* Sections dépliantes : le bouton révèle les champs correspondants */
function basculerZone(idZone) {
  const zone = $(idZone);
  zone.hidden = !zone.hidden;
}
$("#btnMontrerMdp")?.addEventListener("click", () => basculerZone("#zoneMdp"));

/* « Connecter son LinkedIn » : ouvre la page de connexion LinkedIn puis
   surveille la session via l'extension — le badge passe au vert tout seul. */
let _surveilLinkedin = null;

/* Ouvre LinkedIn (login ou changement de compte) et surveille la session :
   quand un compte est détecté, le badge et le nom se mettent à jour seuls. */
function surveillerConnexionLinkedin(url) {
  if (!extensionPresente) {
    $("#cnxLinkedinAide").textContent =
      "Il faut d'abord installer l'extension Chrome Skaelia (chrome://extensions), puis recharger cette page.";
    $("#zoneLinkedin").hidden = false;
    return;
  }
  window.open(url, "_blank", "noopener");
  toast("Connecte-toi à LinkedIn avec le compte voulu — je surveille…");
  if (_surveilLinkedin) clearInterval(_surveilLinkedin);
  let essais = 0, etatDepart = sessionLinkedinOk;
  _surveilLinkedin = setInterval(async () => {
    essais += 1;
    const r = await verifierSessionLinkedin();
    if (r.connecte) {
      clearInterval(_surveilLinkedin); _surveilLinkedin = null;
      sessionLinkedinOk = true;
      majChipsConnexions(); majBlocConnexions();
      toast(r.nom ? `LinkedIn connecté ✓ — ${r.nom}` : "LinkedIn connecté ✓");
    } else if (essais > 40) {           // ~2 minutes puis on arrête
      clearInterval(_surveilLinkedin); _surveilLinkedin = null;
    }
  }, 3000);
}

$("#btnInstallerExtension")?.addEventListener("click", () => {
  window.open(LIEN_EXTENSION, "_blank", "noopener");
  toast("Installe l'extension, puis recharge cette page.");
});

$("#btnConnecterLinkedin")?.addEventListener("click", () =>
  surveillerConnexionLinkedin("https://www.linkedin.com/login"));

$("#btnChangerLinkedin")?.addEventListener("click", () => {
  if (!confirm("Pour changer de compte, tu vas être déconnecté de LinkedIn dans ce navigateur, "
             + "puis tu te reconnecteras avec le compte voulu. Continuer ?")) return;
  // Déconnexion LinkedIn puis page de connexion, et on surveille la nouvelle session
  surveillerConnexionLinkedin("https://www.linkedin.com/m/logout/");
});

/* Gmail : « Connecter » et « Changer de compte » lancent la même autorisation
   Google (le sélecteur de compte est toujours affiché). */
let gmailOauth = false;
$("#btnConnecterGmail")?.addEventListener("click", () => { window.location.href = "/connexion/gmail"; });
$("#btnChangerGmail")?.addEventListener("click", () => { window.location.href = "/connexion/gmail"; });

$("#btnSauverGmail")?.addEventListener("click", async () => {
  if (!$("#rSmtpUtilisateur").value.trim()) { toast("Indique ton adresse Gmail."); return; }
  await post("/api/reglages", {
    smtp_perso: {
      hote: $("#rSmtpHote").value,
      port: $("#rSmtpPort").value,
      utilisateur: $("#rSmtpUtilisateur").value,
      mot_de_passe: $("#rSmtpMdp").value,
    },
  });
  await chargerReglages();
  await majBlocConnexions();
  $("#zoneGmail").hidden = true;
  toast("Gmail relié ✓");
});

/* ---------------- carnet « Mes contacts » ---------------- */

function cleContact(c) {
  const url = (c.url_linkedin || "").split("?")[0].replace(/\/+$/, "").toLowerCase();
  if (url) return url;
  return `${(c.nom || "").trim().toLowerCase()}@${(c.entreprise || "").trim().toLowerCase()}`;
}

function majCompteurContacts() {
  const pastille = $("#compteurContacts");
  pastille.textContent = mesContacts.length;
  pastille.hidden = mesContacts.length === 0;
}

async function chargerMesContacts() {
  try { mesContacts = await api("/api/mes-contacts"); }
  catch { mesContacts = []; }
  clesSauvegardees = new Set(mesContacts.map(cleContact));
  majCompteurContacts();
}

/* Attache à un contact les offres publiées par son entreprise (lien retour) */
function enrichirOffres(c) {
  if (!resultats || !resultats.offres) return c;
  const offres = resultats.offres
    .filter((o) => o.entreprise === c.entreprise)
    .map((o) => ({ titre: o.titre, url: o.url }));
  return { ...c, offres };
}

async function ajouterContacts(contacts) {
  try {
    contacts = contacts.map(enrichirOffres);
    const r = await post("/api/mes-contacts", { contacts });
    mesContacts = r.contacts;
    clesSauvegardees = new Set(mesContacts.map(cleContact));
    majCompteurContacts();
    if (r.ajoutes === 0) toast("Déjà dans vos contacts.");
    else toast(r.ajoutes === 1 ? "Contact ajouté ✓" : `${r.ajoutes} contacts ajoutés ✓`);
    if (tableActive === "contacts" && !$("#vueResultats").hidden) dessinerTable();
  } catch (e) { toast(e.message); }
}

async function supprimerContact(cle) {
  try {
    const r = await post("/api/mes-contacts/supprimer", { cles: [cle] });
    mesContacts = r.contacts;
    clesSauvegardees = new Set(mesContacts.map(cleContact));
    majCompteurContacts();
    dessinerMesContacts();
    if (resultats && tableActive === "contacts" && !$("#vueResultats").hidden) dessinerTable();
  } catch (e) { toast(e.message); }
}

$("#btnToutAjouter")?.addEventListener("click", () => {
  if (resultats && resultats.contacts.length) ajouterContacts(resultats.contacts);
});

$("#btnToutSupprimer")?.addEventListener("click", () => {
  if (!resultats || !resultats.contacts.length) return;
  if (!confirm("Supprimer tous les contacts trouvés de cette liste ?")) return;
  resultats.contacts = [];
  dessinerTable();
});

function dessinerMesContacts() {
  const table = $("#tableMesContacts");
  const vide = $("#contactsVide");
  const actions = $("#actionsContacts");
  if (!mesContacts.length) {
    table.innerHTML = "";
    $("#carteMesContacts").hidden = true;
    actions.hidden = true;
    vide.hidden = false;
    return;
  }
  $("#carteMesContacts").hidden = false;
  actions.hidden = false;
  vide.hidden = true;
  table.innerHTML =
    "<thead><tr><th>Contact</th><th>Poste</th><th>Entreprise</th><th>Offre publiée</th><th>LinkedIn</th><th>Email</th><th>Téléphone</th><th></th><th></th></tr></thead><tbody>" +
    mesContacts.map((c) => {
      const cle = cleContact(c);
      const offres = c.offres || [];
      const lienLinkedin = c.url_linkedin
        ? `<a href="${echapper(c.url_linkedin)}" target="_blank" rel="noopener">Profil</a>`
        : '<span class="txt-faible">—</span>';
      const lienOffre = offres.length
        ? offres.slice(0, 3).map((o) => `<a href="${echapper(o.url)}" target="_blank" rel="noopener" title="${echapper(o.titre)}">${echapper(o.titre || "Voir l'offre")}</a>`).join("<br>")
        : '<span class="txt-faible">—</span>';
      const cellEmail = c.email ? echapper(c.email) : '<span class="txt-faible">—</span>';
      const cellTel = c.telephone ? echapper(c.telephone) : '<span class="txt-faible">—</span>';
      return `<tr>
        <td><strong>${echapper(c.nom)}</strong></td>
        <td>${echapper(c.poste)}</td>
        <td>${echapper(c.entreprise)}</td>
        <td class="cellule-offre">${lienOffre}</td>
        <td>${lienLinkedin}</td>
        <td>${cellEmail}</td>
        <td>${cellTel}</td>
        <td><button class="btn btn-primaire btn-petit btn-prendre" data-cle="${echapper(cle)}">Prendre contact manuellement</button></td>
        <td><button class="btn-suppr" data-cle="${echapper(cle)}" title="Retirer">✕</button></td>
      </tr>`;
    }).join("") +
    "</tbody>";

  table.querySelectorAll(".btn-prendre").forEach((b) =>
    b.addEventListener("click", () => ouvrirPrendreContact(b.dataset.cle))
  );
  table.querySelectorAll(".btn-suppr").forEach((b) =>
    b.addEventListener("click", () => supprimerContact(b.dataset.cle))
  );
}

/* ---- Prendre contact manuellement : LinkedIn / Mail / Téléphone ---- */

async function ouvrirPrendreContact(cle) {
  const c = mesContacts.find((x) => cleContact(x) === cle);
  if (!c) return;
  $("#pcTitre").textContent = "Prendre contact manuellement — " + c.nom;
  $("#pcSousTitre").textContent = [c.poste, c.entreprise].filter(Boolean).join(" · ");

  const msg = await messagePersonnalise(c);
  const zone = $("#optionsContact");

  // LinkedIn : ouvre la messagerie du profil + copie le message pré-rédigé
  const blocLinkedin = c.url_linkedin ? `
    <div class="option-bloc">
      <div class="option-titre"><span class="oc-icone oc-linkedin">in</span> LinkedIn</div>
      <textarea class="message-prospect" id="pcMsgLinkedin" rows="6">${echapper(msg)}</textarea>
      <button class="btn btn-primaire btn-petit" id="pcLinkedin">Envoyer sur LinkedIn →</button>
      <small class="txt-faible">La fenêtre de message LinkedIn s'ouvre avec le texte copié : colle (Ctrl+V) et envoie.</small>
    </div>` : `
    <div class="option-bloc desactive"><div class="option-titre"><span class="oc-icone oc-linkedin">in</span> LinkedIn — profil inconnu</div></div>`;

  // Email : vérifier (UseBouncer) puis envoyer directement (connexion Gmail)
  // ou, à défaut, ouvrir le brouillon pré-rempli dans la messagerie.
  const blocEmail = c.email ? `
    <div class="option-bloc">
      <div class="option-titre"><span class="oc-icone oc-mail">@</span> Email — ${echapper(c.email)}
        <span id="pcStatutEmail">${c.statut_email ? badgeStatutEmail(c.statut_email) : ""}</span></div>
      ${emailPersoConfigure ? `<textarea class="message-prospect" id="pcMsgEmail" rows="6">${echapper(msg)}</textarea>` : ""}
      <div class="oc-actions">
        <button class="btn btn-secondaire btn-petit" id="pcVerifier">Vérifier</button>
        <button class="btn btn-primaire btn-petit" id="pcEcrire">${emailPersoConfigure ? "Envoyer l'email →" : "Contacter"}</button>
      </div>
      ${emailPersoConfigure ? `<small class="txt-faible">Envoi direct depuis ${echapper(emailPersoAdresse)}.</small>` : ""}
    </div>` : `
    <div class="option-bloc">
      <div class="option-titre"><span class="oc-icone oc-mail">@</span> Email — non trouvé</div>
      ${boutonEnrichirEmail(c)}
    </div>`;

  // Téléphone
  const rech = encodeURIComponent(`${c.nom} ${c.entreprise} téléphone`);
  const blocTel = c.telephone ? `
    <div class="option-bloc">
      <div class="option-titre"><span class="oc-icone oc-tel">☎</span> Téléphone — ${echapper(c.telephone)}</div>
      <a class="btn btn-primaire btn-petit" href="tel:${echapper(c.telephone.replace(/\s/g, ""))}">Contacter</a>
    </div>` : `
    <div class="option-bloc">
      <div class="option-titre"><span class="oc-icone oc-tel">☎</span> Téléphone — aucun numéro</div>
      <div class="oc-actions">
        ${boutonEnrichirTel(c)}
        <a class="btn btn-secondaire btn-petit" href="https://www.google.com/search?q=${rech}" target="_blank" rel="noopener">Chercher</a>
        <button class="btn btn-secondaire btn-petit" id="pcSaisirTel">Saisir le numéro</button>
      </div>
    </div>`;

  zone.innerHTML = blocLinkedin + blocEmail + blocTel;

  $("#pcLinkedin")?.addEventListener("click", async () => {
    const texte = $("#pcMsgLinkedin").value;
    if (extensionPresente && c.url_linkedin) {
      const btn = $("#pcLinkedin");
      btn.disabled = true; btn.textContent = "Envoi en cours…";
      const r = await envoyerViaExtension(c.url_linkedin, texte);
      btn.disabled = false; btn.textContent = "Envoyer sur LinkedIn →";
      toast(r.ok ? "Message envoyé sur LinkedIn ✓" : "Échec de l'envoi : " + (r.error || "inconnu"));
    } else {
      const ok = await copier(texte);
      ouvrirMessagerieLinkedin(c);
      toast(ok ? "Message copié — colle-le (Ctrl+V) et envoie" : "Rédige ton message dans LinkedIn");
    }
  });

  async function verifierEmail() {
    const r = await post("/api/verifier-email", { email: c.email, cle });
    $("#pcStatutEmail").innerHTML = badgeStatutEmail(r.statut);
    const idx = mesContacts.findIndex((x) => cleContact(x) === cle);
    if (idx >= 0) mesContacts[idx].statut_email = r.statut;
    return r.statut;
  }

  function ouvrirEmail() {
    const sujet = encodeURIComponent("Prise de contact — Skaelia");
    const corps = encodeURIComponent(msg);
    window.location.href = `mailto:${c.email}?subject=${sujet}&body=${corps}`;
  }

  /* Envoi direct via la connexion Gmail du compte (Réglages > Connexions). */
  async function envoyerEmailDirect() {
    const corps = $("#pcMsgEmail")?.value || msg;
    if (!confirm(`Envoyer cet email à ${c.email} ?`)) return;
    const btn = $("#pcEcrire");
    btn.disabled = true; btn.textContent = "Envoi…";
    try {
      await post("/api/envoyer-email", { a: c.email, sujet: "Prise de contact — Skaelia", corps });
      toast("Email envoyé ✓");
    } catch (e) { toast("Échec de l'envoi : " + e.message); }
    btn.disabled = false; btn.textContent = "Envoyer l'email →";
  }

  // « Vérifier » = contrôle l'adresse (UseBouncer). « Contacter/Envoyer » =
  // envoie directement (connexion Gmail) ou ouvre le brouillon pré-rempli.
  $("#pcVerifier")?.addEventListener("click", async () => {
    $("#pcVerifier").disabled = true;
    $("#pcVerifier").textContent = "Vérification…";
    try { toast("Email : " + traduireStatut(await verifierEmail())); }
    catch (e) { toast(e.message); }
    $("#pcVerifier").disabled = false;
    $("#pcVerifier").textContent = "Vérifier";
  });

  $("#pcEcrire")?.addEventListener("click", () => emailPersoConfigure ? envoyerEmailDirect() : ouvrirEmail());

  $("#pcSaisirTel")?.addEventListener("click", async () => {
    const num = prompt(`Numéro de téléphone de ${c.nom} :`, c.telephone || "");
    if (num === null) return;
    try {
      const r = await post("/api/mes-contacts/maj", { cle, telephone: num });
      const idx = mesContacts.findIndex((x) => cleContact(x) === cle);
      if (idx >= 0) mesContacts[idx] = r.contact;
      dessinerMesContacts();
      ouvrirPrendreContact(cle);
    } catch (e) { toast(e.message); }
  });

  // Enrichissement FullEnrich À LA DEMANDE, INDÉPENDANT email / téléphone
  // (l'email et le mobile se paient séparément — mobile bien plus cher).
  async function lancerEnrichissement(champ, selecteur) {
    const quoi = champ === "email" ? "l'email" : "le numéro";
    if (!confirm(`Rechercher ${quoi} via FullEnrich ? Cela utilise des crédits.`)) return;
    zone.querySelectorAll(selecteur).forEach((x) => { x.disabled = true; x.textContent = "Recherche en cours…"; });
    try {
      const r = await post("/api/mes-contacts/enrichir", { cle, champ });
      const idx = mesContacts.findIndex((x) => cleContact(x) === cle);
      if (idx >= 0 && r.contact) mesContacts[idx] = r.contact;
      dessinerMesContacts();
      toast(r.trouve ? (champ === "email" ? "Email trouvé ✓" : "Numéro trouvé ✓")
                     : (champ === "email" ? "Aucun email trouvé." : "Aucun numéro trouvé."));
    } catch (e) { toast(e.message); }
    ouvrirPrendreContact(cle);  // ré-affiche la modale à jour
  }
  zone.querySelectorAll(".pcEnrichirEmail").forEach((b) =>
    b.addEventListener("click", () => lancerEnrichissement("email", ".pcEnrichirEmail")));
  zone.querySelectorAll(".pcEnrichirTel").forEach((b) =>
    b.addEventListener("click", () => lancerEnrichissement("telephone", ".pcEnrichirTel")));

  $("#voilePrendreContact").hidden = false;
}

function boutonEnrichirEmail(c) {
  if (!fullenrichConfiguree)
    return '<small class="txt-faible">Enrichissement indisponible : clé FullEnrich manquante (Réglages).</small>';
  if (c.email_recherche === "fait")
    return '<small class="txt-faible">FullEnrich n\'a pas trouvé d\'email.</small>';
  return '<button class="btn btn-primaire btn-petit pcEnrichirEmail">Rechercher</button>';
}

function boutonEnrichirTel(c) {
  if (!fullenrichConfiguree)
    return '<small class="txt-faible">Enrichissement indisponible : clé FullEnrich manquante (Réglages).</small>';
  if (c.tel_recherche === "fait")
    return '<small class="txt-faible">FullEnrich n\'a pas trouvé de numéro.</small>';
  return '<button class="btn btn-secondaire btn-petit pcEnrichirTel">Rechercher</button>';
}

function badgeStatutEmail(statut) {
  if (!statut) return "";
  if (statut === "deliverable") return '<span class="badge badge-ok">délivrable ✓</span>';
  if (statut === "risky") return '<span class="badge badge-moyen">incertain</span>';
  if (statut === "undeliverable") return '<span class="badge badge-erreur">invalide</span>';
  return `<span class="badge badge-neutre">${echapper(statut)}</span>`;
}
function traduireStatut(s) {
  return { deliverable: "délivrable", risky: "incertain", undeliverable: "invalide", unknown: "inconnu" }[s] || s;
}

$("#btnFermerPrendreContact").addEventListener("click", () => { $("#voilePrendreContact").hidden = true; });
$("#voilePrendreContact").addEventListener("click", (e) => {
  if (e.target === $("#voilePrendreContact")) $("#voilePrendreContact").hidden = true;
});

$("#btnExportContacts")?.addEventListener("click", () => { location.href = "/api/mes-contacts/export"; });

/* ---- Tout prospecter : sélection + canal + parcours étape par étape ---- */

let fileProspection = [];
let etapeIdx = 0;

$("#btnToutProspecter")?.addEventListener("click", () => {
  const liste = $("#prListe");
  liste.innerHTML = mesContacts.map((c) => {
    const cle = cleContact(c);
    const canalDefaut = c.email ? "mail" : "linkedin";
    return `<div class="prospect-item">
      <label class="prospect-check"><input type="checkbox" class="pr-sel" data-cle="${echapper(cle)}" checked>
        <span><strong>${echapper(c.nom)}</strong> <small>${echapper(c.entreprise)}</small></span></label>
      <div class="pr-canaux">
        <label class="pr-canal"><input type="radio" name="canal-${echapper(cle)}" value="mail" ${canalDefaut === "mail" ? "checked" : ""} ${c.email ? "" : "disabled"}><span>Mail</span></label>
        <label class="pr-canal"><input type="radio" name="canal-${echapper(cle)}" value="linkedin" ${canalDefaut === "linkedin" ? "checked" : ""} ${c.url_linkedin ? "" : "disabled"}><span>LinkedIn</span></label>
      </div>
    </div>`;
  }).join("");
  $("#voileProspecter").hidden = false;
});

$("#btnFermerProspecter").addEventListener("click", () => { $("#voileProspecter").hidden = true; });

$("#btnLancerProspection").addEventListener("click", () => {
  fileProspection = [];
  $$("#prListe .pr-sel").forEach((chk) => {
    if (!chk.checked) return;
    const cle = chk.dataset.cle;
    const c = mesContacts.find((x) => cleContact(x) === cle);
    if (!c) return;
    const canal = $(`input[name="canal-${cle}"]:checked`)?.value || (c.email ? "mail" : "linkedin");
    fileProspection.push({ contact: c, canal });
  });
  if (!fileProspection.length) { toast("Sélectionne au moins un contact."); return; }
  $("#voileProspecter").hidden = true;
  etapeIdx = 0;
  afficherEtape();
});

async function afficherEtape() {
  if (etapeIdx < 0) etapeIdx = 0;
  if (etapeIdx >= fileProspection.length) { $("#voileEtape").hidden = true; toast("Prospection terminée ✓"); return; }
  const { contact: c, canal } = fileProspection[etapeIdx];
  $("#etProgression").textContent = `Contact ${etapeIdx + 1} / ${fileProspection.length}`;
  $("#etNom").textContent = c.nom;
  $("#etPoste").textContent = [c.poste, c.entreprise].filter(Boolean).join(" · ");
  const msg = await messagePersonnalise(c);

  if (canal === "mail" && c.email) {
    const libelle = emailPersoConfigure ? "Vérifier et envoyer l'email →" : "Vérifier et écrire l'email →";
    $("#etAction").innerHTML = `
      <div class="option-bloc">
        <div class="option-titre"><span class="oc-icone oc-mail">@</span> Email — ${echapper(c.email)}
          <span id="etStatutEmail">${c.statut_email ? badgeStatutEmail(c.statut_email) : ""}</span></div>
        <textarea class="message-prospect" id="etMsg" rows="6">${echapper(msg)}</textarea>
        <button class="btn btn-primaire btn-petit" id="etOuvrir">${libelle}</button>
        ${emailPersoConfigure ? `<small class="txt-faible">Envoi direct depuis ${echapper(emailPersoAdresse)}.</small>` : ""}
      </div>`;
  } else if (c.url_linkedin) {
    $("#etAction").innerHTML = `
      <div class="option-bloc">
        <div class="option-titre"><span class="oc-icone oc-linkedin">in</span> LinkedIn</div>
        <textarea class="message-prospect" id="etMsg" rows="6">${echapper(msg)}</textarea>
        <button class="btn btn-primaire btn-petit" id="etOuvrir">Envoyer sur LinkedIn →</button>
      </div>`;
  } else {
    $("#etAction").innerHTML = `<div class="option-bloc desactive"><div class="option-titre">Aucun canal disponible pour ce contact</div></div>`;
  }

  $("#etOuvrir")?.addEventListener("click", async () => {
    const { contact: cc, canal: cn } = fileProspection[etapeIdx];
    if (cn === "mail" && cc.email) {
      $("#etOuvrir").disabled = true; $("#etOuvrir").textContent = "Vérification…";
      let statut = cc.statut_email;
      try {
        if (!["deliverable", "risky", "undeliverable"].includes(statut)) {
          const r = await post("/api/verifier-email", { email: cc.email, cle: cleContact(cc) });
          statut = r.statut;
          cc.statut_email = statut;
          const idx = mesContacts.findIndex((x) => cleContact(x) === cleContact(cc));
          if (idx >= 0) mesContacts[idx].statut_email = statut;
          if ($("#etStatutEmail")) $("#etStatutEmail").innerHTML = badgeStatutEmail(statut);
        }
      } catch (e) { toast(e.message); }
      $("#etOuvrir").disabled = false;
      $("#etOuvrir").textContent = emailPersoConfigure ? "Vérifier et envoyer l'email →" : "Vérifier et écrire l'email →";
      if (statut === "undeliverable" && !confirm("Adresse invalide (non délivrable). Écrire quand même ?")) return;
      if (emailPersoConfigure) {
        if (!confirm(`Envoyer cet email à ${cc.email} ?`)) return;
        $("#etOuvrir").disabled = true; $("#etOuvrir").textContent = "Envoi…";
        try {
          await post("/api/envoyer-email", {
            a: cc.email, sujet: "Prise de contact — Skaelia", corps: $("#etMsg").value });
          toast("Email envoyé ✓");
        } catch (e) { toast("Échec de l'envoi : " + e.message); }
        $("#etOuvrir").disabled = false; $("#etOuvrir").textContent = "Vérifier et envoyer l'email →";
        return;
      }
      const sujet = encodeURIComponent("Prise de contact — Skaelia");
      window.location.href = `mailto:${cc.email}?subject=${sujet}&body=${encodeURIComponent($("#etMsg").value)}`;
    } else if (cc.url_linkedin) {
      if (extensionPresente) {
        $("#etOuvrir").disabled = true; $("#etOuvrir").textContent = "Envoi…";
        const r = await envoyerViaExtension(cc.url_linkedin, $("#etMsg").value);
        $("#etOuvrir").disabled = false; $("#etOuvrir").textContent = "Envoyer sur LinkedIn →";
        toast(r.ok ? "Message envoyé ✓" : "Échec : " + (r.error || "inconnu"));
      } else {
        await copier($("#etMsg").value);
        ouvrirMessagerieLinkedin(cc);
        toast("Message copié — colle-le (Ctrl+V) et envoie");
      }
    }
  });

  $("#etPrec").disabled = etapeIdx === 0;
  $("#etSuiv").textContent = etapeIdx === fileProspection.length - 1 ? "Terminer" : "Suivant →";
  $("#voileEtape").hidden = false;
}

$("#etPrec").addEventListener("click", () => { etapeIdx--; afficherEtape(); });
$("#etSuiv").addEventListener("click", () => { etapeIdx++; afficherEtape(); });

/* ---------------- Navigation Prospection / Mes contacts ---------------- */

function montrerVue(nom) {
  $("#vueProspection").hidden = nom !== "prospection";
  $("#vueContacts").hidden = nom !== "contacts";
  $("#vueComptes").hidden = nom !== "comptes";
  $$(".nav-onglet").forEach((b) => b.classList.toggle("actif", b.dataset.vue === nom));
  if (nom === "contacts") dessinerMesContacts();
  if (nom === "comptes") chargerComptes();
}

/* ---------------- Gestion des comptes (administrateur) ---------------- */

let comptes = [];

function dateFr(iso) {
  if (!iso) return "—";
  const [a, m, j] = iso.slice(0, 10).split("-");
  return a ? `${j}/${m}/${a}` : "—";
}

async function chargerComptes() {
  try { comptes = await api("/api/admin/utilisateurs"); }
  catch (e) { toast(e.message); return; }
  $("#detailCompte").hidden = true;
  const table = $("#tableComptes");
  const badgeStatut = (s) => ({
    actif: '<span class="badge badge-ok">actif</span>',
    valide: '<span class="badge badge-moyen">validé (mdp à définir)</span>',
    en_attente: '<span class="badge badge-neutre">en attente</span>',
  }[s] || `<span class="badge badge-neutre">${echapper(s)}</span>`);
  table.innerHTML =
    "<thead><tr><th>Compte</th><th>Nom</th><th>Statut</th><th>Dernière connexion</th><th>Connexions</th></tr></thead><tbody>" +
    comptes.map((c) => {
      const total = Object.values(c.connexions || {}).reduce((s, n) => s + n, 0);
      return `<tr class="ligne-compte" data-email="${echapper(c.email)}">
        <td>${echapper(c.email)}</td>
        <td>${echapper(c.nom) || "—"}</td>
        <td>${badgeStatut(c.statut)}</td>
        <td>${dateFr(c.derniere_connexion)}</td>
        <td>${total}</td>
      </tr>`;
    }).join("") + "</tbody>";
  table.querySelectorAll(".ligne-compte").forEach((tr) =>
    tr.addEventListener("click", () => afficherDetailCompte(tr.dataset.email))
  );
}

function afficherDetailCompte(email) {
  const c = comptes.find((x) => x.email === email);
  if (!c) return;
  const jours = Object.entries(c.connexions || {}).sort((a, b) => b[0].localeCompare(a[0]));
  const lignes = jours.length
    ? jours.map(([j, n]) => `<div class="cnx-jour"><span>${dateFr(j)}</span><b>${n} connexion${n > 1 ? "s" : ""}</b></div>`).join("")
    : '<div class="txt-faible">Aucune connexion enregistrée pour l\'instant (le comptage démarre avec cette mise à jour).</div>';
  const estAdmin = c.email === $("#utilisateurEmail").textContent;
  $("#detailCompte").innerHTML = `
    <h2>${echapper(c.email)}</h2>
    <p class="sous-titre">${echapper(c.nom) || "Nom non renseigné"} ·
      compte ${c.auth === "google" ? "Google" : "mot de passe"} ·
      demandé le ${dateFr(c.demande_le)}${c.valide_le ? " · validé le " + dateFr(c.valide_le) : ""}</p>
    <h2>Connexions par date</h2>
    <div class="cnx-historique">${lignes}</div>
    <div class="modale-actions">
      <button class="btn btn-secondaire" id="btnAdminMdp">Changer le mot de passe</button>
      ${estAdmin ? "" : '<button class="btn btn-danger" id="btnAdminSupprimer">Supprimer ce compte</button>'}
    </div>`;
  $("#detailCompte").hidden = false;
  $("#detailCompte").scrollIntoView({ behavior: "smooth", block: "nearest" });

  $("#btnAdminMdp").addEventListener("click", async () => {
    const mdp = prompt(`Nouveau mot de passe pour ${c.email} (8 caractères min.) :`);
    if (mdp === null) return;
    try {
      await post("/api/admin/mdp", { email: c.email, mot_de_passe: mdp });
      toast("Mot de passe changé ✓");
    } catch (e) { toast(e.message); }
  });

  $("#btnAdminSupprimer")?.addEventListener("click", async () => {
    if (!confirm(`Supprimer définitivement le compte ${c.email} ?\n\nSes contacts enregistrés et son historique de recherches seront aussi supprimés.`)) return;
    try {
      await post("/api/admin/supprimer", { email: c.email });
      toast("Compte supprimé ✓");
      chargerComptes();
    } catch (e) { toast(e.message); }
  });
}
$$(".nav-onglet").forEach((b) =>
  b.addEventListener("click", () => montrerVue(b.dataset.vue))
);

/* ---------------- Assistant de bienvenue (première connexion) ---------------- */

let _surveilObLinkedin = null;

function ouvrirOnboarding(etape) {
  // L'assistant n'apparaît qu'UNE fois, au setup du compte : on le marque
  // « vu » dès l'ouverture. Les connexions non faites se règlent ensuite
  // dans les Réglages — plus aucun rappel aux connexions suivantes.
  post("/api/onboarding-vu", {}).catch(() => {});
  sessionStorage.setItem("ob_encours", "1");   // pour reprendre après le retour Gmail
  detecterExtension();
  majEtapeOnboarding(etape);
  $("#voileOnboarding").hidden = false;
}

function majEtapeOnboarding(etape) {
  const surGmail = etape === "gmail";
  $("#obGmail").hidden = !surGmail;
  $("#obLinkedin").hidden = surGmail;
  $("#obPoint1").classList.toggle("actif", surGmail);
  $("#obPoint2").classList.toggle("actif", !surGmail);
  if (surGmail) {
    const badge = $("#obGmailEtat");
    badge.textContent = gmailOauth ? "connecté ✓" : "";
    badge.className = "badge " + (gmailOauth ? "badge-ok" : "badge-neutre");
  } else {
    majEtatObLinkedin();
  }
}

async function majEtatObLinkedin() {
  const el = $("#obLinkedinEtat");
  const btnInstall = $("#obInstallerExtension"), btnConn = $("#obConnecterLinkedin");
  if (!extensionPresente) {
    el.textContent = "extension non installée"; el.className = "badge badge-erreur";
    $("#obLinkedinAide").textContent =
      "Installe l'extension Chrome Skaelia (un clic), puis recharge la page. Tu peux aussi terminer et le faire plus tard.";
    if (btnInstall) btnInstall.hidden = false;
    if (btnConn) btnConn.hidden = true;
    return;
  }
  if (btnInstall) btnInstall.hidden = true;
  if (btnConn) btnConn.hidden = false;
  $("#obLinkedinAide").textContent = "";
  const r = await verifierSessionLinkedin();
  if (!r.repondu) {   // extension présente mais trop ancienne
    el.textContent = "extension à recharger"; el.className = "badge badge-erreur";
    $("#obLinkedinAide").textContent =
      "Ton extension Skaelia est trop ancienne : va sur chrome://extensions, clique sur ↻ sur la carte Skaelia, puis reviens. (Tu peux aussi terminer et le faire plus tard.)";
    return;
  }
  el.textContent = r.connecte ? ("connecté ✓" + (r.nom ? " — " + r.nom : "")) : "non connecté";
  el.className = "badge " + (r.connecte ? "badge-ok" : "badge-neutre");
}

async function terminerOnboarding() {
  if (_surveilObLinkedin) { clearInterval(_surveilObLinkedin); _surveilObLinkedin = null; }
  sessionStorage.removeItem("ob_encours");
  try { await post("/api/onboarding-vu", {}); } catch (e) { /* on ferme quand même */ }
  $("#voileOnboarding").hidden = true;
}

$("#obConnecterGmail")?.addEventListener("click", () => { window.location.href = "/connexion/gmail"; });
$("#obSauterGmail")?.addEventListener("click", () => majEtapeOnboarding("linkedin"));
$("#obTerminer")?.addEventListener("click", terminerOnboarding);
$("#obInstallerExtension")?.addEventListener("click", () => {
  window.open(LIEN_EXTENSION, "_blank", "noopener");
  toast("Installe l'extension, puis reviens et recharge la page.");
});

$("#obConnecterLinkedin")?.addEventListener("click", () => {
  if (!extensionPresente) { majEtatObLinkedin(); return; }
  window.open("https://www.linkedin.com/login", "_blank", "noopener");
  toast("Connecte-toi sur LinkedIn — je surveille…");
  if (_surveilObLinkedin) clearInterval(_surveilObLinkedin);
  let essais = 0;
  _surveilObLinkedin = setInterval(async () => {
    essais += 1;
    const r = await verifierSessionLinkedin();
    if (r.connecte) {
      clearInterval(_surveilObLinkedin); _surveilObLinkedin = null;
      sessionLinkedinOk = true; majChipsConnexions();
      $("#obLinkedinEtat").textContent = "connecté ✓";
      $("#obLinkedinEtat").className = "badge badge-ok";
      toast("LinkedIn connecté ✓");
      setTimeout(terminerOnboarding, 1000);
    } else if (essais > 40) {           // ~2 minutes puis on arrête la surveillance
      clearInterval(_surveilObLinkedin); _surveilObLinkedin = null;
    }
  }, 3000);
});

/* ---------------- démarrage ---------------- */

(async function demarrage() {
  const retourGmail = new URLSearchParams(location.search).get("gmail") === "ok";
  if (retourGmail) {
    history.replaceState(null, "", "/");
    toast("Gmail connecté ✓ — tes emails partiront directement.");
  }
  let u = {};
  try { u = await api("/api/moi"); } catch (e) { /* non connecté : géré par api() */ }
  if (u.email) $("#utilisateurEmail").textContent = u.email;
  if (u.admin) $("#navComptes").hidden = false;
  try { await chargerReglages(); } catch (e) { /* réglages indisponibles */ }

  // Assistant de bienvenue : UNIQUEMENT au setup du compte (première connexion).
  if (u.onboarding_a_faire) {
    ouvrirOnboarding(gmailOauth ? "linkedin" : "gmail");
  } else if (retourGmail && sessionStorage.getItem("ob_encours")) {
    // On revient de la connexion Gmail lancée PENDANT l'assistant : on enchaîne
    // sur l'étape LinkedIn. (Une connexion Gmail lancée depuis les Réglages, elle,
    // ne rouvre pas l'assistant.)
    ouvrirOnboarding("linkedin");
  }
})();

// Recherche améliorée : confirmation dès qu'on coche (consomme des crédits).
$("#fRechercheAmelioree")?.addEventListener("change", (e) => {
  if (e.target.checked &&
      !confirm("Êtes-vous sûr ? La recherche améliorée consomme davantage de crédits FullEnrich (~0,25 crédit par contact trouvé).")) {
    e.target.checked = false;
  }
});

// Types de contrat : bouton « + » pour révéler les autres que CDI.
$("#btnPlusContrats")?.addEventListener("click", () => {
  const supp = $("#contratsSupp");
  if (!supp) return;
  supp.hidden = !supp.hidden;
  $("#btnPlusContrats").textContent = supp.hidden ? "+" : "−";
});
chargerMesContacts();
chargerHistorique();
detecterExtension();
setTimeout(() => {
  const el = $("#etatExtension");
  if (el) el.textContent = extensionPresente ? "installée ✓ (envoi LinkedIn direct actif)" : "non détectée (envoi LinkedIn manuel)";
  majChipsConnexions();   // pastilles d'en-tête : LinkedIn + Gmail
}, 1000);

api("/api/statut").then((s) => {
  if (s.etat === "en_cours") {
    $("#suiviTitre").textContent = "Recherche : " + s.titre;
    $("#blocSuivi").hidden = false;
    $("#btnLancer").disabled = true;
    sondage = setInterval(interrogerStatut, 1500);
  } else if (s.etat === "termine" && s.synthese) {
    afficherResultats(s);
  }
}).catch(() => {});
