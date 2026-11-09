// Panneau d'une image de scène : ce que l'on voit, cadrage, point de vue, personnages, tenues,
// références, continuité, prompt, LoRA, reprendre une image existante. (La « roue » du récit.)

import { post, run } from "../api.js";
import { bind, busy, drawer, esc, lightbox, thumb, toast } from "../ui.js";
import { sceneById, sceneState, store } from "../app.js";
import { loraEditor, loraHandlers, pickImage } from "./parts.js";

export function openShot(ctx, sid, pid) {
  let dirtyPrompt = false;
  const handle = drawer("Image", (content, h) => {
    const paint = () => {
      const data = store.data;
      const sc = sceneById(sid);
      const plan = (sc?.plans || []).find((p) => p.id === pid);
      if (!plan) { h.close(); return; }
      h.setTitle(`Image · ${sc.title}`);
      content.innerHTML = body(data, sc, plan);
    };
    h.paint = paint;
    paint();
    const reload = async () => { await ctx.refresh({ render: false }); paint(); };
    const plan = () => sceneById(sid).plans.find((p) => p.id === pid);
    bind(content, {
      zoom: (el) => lightbox(el.dataset.src),
      draw: (el) => busy(el, async () => {
        const prompt = dirtyPrompt ? content.querySelector("[name=prompt]").value.trim() : null;
        await run("/api/recit/draw", { scene: sid, plan: pid, prompt }, "Image du moment");
        dirtyPrompt = false;
        toast("Image dessinée");
        await reload();
        ctx.refresh();
      }),
      "shot-save": (el) => busy(el, async () => {
        const characters = [...content.querySelectorAll("[name=visible]:checked")].map((i) => i.value);
        await post("/api/recit/shot", {
          scene: sid, plan: pid, note: content.querySelector("[name=note]").value,
          framing: content.querySelector("[name=framing]").value,
          viewpoint: content.querySelector("[name=viewpoint]")?.value ?? null, characters,
        });
        toast("Réglages de l'image enregistrés : redessinez pour les voir.");
        await reload();
      }),
      outfit: async (el) => {
        await post("/api/recit/outfit", { scene: sid, character: el.dataset.character, outfit: el.value });
        toast(`Tenue de ${el.dataset.character} : ${el.value || "par défaut"}`);
        await reload();
      },
      "ref-toggle": async (el) => {
        const p = plan();
        const excluded = new Set(p.refs.auto.filter((r) => r.excluded).map((r) => r.key));
        excluded.has(el.dataset.key) ? excluded.delete(el.dataset.key) : excluded.add(el.dataset.key);
        await saveRefs(p, [...excluded], extras(p));
      },
      "ref-remove": async (el) => {
        const p = plan();
        await saveRefs(p, excludedKeys(p), extras(p).filter((r) => r !== el.dataset.ref));
      },
      "ref-add": async (el) => {
        if (!el.value) return;
        const p = plan();
        await saveRefs(p, excludedKeys(p), [...extras(p), el.value]);
      },
      continuity: async (el) => {
        await post("/api/facile/plan/continuity", { scene: sid, plan: pid, on: el.checked });
        await reload();
      },
      "prompt-input": () => { dirtyPrompt = true; },
      "prompt-suggest": (el) => busy(el, async () => {
        const res = await post("/api/facile/prompt/suggest", { kind: "plan", id: plan().aid });
        content.querySelector("[name=prompt]").value = res.prompt;
        dirtyPrompt = true;
      }),
      "prompt-save": (el) => busy(el, async () => {
        await post(`/api/asset/${encodeURIComponent(plan().aid)}`, { prompt: content.querySelector("[name=prompt]").value });
        dirtyPrompt = false;
        toast("Prompt enregistré");
        await reload();
      }),
      reuse: async () => {
        const img = await pickImage(store.data);
        if (!img) return;
        await post("/api/facile/plan/copy-image", { scene: sid, plan: pid, source: img.aid, candidate: img.candidate });
        toast("Image reprise");
        await reload();
        ctx.refresh();
      },
      ...loraHandlers(content, async (loras) => {
        await post("/api/facile/asset/loras", { asset: plan().aid, loras });
        toast("LoRA enregistrés");
        await reload();
      }),
    });
    content.addEventListener("input", (e) => { if (e.target.name === "prompt") dirtyPrompt = true; });

    async function saveRefs(p, exclude, extra) {
      await post("/api/facile/plan/refs", { scene: sid, plan: pid, exclude, extra });
      await reload();
    }
  });
  return handle;
}

const excludedKeys = (p) => p.refs.auto.filter((r) => r.excluded).map((r) => r.key);
const extras = (p) => (p.refs.extra || []).map((r) => r.ref || r.key || r.aid).filter(Boolean);

function body(data, sc, plan) {
  const st = sceneState(sc.id);
  const framing = st.plans?.[plan.id]?.framing || "";
  const shared = st.plans?.[plan.id]?.shared;
  const location = (data.locations || []).find((l) => l.name === sc.location);
  const viewpoints = location?.viewpoints || [];
  const wardrobe = data.recit?.wardrobe || {};
  const refs = plan.refs || { auto: [], extra: [], missing: [] };
  const extraKeys = new Set(extras(plan));
  return `
    ${thumb(plan.image, "", "Pas encore d'image")}
    <div class="row">
      <button class="btn primary" data-act="draw">${plan.image ? "Redessiner" : "Dessiner"}</button>
      <button class="btn" data-act="reuse">Reprendre une image existante</button>
    </div>
    ${shared ? `<p class="notice small">Ce moment montre l'image d'un autre moment. La régler ou la redessiner lui donne sa propre image.</p>` : ""}
    ${refs.missing?.length ? `<p class="notice warn small">À dessiner d'abord : ${esc(refs.missing.join(", "))} (fait automatiquement par « Dessiner »).</p>` : ""}

    <section class="stack">
      <p class="section-title">Ce que l'on voit</p>
      <textarea name="note" rows="3" placeholder="Une phrase : ce que montre l'image">${esc(plan.text || "")}</textarea>
      <div class="row">
        <label class="field" style="flex:1"><span>Cadrage</span><select name="framing">
          ${["", ...(data.recit?.framings || [])].map((f) => `<option value="${esc(f)}" ${f === framing ? "selected" : ""}>${f ? esc(f) : "(au choix de l'IA)"}</option>`).join("")}</select></label>
        ${viewpoints.length ? `<label class="field" style="flex:1"><span>Point de vue</span><select name="viewpoint">
          <option value="">(vue générale)</option>${viewpoints.map((v) => `<option ${v.name === plan.viewpoint ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>` : ""}
      </div>
      ${(sc.characters || []).length ? `<div><span class="small" style="font-weight:700">Personnages à l'image</span><div class="chips">
        ${sc.characters.map((c) => `<label class="chip"><input type="checkbox" name="visible" value="${esc(c)}" ${(plan.characters || []).includes(c) ? "checked" : ""}> ${esc(c)}</label>`).join("")}</div></div>` : ""}
      <div class="row end"><button class="btn small" data-act="shot-save">Enregistrer</button></div>
    </section>

    ${(sc.characters || []).some((c) => (wardrobe[c] || []).length) ? `<section class="stack">
      <p class="section-title">Tenues dans cette scène</p>
      ${sc.characters.filter((c) => (wardrobe[c] || []).length).map((c) => `<label class="field"><span>${esc(c)}</span>
        <select data-change="outfit" data-character="${esc(c)}"><option value="">(tenue par défaut)</option>
        ${wardrobe[c].map((o) => `<option ${o === st.outfits?.[c] ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`).join("")}
    </section>` : ""}

    <section class="stack">
      <p class="section-title">Références</p>
      <p class="small muted">Les images qui guident le dessin (décor, personnages, tenues, image d'avant). Touchez pour écarter ou reprendre.</p>
      <div class="subgrid">
        ${refs.auto.map((r) => `<button class="lib-card" data-act="ref-toggle" data-key="${esc(r.key)}" title="${r.excluded ? "Reprendre" : "Écarter"}">
          ${r.image ? `<div class="thumb square" style="${r.excluded ? "opacity:.35" : ""}"><img src="${esc(r.image)}" alt=""></div>` : `<div class="thumb square empty">à dessiner</div>`}
          <span class="small ${r.excluded ? "chip off" : ""}" style="${r.excluded ? "border:0;padding:0" : ""}">${esc(r.label)}</span></button>`).join("")}
        ${(refs.extra || []).map((r) => `<button class="lib-card" data-act="ref-remove" data-ref="${esc(r.ref || r.key || r.aid)}" title="Retirer">
          ${r.image ? `<div class="thumb square"><img src="${esc(r.image)}" alt=""></div>` : `<div class="thumb square empty"></div>`}
          <span class="small">＋ ${esc(r.label || r.ref)}</span></button>`).join("")}
      </div>
      <label class="field"><span>Ajouter une référence</span><select data-change="ref-add"><option value="">Choisir une image retenue…</option>
        ${(data.ref_choices || []).filter((c) => !extraKeys.has(c.ref)).map((c) => `<option value="${esc(c.ref)}">${esc(c.label)}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" data-change="continuity" ${plan.continuity ? "checked" : ""}><span>Continuité : l'image d'avant sert de référence <small class="muted">(décochez pour la tenue d'origine)</small></span></label>
    </section>

    <section class="stack">
      <p class="section-title">Prompt</p>
      <textarea name="prompt" rows="5" placeholder="Rédigé par l'IA au moment du dessin, en anglais">${esc(plan.prompt || "")}</textarea>
      <div class="row"><button class="btn ai small" data-act="prompt-suggest">Proposer</button><button class="btn small" data-act="prompt-save">Enregistrer</button>
        <span class="small muted">« Redessiner » utilise le prompt modifié.</span></div>
    </section>

    ${data.kids ? "" : `<section class="stack"><p class="section-title">LoRA <small class="muted">(ComfyUI seulement)</small></p>${loraEditor(plan.loras, data.lora_names)}</section>`}`;
}
