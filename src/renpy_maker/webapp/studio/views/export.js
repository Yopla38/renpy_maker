// Export : le projet Ren'Py (titre, résolution, points bloquants, export, vérification, lancement).

import { get, post } from "../api.js";
import { bind, busy, esc, toast } from "../ui.js";

export function render(root, ctx) {
  if (ctx.data.kids) {
    root.innerHTML = `<div class="page"><div class="empty-state"><h2>Lire mon histoire</h2>
      <p>Sur cet appareil, l'histoire se lit directement dans l'application.</p><a class="btn primary" href="#/lecture">▶ Lire</a></div></div>`;
    return;
  }
  root.innerHTML = `<div class="page"><p class="muted">Chargement…</p></div>`;
  let result = null;
  const paint = async () => {
    const info = await get("/api/renpy");
    const s = info.settings || {};
    const title = s.title && s.title !== "Mon histoire" ? s.title : ctx.data.title || s.title;
    root.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Export Ren'Py</h1><p>Le jeu complet : une étiquette par scène, les choix en menus, les images de chaque plan.</p></div></div>
      <div class="stack">
        ${info.blocking.length ? `<div class="notice warn"><b>À régler avant l'export</b><ul class="list small">${info.blocking.map((b) => `<li>${esc(b)}</li>`).join("")}</ul></div>`
          : `<div class="notice ok">Rien ne bloque l'export.</div>`}
        ${info.warnings.length ? `<details class="card"><summary><b>À vérifier</b> (${info.warnings.length})</summary><ul class="list small" style="margin-top:8px">${info.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
        <div class="card stack">
          <p class="section-title">Le jeu</p>
          <div class="row" style="align-items:flex-end">
            <label class="field" style="flex:3;min-width:200px"><span>Titre</span><input type="text" name="title" value="${esc(title || "")}"></label>
            <label class="field" style="flex:1;min-width:90px"><span>Largeur</span><input type="number" name="width" value="${esc(s.width)}" min="320" max="7680"></label>
            <label class="field" style="flex:1;min-width:90px"><span>Hauteur</span><input type="number" name="height" value="${esc(s.height)}" min="320" max="7680"></label>
            <button class="btn" data-act="save">Enregistrer</button>
          </div>
          <p class="small muted">Dossier du projet : <code>${esc(info.project_dir)}</code></p>
          ${info.sdk_found ? "" : `<p class="notice small">SDK Ren'Py introuvable : l'export écrit le projet, mais ne peut ni le vérifier ni le lancer (réglez <code>renpy.sdk_dir</code> dans config.yaml).</p>`}
        </div>
        <div class="row">
          <button class="btn primary" data-act="export" ${info.blocking.length ? "disabled" : ""}>Créer le jeu</button>
          <button class="btn" data-act="launch" ${info.sdk_found ? "" : "disabled"}>▶ Lancer dans Ren'Py</button>
        </div>
        <div id="result">${result || ""}</div>
      </div></div>`;
  };
  paint().catch((e) => { root.innerHTML = `<div class="page"><div class="notice warn">${esc(e.message)}</div></div>`; });

  bind(root, {
    save: (el) => busy(el, async () => {
      const v = (n) => root.querySelector(`[name=${n}]`).value;
      await post("/api/renpy/settings", { title: v("title"), width: +v("width"), height: +v("height") });
      toast("Réglages du jeu enregistrés");
      await paint();
    }),
    export: (el) => busy(el, async () => {
      const res = await post("/api/facile/export");
      const lint = res.lint || {};
      result = `<div class="card stack">
        <div class="notice ok"><b>Jeu créé</b> : ${esc(res.export.images)} image(s), ${esc(res.export.files.join(", "))}.</div>
        ${lint.skipped ? `<p class="notice small">${esc(lint.skipped)}</p>`
          : lint.ok ? `<div class="notice ok">Vérification Ren'Py : aucun problème.</div>`
          : `<div class="notice warn"><b>Vérification Ren'Py</b><pre class="small" style="white-space:pre-wrap">${esc([...(lint.errors || []), ...(lint.tail || [])].join("\n"))}</pre></div>`}
      </div>`;
      toast("Jeu créé");
      await paint();
    }),
    launch: (el) => busy(el, async () => { await post("/api/facile/launch"); toast("Ren'Py se lance dans une autre fenêtre"); }),
  });
}
