/* Skaelia Prospection — logique client (version simplifiée) */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

let sondage = null;
let resultats = null;
let tableActive = "contacts";

/* ---------------- utilitaires ---------------- */

function toast(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
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

/* ---------------- lancement & suivi ---------------- */

async function lancerRecherche() {
  const poste = $("#fPoste").value.trim();
  const lieu = $("#fLieu").value.trim();
  if (!poste) { toast("Indiquez le poste recherché."); $("#fPoste").focus(); return; }
  try {
    await post("/api/lancer", { poste, lieu });
  } catch (e) { toast(e.message); return; }

  $("#btnLancer").disabled = true;
  $("#vueResultats").hidden = true;
  $("#suiviTitre").textContent = `Recherche : ${poste}${lieu ? " — " + lieu : ""}`;
  $("#blocSuivi").hidden = false;
  $("#journal").innerHTML = "";
  $("#suiviSpinner").style.display = "";
  if (sondage) clearInterval(sondage);
  sondage = setInterval(interrogerStatut, 1500);
}

$("#btnLancer").addEventListener("click", lancerRecherche);
$("#fPoste").addEventListener("keydown", (e) => { if (e.key === "Enter") lancerRecherche(); });
$("#fLieu").addEventListener("keydown", (e) => { if (e.key === "Enter") lancerRecherche(); });

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

/* ---------------- résultats ---------------- */

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
}

$$(".onglet").forEach((b) =>
  b.addEventListener("click", () => {
    $$(".onglet").forEach((x) => x.classList.remove("actif"));
    b.classList.add("actif");
    tableActive = b.dataset.table;
    dessinerTable();
  })
);

function badgeStatutEmail(statut) {
  if (!statut) return "";
  if (statut === "deliverable") return '<span class="badge badge-ok">vérifié</span>';
  if (statut === "risky") return '<span class="badge badge-moyen">incertain</span>';
  return `<span class="badge badge-neutre">${echapper(statut)}</span>`;
}

/* Offres de l'entreprise d'un contact : liste "titre (lien)" */
function offresDeLEntreprise(nomEntreprise) {
  const offres = resultats.offres.filter((o) => o.entreprise === nomEntreprise);
  if (!offres.length) return "";
  return offres.slice(0, 4).map((o) =>
    `<div class="offre-ligne">
       <a class="offre-lien" href="${echapper(o.url)}" target="_blank" rel="noopener">
         ${o.nouveau ? '<span class="badge badge-nouveau">NOUVEAU</span> ' : ""}${echapper(o.titre)}
       </a>${o.date ? `<span class="offre-date">${echapper(o.date)}</span>` : ""}
     </div>`).join("") + (offres.length > 4 ? `<span class="badge badge-neutre">+${offres.length - 4} autres</span>` : "");
}

function dessinerTable() {
  const table = $("#tableResultats");
  if (!resultats) return;

  if (tableActive === "contacts") {
    if (!resultats.contacts.length) {
      table.innerHTML = "<tbody><tr><td style='padding:24px'>Aucun contact trouvé pour cette recherche.</td></tr></tbody>";
      return;
    }
    table.innerHTML =
      "<thead><tr><th>Contact</th><th>Poste du contact</th><th>Entreprise</th><th>Recrute actuellement</th><th>LinkedIn</th><th>Email</th><th></th></tr></thead><tbody>" +
      resultats.contacts.map((c) => `<tr>
        <td><strong>${echapper(c.nom)}</strong></td>
        <td>${echapper(c.poste)}</td>
        <td>${echapper(c.entreprise)}</td>
        <td class="cellule-postes">${offresDeLEntreprise(c.entreprise)}</td>
        <td><a href="${echapper(c.url_linkedin)}" target="_blank" rel="noopener">Profil</a></td>
        <td>${echapper(c.email || "")}</td>
        <td>${badgeStatutEmail(c.statut_email)}</td></tr>`).join("") +
      "</tbody>";
  } else {
    table.innerHTML =
      "<thead><tr><th></th><th>Poste</th><th>Entreprise</th><th>Lieu</th><th>Contrat</th><th>Salaire</th><th>Publiée</th><th>Source</th></tr></thead><tbody>" +
      resultats.offres.map((o) => `<tr>
        <td>${o.nouveau ? '<span class="badge badge-nouveau">NOUVEAU</span>' : ""}</td>
        <td><a href="${echapper(o.url)}" target="_blank" rel="noopener">${echapper(o.titre)}</a></td>
        <td>${echapper(o.entreprise)}</td><td>${echapper(o.lieu)}</td>
        <td>${echapper(o.contrat)}</td><td>${echapper(o.salaire)}</td>
        <td>${echapper(o.date)}</td><td>${echapper(o.source)}</td></tr>`).join("") +
      "</tbody>";
  }
}

/* ---------------- compte ---------------- */

$("#btnDeconnexion").addEventListener("click", async () => {
  await post("/api/deconnexion");
  location.href = "/connexion";
});

$("#btnChangerMdp").addEventListener("click", () => {
  $("#msgMdp").hidden = true;
  $("#mAncien").value = ""; $("#mNouveau").value = "";
  $("#voileMdp").hidden = false;
});
$("#btnFermerMdp").addEventListener("click", () => { $("#voileMdp").hidden = true; });
$("#btnValiderMdp").addEventListener("click", async () => {
  try {
    await post("/api/changer-mdp", { ancien: $("#mAncien").value, nouveau: $("#mNouveau").value });
    $("#voileMdp").hidden = true;
    toast("Mot de passe changé ✓");
  } catch (e) {
    const msg = $("#msgMdp");
    msg.textContent = e.message; msg.hidden = false;
  }
});

/* ---------------- réglages ---------------- */

async function chargerReglages() {
  const r = await api("/api/reglages");
  $("#rExclusions").value = (r.exclusions_cabinets || []).join("\n");
  $("#etatCle").textContent = r.usebouncer_configuree ? "— configurée ✓" : "— non configurée";
  $("#etatSmtp").textContent = r.smtp_configure ? "configuré ✓" : "non configuré";
  return r;
}

$("#btnReglages").addEventListener("click", async () => {
  await chargerReglages();
  $("#rCle").value = ""; $("#rSmtpMdp").value = "";
  $("#voileReglages").hidden = false;
});
$("#btnFermerReglages").addEventListener("click", () => { $("#voileReglages").hidden = true; });

$("#btnSauverReglages").addEventListener("click", async () => {
  const corps = {
    exclusions_cabinets: $("#rExclusions").value.split("\n").map((l) => l.trim()).filter(Boolean),
  };
  if ($("#rCle").value.trim()) corps.usebouncer_api_key = $("#rCle").value.trim();
  if ($("#rSmtpHote").value.trim() || $("#rSmtpUtilisateur").value.trim()) {
    corps.smtp = {
      hote: $("#rSmtpHote").value,
      port: $("#rSmtpPort").value,
      utilisateur: $("#rSmtpUtilisateur").value,
      mot_de_passe: $("#rSmtpMdp").value,
    };
  }
  await post("/api/reglages", corps);
  toast("Réglages enregistrés ✓");
  $("#voileReglages").hidden = true;
});

/* ---------------- démarrage ---------------- */

api("/api/moi").then((u) => { $("#utilisateurEmail").textContent = u.email; }).catch(() => {});
chargerReglages().then((r) => {
  const config = r.smtp_configure;
  // pré-remplir l'hôte/utilisateur si déjà connus ? (non exposés — champs laissés vides)
}).catch(() => {});

// Reprendre une recherche en cours ou des résultats existants après rechargement
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
