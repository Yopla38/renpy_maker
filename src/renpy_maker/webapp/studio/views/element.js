// Panneau d'un élément de la bible : personnage, tenue, lieu ou point de vue.
// Image, identité, prompt, références, LoRA ; garde-robe pour un personnage, points de vue pour un lieu.

import { post, run } from "../api.js";
import { bind, busy, confirmDialog, drawer, esc, formDialog, lightbox, thumb, toast } from "../ui.js";
import { store } from "../app.js";
import { loraEditor, loraHandlers } from "./parts.js";

// Retrouve un élément dans la vue, quel que soit son type.
export function findElement(data, aid) {
  const c = data.characters.find((x) => x.aid === aid);
  if (c) return { kind: "character", el: c };
  const o = data.outfits.find((x) => x.aid === aid);
  if (o) return { kind: "outfit", el: o };
  for (const l of data.locations) {
    if (l.aid === aid) return { kind: "location", el: l };
    const v = (l.viewpoints || []).find((x) => x.aid === aid);
    if (v) return { kind: "viewpoint", el: { ...v, parent: l.name, parent_aid: l.aid } };
  }
  return null;
}

const KIND_LABEL = { character: "Personnage", outfit: "Tenue", location: "Lieu", viewpoint: "Point de vue" };

export function openElement(ctx, aid) {
  return drawer("Élément", (content, h) => {
    const paint = () => {
      const found = findElement(store.data, aid);
      if (!found) { h.close(); return; }
      h.setTitle(`${KIND_LABEL[found.kind]} · ${found.el.name}`);
      content.innerHTML = body(store.data, found.kind, found.el);
    };
    paint();
    const reload = async () => { await ctx.refresh({ render: false }); paint(); ctx.rerender?.(); };
    const el = () => findElement(store.data, aid).el;
    const val = (name) => content.querySelector(`[name="${name}"]`)?.value ?? "";
    bind(content, {
      zoom: (b) => lightbox(b.dataset.src),
      draw: (b) => busy(b, async () => {
        await run("/api/facile/card", { aid: b.dataset.aid || aid }, `Dessin de « ${el().name} »`);
        toast("Image dessinée");
        await reload();
      }),
      "draw-prompt": (b) => busy(b, async () => {
        const prompt = val("prompt").trim();
        if (!prompt) return toast("Le prompt est vide", "error");
        await run("/api/facile/card", { aid, prompt }, `Dessin de « ${el().name} »`);
        toast("Image dessinée");
        await reload();
      }),
      "identity-save": (b) => busy(b, async () => {
        const { kind } = findElement(store.data, aid);
        if (kind === "character" || kind === "outfit") {
          await post("/api/facile/element/update", { aid, name: val("name"), description: val("description"),
                                                     descriptor: kind === "character" ? val("descriptor") : undefined });
        } else {
          await post(`/api/asset/${encodeURIComponent(aid)}`, { description: val("description") });
        }
        toast("Enregistré");
        await reload();
      }),
      "identity-suggest": (b) => busy(b, async () => {
        const res = await post("/api/facile/identity/suggest", { aid });
        if (res.description) content.querySelector("[name=description]").value = res.description;
        if (res.descriptor) content.querySelector("[name=descriptor]").value = res.descriptor;
        toast("Proposition remplie : relisez puis enregistrez.");
      }),
      "prompt-suggest": (b) => busy(b, async () => {
        const res = await post("/api/facile/prompt/suggest", { kind: "card", id: aid });
        content.querySelector("[name=prompt]").value = res.prompt;
      }),
      "prompt-save": (b) => busy(b, async () => {
        await post(`/api/asset/${encodeURIComponent(aid)}`, { prompt: val("prompt") });
        toast("Prompt enregistré");
        await reload();
      }),
      "ref-add": async (s) => {
        if (!s.value) return;
        await post("/api/facile/element/refs", { aid, refs: [...(el().refs || []), s.value], based_on: el().based_on || null });
        await reload();
      },
      "ref-remove": async (b) => {
        await post("/api/facile/element/refs", { aid, refs: (el().refs || []).filter((r) => r !== b.dataset.ref), based_on: el().based_on || null });
        await reload();
      },
      "based-on": async (s) => {
        await post("/api/facile/element/refs", { aid, refs: el().refs || [], based_on: s.value || null });
        toast("Tenue de départ enregistrée : redessinez pour l'appliquer.");
        await reload();
      },
      retouch: (b) => busy(b, async () => {
        const mode = b.dataset.mode;
        const v = await formDialog({
          title: mode === "add" ? "Ajouter à la tenue" : "Retirer de la tenue",
          intro: "La tenue est redessinée à partir de son image actuelle : seul ce détail change.",
          fields: [{ name: "text", label: mode === "add" ? "Ce qu'on ajoute" : "Ce qu'on retire", placeholder: "Par exemple : un chapeau de paille", required: true }],
        });
        if (!v) return;
        await run("/api/facile/outfit/edit", { aid, mode, text: v.text }, "Retouche de la tenue");
        toast("Tenue retouchée");
        await reload();
      }),
      // --- garde-robe ---
      "outfit-open": (b) => openElement(ctx, b.dataset.aid),
      "outfit-default": async (b) => {
        await post("/api/atelier/outfit/default", { character: aid, outfit: b.dataset.aid });
        toast("Tenue par défaut enregistrée");
        await reload();
      },
      "outfits-propose": (b) => busy(b, async () => {
        const c = el();
        const existing = store.data.outfits.filter((o) => o.parent === c.name).map((o) => o.name);
        const res = await post("/api/atelier/outfits/propose", { character: c.name, description: c.description,
                                                                  idea: store.data.idea, existing, count: 3 });
        content.querySelector("#proposed").innerHTML = proposals(res.outfits, "outfit-accept");
      }),
      "outfit-accept": (b) => busy(b, async () => {
        const card = b.closest("[data-proposal]");
        await post("/api/facile/outfit/create", { character: aid, name: card.querySelector("[name=p-name]").value,
                                                  description: card.querySelector("[name=p-description]").value, scenes: [] });
        card.remove();
        toast("Tenue ajoutée à la garde-robe");
        await reload();
      }),
      "outfit-new": async () => {
        const v = await formDialog({ title: "Nouvelle tenue", fields: [
          { name: "name", label: "Nom", placeholder: "Par exemple : robe de bal", required: true },
          { name: "description", label: "Description", type: "textarea", rows: 2 }] });
        if (!v) return;
        await post("/api/facile/outfit/create", { character: aid, name: v.name, description: v.description, scenes: [] });
        await reload();
      },
      // --- points de vue ---
      "viewpoint-open": (b) => openElement(ctx, b.dataset.aid),
      "viewpoints-propose": (b) => busy(b, async () => {
        const l = el();
        const res = await post("/api/atelier/viewpoints/propose", { location: l.name, description: l.description,
          idea: store.data.idea, existing: (l.viewpoints || []).map((v) => v.name), count: 3 });
        content.querySelector("#proposed").innerHTML = proposals(res.viewpoints, "viewpoint-accept");
      }),
      "viewpoint-accept": (b) => busy(b, async () => {
        const card = b.closest("[data-proposal]");
        await post("/api/atelier/viewpoints/add", { location: aid, name: card.querySelector("[name=p-name]").value,
                                                    description: card.querySelector("[name=p-description]").value });
        card.remove();
        toast("Point de vue ajouté");
        await reload();
      }),
      "viewpoint-new": async () => {
        const v = await formDialog({ title: "Nouveau point de vue", fields: [
          { name: "name", label: "Nom", placeholder: "Par exemple : le quai, vu de la mer", required: true },
          { name: "description", label: "Ce que l'on voit", type: "textarea", rows: 2 }] });
        if (!v) return;
        await post("/api/atelier/viewpoints/add", { location: aid, name: v.name, description: v.description });
        await reload();
      },
      "proposal-drop": (b) => b.closest("[data-proposal]").remove(),
      create: (b) => busy(b, async () => {
        await run("/api/facile/complete", {}, "Création des éléments manquants");
        await reload();
      }),
      ...loraHandlers(content, async (loras) => {
        await post("/api/facile/asset/loras", { asset: aid, loras });
        toast("LoRA enregistrés");
        await reload();
      }),
    });
  });
}

function proposals(list, act) {
  if (!list?.length) return `<p class="muted small">Pas de proposition : réessayez.</p>`;
  return list.map((p) => `<div class="card stack" data-proposal style="gap:8px">
    <input type="text" name="p-name" value="${esc(p.name)}">
    <textarea name="p-description" rows="2">${esc(p.description || "")}</textarea>
    <div class="row end"><button class="btn quiet small" data-act="proposal-drop">Écarter</button><button class="btn small primary" data-act="${act}">Ajouter</button></div></div>`).join("");
}

function body(data, kind, e) {
  if (!e.aid) {
    return `<div class="notice">Cet élément est dans l'histoire mais pas encore dans la bible.</div>
      <button class="btn primary" data-act="create">Créer les éléments manquants</button>`;
  }
  const portrait = kind === "character" || kind === "outfit";
  const outfits = kind === "character" ? data.outfits.filter((o) => o.parent === e.name) : [];
  const siblings = kind === "outfit" ? data.outfits.filter((o) => o.parent === e.parent && o.aid !== e.aid && o.ready) : [];
  const refChoices = (data.ref_choices || []).filter((r) => r.ref !== e.aid && !(e.refs || []).includes(r.ref));
  const refLabel = (ref) => (data.ref_choices || []).find((r) => r.ref === ref)?.label || ref;
  return `
    <div style="max-width:${portrait ? "260px" : "100%"}">${thumb(e.image, portrait ? "portrait" : "", "Pas encore d'image")}</div>
    <div class="row">
      <button class="btn ${e.image ? "" : "primary"}" data-act="draw">${e.image ? "Redessiner" : "Dessiner"}</button>
      ${kind === "outfit" && e.image ? `<button class="btn small" data-act="retouch" data-mode="add">＋ Ajouter un détail</button><button class="btn small" data-act="retouch" data-mode="remove">− Retirer un détail</button>` : ""}
    </div>
    ${e.blocked ? `<p class="notice warn small">Dessinez d'abord ${kind === "outfit" ? `le personnage « ${esc(e.parent)} »` : "les images dont il dépend"}.</p>` : ""}

    <section class="stack">
      <p class="section-title">Identité</p>
      ${kind === "character" || kind === "outfit" ? `<label class="field"><span>Nom</span><input type="text" name="name" value="${esc(e.name)}"></label>` : ""}
      <label class="field"><span>${kind === "character" ? "Apparence" : "Description"}</span><textarea name="description" rows="3">${esc(e.description || "")}</textarea></label>
      ${kind === "character" ? `<label class="field"><span>Genre et âge</span><input type="text" name="descriptor" value="${esc(e.descriptor || "")}" placeholder="Par exemple : young woman, about 30"><small>En anglais, avec un mot de genre (woman, man, girl, boy…) : il guide le dessin.</small></label>` : ""}
      <div class="row">${kind === "character" ? `<button class="btn ai small" data-act="identity-suggest">Pré-remplir</button>` : ""}<button class="btn small" data-act="identity-save">Enregistrer</button></div>
    </section>

    ${kind === "character" ? `<section class="stack">
      <p class="section-title">Garde-robe</p>
      <div class="subgrid">${outfits.map((o) => `<div class="mini">
        <button class="lib-card" data-act="outfit-open" data-aid="${esc(o.aid)}">${thumb(o.image, "portrait", "à dessiner", false)}</button>
        <b>${esc(o.name)}</b>
        ${o.aid === e.default_outfit ? `<span class="tag ok">par défaut</span>` : (o.aid ? `<button class="btn quiet small" data-act="outfit-default" data-aid="${esc(o.aid)}">Par défaut</button>` : "")}
      </div>`).join("") || `<p class="muted small">Pas encore de tenue.</p>`}</div>
      <div class="row"><button class="btn ai small" data-act="outfits-propose">Proposer des tenues</button><button class="btn small" data-act="outfit-new">＋ Tenue</button></div>
      <div id="proposed" class="stack"></div>
    </section>` : ""}

    ${kind === "location" ? `<section class="stack">
      <p class="section-title">Points de vue</p>
      <div class="subgrid">${(e.viewpoints || []).map((v) => `<div class="mini">
        <button class="lib-card" data-act="viewpoint-open" data-aid="${esc(v.aid)}">${thumb(v.image, "", "à dessiner", false)}</button><b>${esc(v.name)}</b></div>`).join("") || `<p class="muted small">Une seule vue pour l'instant.</p>`}</div>
      <div class="row"><button class="btn ai small" data-act="viewpoints-propose">Proposer des points de vue</button><button class="btn small" data-act="viewpoint-new">＋ Point de vue</button></div>
      <div id="proposed" class="stack"></div>
    </section>` : ""}

    <section class="stack">
      <p class="section-title">Prompt</p>
      <textarea name="prompt" rows="5" placeholder="Rédigé par l'IA au moment du dessin, en anglais">${esc(e.prompt || "")}</textarea>
      <div class="row"><button class="btn ai small" data-act="prompt-suggest">Proposer</button><button class="btn small" data-act="prompt-save">Enregistrer</button><button class="btn small" data-act="draw-prompt">Dessiner avec ce prompt</button></div>
    </section>

    ${kind !== "viewpoint" ? `<section class="stack">
      <p class="section-title">Références</p>
      ${kind === "outfit" ? `<label class="field"><span>Tenue de départ</span><select data-change="based-on"><option value="">(le personnage seul)</option>
        ${siblings.map((o) => `<option value="${esc(o.aid)}" ${o.aid === e.based_on ? "selected" : ""}>${esc(o.name)}</option>`).join("")}</select>
        <small>La tenue se dessine en modifiant cette tenue déjà retenue.</small></label>` : ""}
      <div class="chips">${(e.refs || []).map((r) => `<span class="chip">${esc(refLabel(r))} <a href="#" data-act="ref-remove" data-ref="${esc(r)}" aria-label="Retirer">✕</a></span>`).join("") || `<span class="muted small">Aucune référence ajoutée.</span>`}</div>
      <label class="field"><span>Ajouter une image retenue</span><select data-change="ref-add"><option value="">Choisir…</option>
        ${refChoices.map((r) => `<option value="${esc(r.ref)}">${esc(r.label)}</option>`).join("")}</select></label>
    </section>` : ""}

    ${data.kids ? "" : `<section class="stack"><p class="section-title">LoRA <small class="muted">(ComfyUI seulement)</small></p>${loraEditor(e.loras, data.lora_names)}</section>`}`;
}
