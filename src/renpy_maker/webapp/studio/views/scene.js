// Scènes : le scénario et le storyboard côte à côte. Chaque réplique avec l'image qui l'accompagne ;
// en bas, la suite de la scène et « Continuer avec l'IA » (la boucle du récit).

import { post, run } from "../api.js";
import { autosize, bind, busy, confirmDialog, esc, formDialog, lightbox, plural, thumb, toast } from "../ui.js";
import { sceneById, sceneImage, sceneState, store } from "../app.js";
import { openShot } from "./shot.js";

const NARRATOR = "Narration";
const drafts = {}; // proposition en cours, par scène (survit à un nouveau rendu)

export function render(root, ctx) {
  const { data, params } = ctx;
  if (!data.scenes.length) {
    root.innerHTML = `<div class="page"><div class="empty-state"><h2>Pas encore de scène</h2>
      <p>Commencez l'histoire : l'IA peut écrire le plan, ou vous pouvez l'écrire en jouant.</p>
      <a class="btn primary" href="#/commencer">Commencer</a></div></div>`;
    return;
  }
  let sid = params[0];
  if (!sceneById(sid)) sid = (store.lastScene && sceneById(store.lastScene) ? store.lastScene : null) || data.recit?.current || data.scenes[0].id;
  store.lastScene = sid;
  const sc = sceneById(sid);

  root.innerHTML = `
    <div class="scene-layout">
      <nav class="scene-list" aria-label="Scènes">${sceneList(data, sid)}</nav>
      <div class="scene-main"><div class="page" id="scene-page"></div></div>
    </div>`;
  const page = root.querySelector("#scene-page");
  const paint = () => {
    page.innerHTML = head(data, sc) + toolbar(sc) + `<div class="board">${board(data, sc)}</div>` + suite(data, sc);
    page.querySelectorAll(".line textarea").forEach(autosize);
  };
  paint();
  root.querySelector(`.scene-link[aria-current="true"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  if (params[1] === "suite") requestAnimationFrame(() => page.querySelector("#suite")?.scrollIntoView({ behavior: "smooth" }));

  const refreshKeep = async () => { await ctx.refresh(); };

  bind(root, {
    zoom: (el) => lightbox(el.dataset.src),
    // --- en-tête ---
    "meta-title": async (el) => {
      await post("/api/facile/scene/meta", { scene: sid, title: el.value });
      toast("Titre enregistré");
      await ctx.refresh({ render: false });
      root.querySelector(`.scene-link[aria-current="true"] b`).textContent = el.value;
    },
    "meta-summary": async (el) => { await post("/api/facile/scene/meta", { scene: sid, summary: el.value }); toast("Résumé enregistré"); await ctx.refresh({ render: false }); },
    // --- répliques ---
    "line-save": async (el) => {
      const row = el.closest(".line");
      const i = +row.dataset.line;
      const speaker = row.querySelector("select").value;
      const text = row.querySelector("textarea").value.trim();
      if (!text) return toast("Une réplique ne peut pas être vide", "error");
      await post("/api/facile/dialogue/line", { scene: sid, line: i, speaker, text });
      sc.dialogue[i] = { ...sc.dialogue[i], speaker, text };
      row.classList.toggle("voice", speaker === NARRATOR);
      row.classList.add("saved");
      setTimeout(() => row.classList.remove("saved"), 1200);
    },
    "line-branch": async (el) => {
      const i = +el.dataset.line;
      const v = await formDialog({
        title: "Vivre autrement après cette réplique",
        intro: "La scène se sépare ici. Ce qui suivait reste un chemin possible (« Continuer ») ; le nouveau chemin est une ligne ouverte à écrire.",
        fields: [{ name: "label", label: "Texte du nouveau choix", placeholder: "Par exemple : Refuser", required: true }],
        ok: "Séparer ici",
      });
      if (!v) return;
      const res = await post("/api/recit/branch", { scene: sid, line: i, label: v.label });
      toast("Nouvelle ligne créée");
      await ctx.refresh({ render: false });
      ctx.go(`#/scene/${encodeURIComponent(res.scene || sid)}/suite`);
    },
    "add-shot": async (el) => {
      const i = +el.dataset.line;
      const plans = (sc.plans || []).map(planItem);
      plans.push({ id: null, from_line: i, text: "" });
      await post("/api/facile/scene/plans", { scene: sid, plans });
      toast("Nouvelle image à partir de cette réplique");
      await refreshKeep();
    },
    "remove-shot": async (el) => {
      const pid = el.dataset.plan;
      if ((sc.plans || []).length < 2) return toast("Une scène garde au moins une image", "error");
      if (!(await confirmDialog("Retirer cette image", "Les répliques restent ; elles s'afficheront avec l'image d'avant.", "Retirer", "danger"))) return;
      await post("/api/facile/scene/plans", { scene: sid, plans: sc.plans.filter((p) => p.id !== pid).map(planItem) });
      await refreshKeep();
    },
    // --- images ---
    draw: (el) => busy(el, async () => {
      await run("/api/recit/draw", { scene: sid, plan: el.dataset.plan }, `Image de « ${sc.title} »`);
      toast("Image dessinée");
      await refreshKeep();
    }),
    shot: (el) => openShot(ctx, sid, el.dataset.plan),
    "draw-missing": (el) => busy(el, async () => {
      const todo = (sc.plans || []).filter((p) => !p.image);
      if (!todo.length) return toast("Toutes les images de la scène sont dessinées");
      for (const p of todo) await run("/api/recit/draw", { scene: sid, plan: p.id }, `Image ${p.id} de « ${sc.title} »`);
      toast(`${plural(todo.length, "image dessinée", "images dessinées")}`);
      await refreshKeep();
    }),
    rewrite: (el) => busy(el, async () => {
      if (sc.dialogue?.length && !(await confirmDialog("Réécrire les répliques", "L'IA réécrit toutes les répliques de cette scène. Les images restent, mais leurs bulles seront à revoir.", "Réécrire"))) return;
      await run("/api/facile/dialogue", { scene: sid }, "Écriture des répliques");
      toast("Répliques écrites");
      await refreshKeep();
    }),
    split: (el) => busy(el, async () => {
      if ((sc.plans || []).some((p) => p.image) && !(await confirmDialog("Proposer un découpage", "L'IA propose un nouveau découpage en images. Les images déjà dessinées des plans conservés restent.", "Proposer"))) return;
      await run("/api/facile/scene/propose", { scene: sid }, "Découpage en images");
      toast("Découpage proposé");
      await refreshKeep();
    }),
    // --- suite ---
    propose: (el) => busy(el, async () => {
      drafts[sid] = await post("/api/recit/propose", { scene: sid, previous: drafts[sid] || null });
      paintSuite();
    }),
    "draft-field": (el) => {
      const d = drafts[sid];
      if (!d) return;
      if (el.name === "keep") d.image.keep = el.checked;
      else if (el.name === "shot") d.image.shot = el.value;
      else d[el.name] = el.value;
    },
    "draft-choice-remove": (el) => { drafts[sid].choices.splice(+el.dataset.i, 1); paintSuite(); },
    direct: (el) => busy(el, async () => {
      const input = page.querySelector("#directive");
      const instruction = input.value.trim();
      if (!instruction) return toast("Écrivez ce qui doit changer", "error");
      const res = await post("/api/recit/direct", { scene: sid, instruction, proposal: drafts[sid] });
      drafts[sid] = res.proposal;
      if (res.reply) toast(res.reply);
      paintSuite();
    }),
    "draft-drop": () => { delete drafts[sid]; paintSuite(); },
    keep: (el) => busy(el, async () => {
      const res = await post("/api/recit/moment", { scene: sid, moment: drafts[sid] });
      delete drafts[sid];
      const target = res.scene || sid;
      if (res.draw && (data.recit?.auto_draw)) {
        run("/api/recit/draw", { scene: target, plan: res.plan }, "Image du moment").then(() => ctx.refresh()).catch((e) => toast(e.message, "error"));
      }
      toast(target !== sid ? "Nouveau lieu : la ligne continue dans une nouvelle scène." : "Moment ajouté");
      await ctx.refresh({ render: false });
      ctx.go(`#/scene/${encodeURIComponent(target)}/suite`);
    }),
    undo: (el) => busy(el, async () => {
      if (!(await confirmDialog("Annuler le dernier moment", "Ses répliques et son image sont retirées.", "Annuler le moment", "danger"))) return;
      const res = await post("/api/recit/undo");
      await ctx.refresh({ render: false });
      ctx.go(`#/scene/${encodeURIComponent(res.scene || sid)}/suite`);
    }),
    "choices-propose": (el) => busy(el, async () => {
      const res = await post("/api/recit/choices/propose", { scene: sid });
      await chooseAmong(ctx, sid, res.choices);
    }),
    "pending-pick": (el) => busy(el, async () => {
      const pending = data.recit.pending;
      await choose(ctx, sid, pending.options, +el.dataset.i);
    }),
    "pending-other": async () => {
      const pending = data.recit.pending;
      const v = await formDialog({ title: "Autre chose…", fields: [{ name: "label", label: "Votre choix", required: true }] });
      if (!v) return;
      const options = [...pending.options.slice(0, 3), v.label];
      await choose(ctx, sid, options, options.length - 1);
    },
    "pending-drop": async () => { await post("/api/recit/options", { drop_pending: true }); await ctx.refresh(); },
    finish: async () => { await post("/api/recit/finish", { scene: sid }); toast("C'est une fin de l'histoire."); await ctx.refresh(); },
    reopen: async () => { await post("/api/recit/reopen", { scene: sid }); toast("La ligne attend de nouveau sa suite."); await ctx.refresh(); },
    goto: (el) => ctx.go(`#/scene/${encodeURIComponent(el.dataset.sid)}`),
  });
  root.addEventListener("keydown", (e) => {
    if (e.target.id === "directive" && e.key === "Enter") { e.preventDefault(); page.querySelector('[data-act="direct"]')?.click(); }
  });

  function paintSuite() {
    const box = page.querySelector("#suite");
    box.outerHTML = suite(data, sc);
  }
}

// ---------- Liste des scènes ----------
function sceneList(data, sid) {
  let html = "";
  let chapter = null;
  for (const s of data.scenes) {
    if (s.chapter !== chapter) {
      chapter = s.chapter;
      html += `<h4>Chapitre ${esc(s.chapter)}${s.chapter_title ? ` · ${esc(s.chapter_title)}` : ""}</h4>`;
    }
    const st = sceneState(s.id);
    const img = sceneImage(s);
    html += `<a class="scene-link" href="#/scene/${encodeURIComponent(s.id)}" aria-current="${s.id === sid}">
      ${img ? `<div class="thumb"><img src="${esc(img)}" alt="" loading="lazy"></div>` : `<div class="thumb empty"></div>`}
      <span><b>${esc(s.title)}</b><small>${plural((s.dialogue || []).length, "réplique", "répliques")}${st.open ? " · ouverte" : st.ending ? " · fin" : (st.choices || []).length ? " · choix" : ""}</small></span></a>`;
  }
  return html;
}

// ---------- En-tête ----------
function head(data, sc) {
  const st = sceneState(sc.id);
  return `<div class="scene-head">
    <p class="section-title">Chapitre ${esc(sc.chapter)}${sc.chapter_title ? ` · ${esc(sc.chapter_title)}` : ""}${sc.route_from ? " · route" : ""}</p>
    <input class="title-input" type="text" value="${esc(sc.title)}" data-change="meta-title" aria-label="Titre de la scène">
    <textarea class="summary-input" rows="2" data-change="meta-summary" aria-label="Ce qui se passe" placeholder="Ce qui se passe dans cette scène…">${esc(sc.summary || "")}</textarea>
    <div class="chips">
      ${sc.location ? `<span class="tag">⌂ ${esc(sc.location)}</span>` : ""}
      ${(sc.characters || []).map((c) => `<span class="tag">☺ ${esc(c)}${st.outfits?.[c] ? ` · ${esc(st.outfits[c])}` : ""}</span>`).join("")}
    </div></div>`;
}

function toolbar(sc) {
  const missing = (sc.plans || []).filter((p) => !p.image).length;
  return `<div class="toolbar">
    <button class="btn ai small" data-act="rewrite">${sc.dialogue?.length ? "Réécrire les répliques" : "Écrire les répliques"}</button>
    ${sc.dialogue?.length ? `<button class="btn ai small" data-act="split">Proposer le découpage en images</button>` : ""}
    ${missing ? `<button class="btn small" data-act="draw-missing">Dessiner les ${plural(missing, "image manquante", "images manquantes")}</button>` : ""}
  </div>`;
}

// ---------- Storyboard ----------
// Même ordre que la lecture : une image seule avant sa réplique, puis l'image normale et ses répliques.
function beats(sc) {
  const lines = sc.dialogue || [];
  const plans = [...(sc.plans || [])].sort((a, b) => a.from_line - b.from_line || (a.pause ? 0 : 1) - (b.pause ? 0 : 1));
  const out = [];
  let cur = null;
  for (let i = 0; i <= lines.length; i++) {
    for (const p of plans.filter((x) => x.from_line === i && x.pause)) out.push({ plan: p, lines: [] });
    for (const p of plans.filter((x) => x.from_line === i && !x.pause)) { cur = { plan: p, lines: [] }; out.push(cur); }
    if (i < lines.length) {
      if (!cur) { cur = { plan: null, lines: [] }; out.push(cur); }
      cur.lines.push(i);
    }
  }
  return out;
}

function board(data, sc) {
  const speakers = [NARRATOR, ...data.characters.map((c) => c.name)];
  const list = beats(sc);
  if (!list.length) return `<div class="empty-state"><p>Pas encore de réplique dans cette scène.</p></div>`;
  return list.map(({ plan, lines }) => `
    <div class="beat">
      <div class="shot ${plan ? "" : "none"}">${plan ? shotCard(sc, plan) : ""}</div>
      <div class="lines">
        ${plan?.pause ? `<div class="speech">${plan.speech ? `<b>${esc(plan.speaker || NARRATOR)}</b> : ${esc(plan.speech)}` : `<i class="muted">Image seule, sans réplique</i>`}</div>` : ""}
        ${lines.map((i) => lineRow(sc, i, speakers)).join("")}
      </div>
    </div>`).join("");
}

function shotCard(sc, plan) {
  return `${thumb(plan.image, "", plan.pause ? "Image seule" : "Image à dessiner")}
    ${plan.text ? `<div class="shot-text">${esc(plan.text)}</div>` : ""}
    <div class="shot-actions">
      <button class="btn small ${plan.image ? "" : "primary"}" data-act="draw" data-plan="${esc(plan.id)}">${plan.image ? "Redessiner" : "Dessiner"}</button>
      <button class="btn small" data-act="shot" data-plan="${esc(plan.id)}" title="Ce que l'on voit, cadrage, références, prompt…">⚙ Régler</button>
      ${(sc.plans || []).length > 1 ? `<button class="btn quiet small" data-act="remove-shot" data-plan="${esc(plan.id)}" title="Retirer cette image">✕</button>` : ""}
    </div>`;
}

function lineRow(sc, i, speakers) {
  const line = sc.dialogue[i];
  const names = speakers.includes(line.speaker) ? speakers : [...speakers, line.speaker];
  const startsShot = (sc.plans || []).some((p) => p.from_line === i && !p.pause);
  return `<div class="line ${line.speaker === NARRATOR ? "voice" : ""}" data-line="${i}">
    <select data-change="line-save" aria-label="Qui parle">${names.map((n) => `<option ${n === line.speaker ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
    <textarea rows="1" data-change="line-save" aria-label="Réplique ${i + 1}">${esc(line.text)}</textarea>
    <div class="line-actions">
      ${!startsShot && i > 0 ? `<button class="btn quiet small" data-act="add-shot" data-line="${i}" title="Une nouvelle image commence à cette réplique">＋ image</button>` : ""}
      <button class="btn quiet small" data-act="line-branch" data-line="${i}" title="Vivre autrement après cette réplique : la scène se sépare ici">⑂ autre suite</button>
    </div>
  </div>`;
}

function planItem(p) {
  return { id: p.id, from_line: p.from_line, text: p.text || "", characters: p.characters?.length ? p.characters : null,
           pause: !!p.pause, speaker: p.speaker || "", speech: p.speech || "" };
}

// ---------- Suite de la scène ----------
function suite(data, sc) {
  const sid = sc.id;
  const st = sceneState(sid);
  const title = (id) => sceneById(id)?.title || id;
  const pending = data.recit?.pending && data.recit.pending.scene === sid ? data.recit.pending : null;
  const canUndo = data.recit?.can_undo && data.recit.current === sid;
  let exits = "";
  if ((st.choices || []).length) {
    exits = `<ul class="list">${st.choices.map((c) => `<li class="exit"><span class="arrow">↳</span><span class="label"><b>${esc(c.label || "Continuer")}</b> <small class="muted">vers ${esc(title(c.target))}</small></span>
      <button class="btn small" data-act="goto" data-sid="${esc(c.target)}">Aller</button></li>`).join("")}</ul>`;
  } else if (st.next) {
    exits = `<div class="exit"><span class="arrow">→</span><span class="label">L'histoire continue dans <b>${esc(title(st.next))}</b></span>
      <button class="btn small" data-act="goto" data-sid="${esc(st.next)}">Aller</button><button class="btn quiet small" data-act="reopen">Rouvrir</button></div>`;
  } else if (st.ending) {
    exits = `<div class="exit"><span class="tag fin">fin</span><span class="label">L'histoire se termine ici.</span><button class="btn small" data-act="reopen">Rouvrir la ligne</button></div>`;
  }
  const open = !!st.open;
  return `<section class="suite" id="suite">
    <div class="row between"><h3>Et ensuite ?</h3><a class="btn quiet small" href="#/carte">Voir sur la carte</a></div>
    ${exits}
    ${pending ? pendingChoices(pending) : ""}
    ${open && !pending ? (drafts[sid] ? proposalCard(data, sc, drafts[sid]) : `
      <div class="card stack">
        <p class="muted">Cette ligne attend sa suite. L'IA propose le moment suivant (voix off, réplique, image, parfois un choix) : vous le gardez, vous le modifiez, ou vous lui dites ce qui doit changer.</p>
        <div class="row">
          <button class="btn ai primary" data-act="propose">Continuer avec l'IA</button>
          <button class="btn small" data-act="choices-propose">Proposer un choix</button>
          <button class="btn quiet small" data-act="finish">Terminer l'histoire ici</button>
          ${canUndo ? `<button class="btn quiet small" data-act="undo">Annuler le dernier moment</button>` : ""}
        </div></div>`) : ""}
  </section>`;
}

function proposalCard(data, sc, d) {
  const cast = [NARRATOR, ...data.characters.map((c) => c.name)];
  const speakerOptions = ["", ...cast].map((n) => `<option value="${esc(n)}" ${n === (d.speaker || "") ? "selected" : ""}>${n ? esc(n) : "(pas de réplique)"}</option>`).join("");
  return `<div class="proposal">
    <div class="row between"><p class="section-title" style="margin:0">Proposition de l'IA</p>
      <button class="btn quiet small" data-act="draft-drop">Écarter</button></div>
    ${d.location ? `<div class="notice"><b>Nouveau lieu :</b> ${esc(d.location.name)}${d.location.description ? ` · <span class="muted">${esc(d.location.description)}</span>` : ""}</div>` : ""}
    <label class="field"><span>Voix off</span><textarea class="voice" name="voix_off" rows="2" data-change="draft-field" placeholder="(facultatif)">${esc(d.voix_off || "")}</textarea></label>
    <div class="row" style="align-items:flex-start">
      <label class="field" style="width:180px"><span>Qui parle</span><select name="speaker" data-change="draft-field">${speakerOptions}</select></label>
      <label class="field" style="flex:1;min-width:220px"><span>Réplique</span><textarea name="text" rows="2" data-change="draft-field">${esc(d.text || "")}</textarea></label>
    </div>
    <div class="stack" style="gap:6px">
      <span class="small" style="font-weight:700">Image</span>
      ${d.image?.can_keep ? `<label class="check"><input type="checkbox" name="keep" data-change="draft-field" ${d.image.keep ? "checked" : ""}><span>Garder l'image d'avant <small class="muted">(rien ne change à l'écran : pas de nouveau dessin)</small></span></label>` : ""}
      <input type="text" name="shot" data-change="draft-field" value="${esc(d.image?.shot || "")}" placeholder="Ce que l'on voit">
      <small class="muted">${esc(d.image?.framing || "")}${d.image?.viewpoint ? ` · point de vue : ${esc(d.image.viewpoint)}` : ""}${d.image?.visible?.length ? ` · à l'image : ${esc(d.image.visible.join(", "))}` : ""}</small>
    </div>
    ${d.choices?.length ? `<div><span class="small" style="font-weight:700">Puis un choix</span><div class="chips">${d.choices.map((c, i) => `<span class="chip">${esc(c)} <a href="#" data-act="draft-choice-remove" data-i="${i}" aria-label="Retirer">✕</a></span>`).join("")}</div></div>` : ""}
    <div class="directive"><input type="text" id="directive" placeholder="Dites ce qui doit changer : « elle est assise », « Tom refuse »…"><button class="btn small" data-act="direct">Appliquer</button></div>
    <div class="row end"><button class="btn" data-act="propose">Une autre proposition</button><button class="btn primary" data-act="keep">Garder ce moment</button></div>
  </div>`;
}

function pendingChoices(pending) {
  return `<div class="proposal">
    <p class="section-title" style="margin:0">Le récit arrive à un choix</p>
    <p class="muted small">Chaque option ouvre une ligne ; vous vivez celle que vous prenez, les autres restent à écrire.</p>
    <div class="stack">${pending.options.map((o, i) => `<button class="btn" data-act="pending-pick" data-i="${i}" style="justify-content:flex-start">${i + 1}. ${esc(o)}</button>`).join("")}</div>
    <div class="row"><button class="btn small" data-act="pending-other">Autre chose…</button><button class="btn quiet small" data-act="pending-drop">Pas maintenant</button></div>
  </div>`;
}

async function choose(ctx, sid, options, picked) {
  const res = await post("/api/recit/choose", { scene: sid, options, picked });
  toast(`${plural(options.length, "ligne ouverte", "lignes ouvertes")} : vous vivez « ${options[picked]} »`);
  await ctx.refresh({ render: false });
  ctx.go(`#/scene/${encodeURIComponent(res.scene)}/suite`);
}

async function chooseAmong(ctx, sid, options) {
  const v = await formDialog({
    title: "Le choix",
    intro: "Modifiez les options si besoin (une par ligne), puis choisissez celle que vous vivez maintenant.",
    fields: [
      { name: "options", label: "Options", type: "textarea", rows: 4, value: options.join("\n") },
      { name: "picked", label: "Vivre maintenant l'option n°", type: "number", value: 1, min: 1, max: 4 },
    ],
    ok: "Choisir",
  });
  if (!v) return;
  const list = v.options.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 4);
  if (list.length < 2) return toast("Il faut au moins deux options", "error");
  const picked = Math.min(Math.max(1, +v.picked || 1), list.length) - 1;
  await choose(ctx, sid, list, picked);
}
