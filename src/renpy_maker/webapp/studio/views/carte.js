// Carte : la forme de l'histoire. Les scènes, les chemins qui les relient, ce qui reste à faire.

import { post, run } from "../api.js";
import { bind, busy, confirmDialog, dialog, esc, formDialog, toast, thumb, lightbox, plural } from "../ui.js";
import { sceneById, sceneImage, sceneState } from "../app.js";

const TODO = [
  ["idee", "Le cadre de l'histoire", "#/commencer"],
  ["style", "Le style des images", "#/commencer"],
  ["personnages", "Les personnages dessinés", "#/personnages"],
  ["lieux", "Les lieux dessinés", "#/lieux"],
  ["tenues", "Les tenues dessinées", "#/personnages"],
  ["histoire", "Les répliques écrites", "#/scene"],
  ["images", "Les images des scènes", "#/scene"],
  ["carte", "La carte vérifiée", null],
];

let selected = null; // scène sélectionnée (garde la sélection d'un rendu à l'autre)

export function render(root, ctx) {
  const { data } = ctx;
  const map = data.map || { nodes: [], edges: [], routes: [], problems: [] };
  if (selected && !map.nodes.some((n) => n.id === selected)) selected = null;
  root.innerHTML = `
    <div class="split">
      <div class="work"><div class="map-wrap">
        <div id="cy" aria-label="Carte de l'histoire"></div>
        <div class="map-tools">
          <button class="btn ai small" data-act="ai">Écrire avec l'IA</button>
          <button class="btn small" data-act="fit">Recentrer</button>
        </div>
        <div class="legend">
          <span><i style="background:#A9B0C2"></i>suite</span>
          <span><i style="background:#D9512C"></i>choix</span>
          <span><i style="border:2px dashed #E0A526"></i>ligne ouverte</span>
          <span><i style="border:3px double #F2EDE3"></i>fin</span>
        </div>
      </div></div>
      <aside class="side" id="map-side"></aside>
    </div>`;
  const side = root.querySelector("#map-side");
  const cy = drawMap(root.querySelector("#cy"), data, (sid) => { selected = sid; panel(); },
                     (sid) => ctx.go(`#/scene/${encodeURIComponent(sid)}`));
  const panel = () => {
    side.innerHTML = selected ? scenePanel(data, selected) : overview(data);
    cy.$("node").removeClass("sel");
    if (selected) cy.$id(selected).addClass("sel");
  };
  panel();

  const handlers = {
    fit: () => cy.fit(undefined, 40),
    zoom: (el) => lightbox(el.dataset.src),
    ai: () => aiMenu(ctx),
    unselect: () => { selected = null; panel(); },
    open: (el) => ctx.go(`#/scene/${encodeURIComponent(el.dataset.sid)}`),
    read: (el) => ctx.go(`#/lecture/${encodeURIComponent(el.dataset.sid)}`),
    route: (el) => {
      const path = JSON.parse(el.dataset.path);
      cy.elements().removeClass("on");
      path.forEach((id, i) => {
        cy.$id(id).addClass("on");
        if (i) cy.edges(`[source = "${path[i - 1]}"][target = "${id}"]`).addClass("on");
      });
    },
    "add-choice": (el) => addChoice(ctx, el.dataset.sid),
    "rename-choice": async (el) => {
      const { sid, target, label } = el.dataset;
      const v = await formDialog({ title: "Renommer le choix", fields: [{ name: "label", label: "Texte du choix", value: label, required: true }] });
      if (!v) return;
      await post("/api/recit/label", { scene: sid, target, label: v.label });
      toast("Choix renommé");
      await ctx.refresh();
    },
    "remove-choice": async (el) => {
      const { sid, target } = el.dataset;
      const sc = sceneById(sid);
      const rest = (sceneState(sid).choices || []).filter((c) => c.target !== target);
      if (!(await confirmDialog("Retirer ce choix", "Le chemin disparaît de la carte. La scène visée reste dans l'histoire.", "Retirer", "danger"))) return;
      await post("/api/facile/map/choices", { scene: sid, choices: rest.map((c) => ({ label: c.label, target: c.target })) });
      toast(`Choix retiré de « ${sc?.title || sid} »`);
      await ctx.refresh();
    },
    rejoin: async (el) => {
      const sid = el.dataset.sid;
      const options = data.scenes.filter((s) => s.id !== sid).map((s) => ({ value: s.id, label: `${s.title} (chapitre ${s.chapter})` }));
      const v = await formDialog({ title: "Rejoindre une autre scène", intro: "Après cette scène, l'histoire continue dans la scène choisie.",
                                   fields: [{ name: "target", label: "Continuer dans", type: "select", options }] });
      if (!v) return;
      await post("/api/facile/reshape", { action: "rejoin", scene: sid, target: v.target });
      await ctx.refresh();
    },
    finish: async (el) => { await post("/api/recit/finish", { scene: el.dataset.sid }); toast("C'est une fin de l'histoire."); await ctx.refresh(); },
    reopen: async (el) => { await post("/api/recit/reopen", { scene: el.dataset.sid }); toast("La ligne attend de nouveau sa suite."); await ctx.refresh(); },
    detach: async (el) => {
      if (!(await confirmDialog("Ranger dans la réserve", "La scène (et la route qui la suit) quitte la carte, sans être effacée : vous pourrez la rattacher plus tard.", "Ranger"))) return;
      await post("/api/facile/reshape", { action: "detach", scene: el.dataset.sid });
      selected = null;
      await ctx.refresh();
    },
    attach: async (el) => {
      const options = data.scenes.map((s) => ({ value: s.id, label: s.title }));
      const v = await formDialog({ title: "Rattacher depuis la réserve", fields: [
        { name: "scene", label: "Après la scène", type: "select", options },
        { name: "label", label: "Texte du choix qui y mène", value: "Autre chemin", required: true }] });
      if (!v) return;
      await post("/api/facile/reshape", { action: "attach", scene: v.scene, block: el.dataset.block, label: v.label });
      await ctx.refresh();
    },
    validate: (el) => busy(el, async () => {
      const res = await post("/api/facile/map/validate");
      toast(res.problems?.length ? "Carte vérifiée. Des impasses restent à corriger." : "Carte vérifiée : tous les chemins mènent quelque part.");
      await ctx.refresh();
    }),
    live: async (el) => {
      await post("/api/recit/current", { scene: el.dataset.sid, follow: false });
      ctx.go(`#/scene/${encodeURIComponent(el.dataset.sid)}/suite`);
    },
  };
  bind(root, handlers);
  return () => cy.destroy();
}

// ---------- Dessin de la carte ----------
function drawMap(container, data, onSelect, onOpen) {
  const map = data.map;
  const current = data.recit?.current;
  const lived = new Set((data.recit?.path || []).map((p) => p.scene));
  // Colonnes par profondeur (début à gauche), scènes inatteignables dans une dernière colonne.
  const cols = new Map();
  let maxDepth = 0;
  for (const n of map.nodes) if (n.reachable) maxDepth = Math.max(maxDepth, n.depth ?? 0);
  for (const n of map.nodes) {
    const d = n.reachable ? n.depth ?? 0 : maxDepth + 1;
    if (!cols.has(d)) cols.set(d, []);
    cols.get(d).push(n.id);
  }
  const pos = {};
  // Assez d'écart entre deux colonnes pour lire le texte des choix posé sur les flèches.
  for (const [d, ids] of cols) ids.forEach((id, i) => { pos[id] = { x: d * 360, y: (i - (ids.length - 1) / 2) * 160 }; });

  const elements = [
    ...map.nodes.map((n) => {
      const sc = sceneById(n.id);
      const img = sceneImage(sc);
      const cls = [n.ending && "ending", n.open && "open", !n.reachable && "lost", n.id === current && "current",
                   lived.has(n.id) && "lived", img ? "img" : "noimg"].filter(Boolean).join(" ");
      return { group: "nodes", data: { id: n.id, label: n.title || n.id, img }, position: pos[n.id], classes: cls };
    }),
    ...map.edges.filter((e) => map.nodes.some((n) => n.id === e.target)).map((e, i) => ({
      group: "edges", data: { id: `e${i}`, source: e.source, target: e.target, label: e.label || "" },
      classes: e.kind === "choice" ? "choice" : "next",
    })),
  ];
  const cy = cytoscape({
    container, elements, layout: { name: "preset" }, wheelSensitivity: 0.25, minZoom: 0.2, maxZoom: 2.5,
    style: [
      { selector: "node", style: {
        shape: "round-rectangle", width: 160, height: 90, "background-color": "#343B50", "border-width": 2,
        "border-color": "#A9B0C2", label: "data(label)", color: "#F2EDE3", "font-size": 13, "font-weight": 600,
        "font-family": "Hanken Grotesk, system-ui, sans-serif", "text-valign": "bottom", "text-margin-y": 8,
        "text-wrap": "ellipsis", "text-max-width": 170 } },
      { selector: "node.img", style: { "background-image": "data(img)", "background-fit": "cover", "background-clip": "node" } },
      { selector: "node.ending", style: { "border-width": 5, "border-style": "double", "border-color": "#F2EDE3" } },
      { selector: "node.open", style: { "border-style": "dashed", "border-color": "#E0A526", "border-width": 3 } },
      { selector: "node.lost", style: { opacity: 0.4 } },
      { selector: "node.current", style: { "underlay-color": "#E0A526", "underlay-opacity": 0.55, "underlay-padding": 7 } },
      { selector: "node.sel", style: { "border-color": "#E0A526", "border-width": 4 } },
      { selector: "node.on", style: { "border-color": "#F4DE9C", "border-width": 4 } },
      { selector: "edge", style: { width: 2, "curve-style": "bezier", "target-arrow-shape": "triangle",
        "line-color": "#A9B0C2", "target-arrow-color": "#A9B0C2", "arrow-scale": 1.1 } },
      { selector: "edge.choice", style: { "line-color": "#D9512C", "target-arrow-color": "#D9512C", width: 2.5,
        label: "data(label)", color: "#F2EDE3", "font-size": 12, "text-background-color": "#1A1E2A",
        "text-background-opacity": 0.9, "text-background-padding": 3, "text-wrap": "wrap", "text-max-width": 150,
        "font-family": "Hanken Grotesk, system-ui, sans-serif" } },
      { selector: "edge.on", style: { width: 5, "line-color": "#F4DE9C", "target-arrow-color": "#F4DE9C" } },
    ],
  });
  cy.fit(undefined, 50);
  if (cy.zoom() > 1.2) { cy.zoom(1.2); cy.center(); }
  // Grande histoire ou petit écran : on garde des titres lisibles, en partant du début (on fait glisser pour voir la suite).
  if (cy.zoom() < 0.6 && map.start) {
    cy.zoom(0.6);
    const start = cy.$id(map.start).position();
    cy.pan({ x: 90 - start.x * 0.6, y: container.clientHeight / 2 - start.y * 0.6 });
  }
  cy.on("tap", "node", (e) => onSelect(e.target.id()));
  cy.on("dbltap", "node", (e) => onOpen(e.target.id()));
  cy.on("tap", (e) => { if (e.target === cy) onSelect(null); });
  return cy;
}

// ---------- Panneau : vue d'ensemble ----------
function overview(data) {
  const map = data.map;
  const done = data.done || {};
  const titles = Object.fromEntries(data.scenes.map((s) => [s.id, s.title]));
  const openLines = data.scenes.filter((s) => sceneState(s.id).open);
  const routes = (map.routes || []).map((r) => `
    <li class="route-item" data-act="route" data-path='${esc(JSON.stringify(r.path))}'>
      <span>${r.path.map((id) => esc(titles[id] || id)).join(" → ")}</span>
      <span class="tag ${r.ending ? "fin" : "warn"}">${r.ending ? "fin" : "impasse"}</span></li>`).join("");
  const nTodo = TODO.filter(([k]) => !done[k]).length;
  return `
    <div><h2>${esc(data.title || "Votre histoire")}</h2>
      <p class="muted small">${plural(data.scenes.length, "scène", "scènes")} · ${plural((map.routes || []).length, "chemin", "chemins")} · ${plural(data.characters.length, "personnage", "personnages")}</p>
      <p class="muted small">Touchez une scène pour agir dessus, deux fois pour l'ouvrir.</p></div>
    ${map.problems?.length ? `<div class="notice warn"><b>À corriger</b><ul class="list small">${map.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>` : ""}
    ${openLines.length ? `<section><p class="section-title">Lignes qui attendent leur suite</p><ul class="list">${openLines.map((s) => `
      <li class="exit"><span class="label">${esc(s.title)}</span><button class="btn small ai" data-act="live" data-sid="${esc(s.id)}">Continuer</button></li>`).join("")}</ul></section>` : ""}
    <section><p class="section-title">Reste à faire ${nTodo ? `(${nTodo})` : ""}</p>
      <ul class="list checklist">${TODO.map(([k, label, href]) => `
        <li class="${done[k] ? "done" : ""}"><span class="dot">${done[k] ? "✓" : ""}</span>
          ${href && !done[k] ? `<a href="${href}">${esc(label)}</a>` : `<span>${esc(label)}</span>`}
          ${k === "carte" && !done[k] ? `<button class="btn small" data-act="validate">Vérifier</button>` : ""}</li>`).join("")}</ul></section>
    <section><p class="section-title">Chemins de l'histoire</p>
      ${routes ? `<ul class="list">${routes}</ul>${map.routes_truncated ? `<p class="small muted">Il y en a trop pour les lister tous.</p>` : ""}` : `<p class="muted small">Aucun chemin pour l'instant.</p>`}</section>
    ${(data.reserve || []).length ? `<section><p class="section-title">Réserve</p><ul class="list">${data.reserve.map((b) => `
      <li class="exit"><span class="label">${esc(b.title || b.id)} <small class="muted">${plural((b.scenes || []).length, "scène", "scènes")}</small></span>
      <button class="btn small" data-act="attach" data-block="${esc(b.id)}">Rattacher</button></li>`).join("")}</ul></section>` : ""}`;
}

// ---------- Panneau : une scène ----------
function scenePanel(data, sid) {
  const sc = sceneById(sid);
  const node = data.map.nodes.find((n) => n.id === sid) || {};
  const st = sceneState(sid);
  const title = (id) => sceneById(id)?.title || id;
  const choices = st.choices || [];
  const nImages = (sc.plans || []).filter((p) => p.image).length;
  let suite;
  if (choices.length) {
    suite = choices.map((c) => `
      <li class="exit"><span class="arrow">↳</span><span class="label"><b>${esc(c.label || "Continuer")}</b><br><small class="muted">vers ${esc(title(c.target))}</small></span>
        <button class="btn quiet small" data-act="rename-choice" data-sid="${esc(sid)}" data-target="${esc(c.target)}" data-label="${esc(c.label || "")}" title="Renommer">✎</button>
        <button class="btn quiet small" data-act="remove-choice" data-sid="${esc(sid)}" data-target="${esc(c.target)}" title="Retirer">✕</button></li>`).join("");
  } else if (st.next) {
    suite = `<li class="exit"><span class="arrow">→</span><span class="label">continue vers <b>${esc(title(st.next))}</b></span></li>`;
  } else if (node.ending) {
    suite = `<li class="exit"><span class="tag fin">fin</span><span class="label">L'histoire se termine ici.</span></li>`;
  } else {
    suite = `<li class="exit"><span class="tag open">ouverte</span><span class="label">Cette ligne attend sa suite.</span></li>`;
  }
  return `
    <div class="row between"><button class="btn quiet small" data-act="unselect">← Vue d'ensemble</button></div>
    ${thumb(sceneImage(sc), "", "Pas encore d'image")}
    <div><p class="section-title">Chapitre ${esc(sc.chapter)} · ${esc(sc.chapter_title || "")}</p><h2>${esc(sc.title)}</h2>
      <p class="muted">${esc(sc.summary || "")}</p>
      <div class="chips">
        ${node.ending ? `<span class="tag fin">fin</span>` : ""}${node.open ? `<span class="tag open">ligne ouverte</span>` : ""}
        ${node.reachable === false ? `<span class="tag warn">inatteignable</span>` : ""}
        <span class="tag">${plural((sc.dialogue || []).length, "réplique", "répliques")}</span>
        <span class="tag ${nImages ? "ok" : ""}">${plural(nImages, "image", "images")}</span></div></div>
    <div class="row"><button class="btn primary" data-act="open" data-sid="${esc(sid)}">Ouvrir la scène</button>
      <button class="btn" data-act="read" data-sid="${esc(sid)}">▶ Lire d'ici</button></div>
    <section><p class="section-title">Après cette scène</p><ul class="list">${suite}</ul></section>
    <section class="stack">
      <div class="row">
        ${choices.length < 4 ? `<button class="btn small" data-act="add-choice" data-sid="${esc(sid)}">＋ Ajouter un choix</button>` : ""}
        ${!choices.length ? `<button class="btn small" data-act="rejoin" data-sid="${esc(sid)}">Rejoindre une scène…</button>` : ""}
        ${node.open ? `<button class="btn small ai" data-act="live" data-sid="${esc(sid)}">Continuer avec l'IA</button>` : ""}
      </div>
      <div class="row">
        ${!node.ending && !choices.length ? `<button class="btn small" data-act="finish" data-sid="${esc(sid)}">Terminer l'histoire ici</button>` : ""}
        ${(node.ending || st.next) && !choices.length ? `<button class="btn small" data-act="reopen" data-sid="${esc(sid)}">Rouvrir la ligne</button>` : ""}
        ${node.id !== data.map.start ? `<button class="btn quiet small" data-act="detach" data-sid="${esc(sid)}">Ranger dans la réserve</button>` : ""}
      </div>
    </section>`;
}

// ---------- Actions ----------
async function addChoice(ctx, sid) {
  const { data } = ctx;
  const st = sceneState(sid);
  const options = [{ value: "__new", label: "＋ Une nouvelle scène" },
    ...data.scenes.filter((s) => s.id !== sid).map((s) => ({ value: s.id, label: s.title }))];
  const v = await formDialog({
    title: "Ajouter un choix", intro: "Le joueur choisira entre les chemins qui partent de cette scène.",
    fields: [
      { name: "label", label: "Texte du choix", placeholder: "Par exemple : Ouvrir la porte", required: true },
      { name: "target", label: "Il mène à", type: "select", options },
      { name: "title", label: "Titre de la nouvelle scène", hint: "Seulement pour une nouvelle scène" },
      { name: "summary", label: "Ce qui s'y passe", type: "textarea", rows: 2, hint: "Seulement pour une nouvelle scène" },
    ],
  });
  if (!v) return;
  const items = (st.choices || []).map((c) => ({ label: c.label, target: c.target }));
  // Premier choix : la suite d'avant reste possible, sous le nom « Continuer ».
  if (!items.length && st.next) items.push({ label: "Continuer", target: st.next });
  if (v.target === "__new") {
    if (!v.title.trim()) return toast("Donnez un titre à la nouvelle scène", "error");
    items.push({ label: v.label, new: { title: v.title, summary: v.summary } });
  } else items.push({ label: v.label, target: v.target });
  await post("/api/facile/map/choices", { scene: sid, choices: items });
  toast("Choix ajouté");
  await ctx.refresh();
}

async function aiMenu(ctx) {
  const { data } = ctx;
  const counts = data.counts || [3, 4, 5, 6];
  const choice = await dialog({
    title: "Écrire avec l'IA",
    html: `<p class="muted">L'IA écrit, vous gardez la main : tout reste modifiable ensuite.</p>
      <div class="stack">
        <div class="card"><b>Ajouter un chapitre</b><p class="small muted">Le plan des scènes, leurs répliques et les nouveaux personnages ou lieux.</p>
          <div class="row"><label class="field" style="flex:1"><span>Nombre de scènes</span><select name="count">${counts.map((n) => `<option ${n === 4 ? "selected" : ""}>${n}</option>`).join("")}</select></label>
          <label class="field" style="flex:3"><span>Consigne (facultatif)</span><input type="text" name="guidance" placeholder="Par exemple : la tempête se lève"></label></div></div>
      </div>`,
    buttons: [
      { label: "Annuler", value: null },
      { label: "Répliques manquantes", value: () => ({ path: "/api/facile/dialogues", label: "Écriture des répliques" }) },
      { label: "Éléments manquants", value: () => ({ path: "/api/facile/complete", label: "Personnages et lieux" }) },
      { label: "Images manquantes", value: () => ({ path: "/api/facile/plan/images", label: "Images des scènes" }) },
      { label: "Ajouter le chapitre", kind: "primary", value: (root) => ({
        path: "/api/facile/chapter/add", label: "Nouveau chapitre",
        body: { count: +root.querySelector("[name=count]").value, guidance: root.querySelector("[name=guidance]").value } }) },
    ],
    wide: true,
  });
  if (!choice) return;
  try {
    await run(choice.path, choice.body || {}, choice.label);
    toast(`${choice.label} : terminé`);
  } finally {
    await ctx.refresh();
  }
}
