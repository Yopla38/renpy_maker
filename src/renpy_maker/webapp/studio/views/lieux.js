// Lieux : les décors de l'histoire et leurs points de vue.

import { post } from "../api.js";
import { bind, busy, esc, formDialog, thumb, toast, plural } from "../ui.js";
import { openElement } from "./element.js";

export function render(root, ctx) {
  const paint = () => {
    const { data } = ctx;
    const used = (name) => data.scenes.filter((s) => s.location === name).length;
    const cards = data.locations.map((l) => `
      <button class="lib-card" data-act="open" data-aid="${esc(l.aid || "")}" data-name="${esc(l.name)}">
        ${thumb(l.image, "", "À dessiner", false)}
        <b>${esc(l.name)}</b>
        <span class="sub">${plural(used(l.name), "scène", "scènes")} · ${plural((l.viewpoints || []).length, "point de vue", "points de vue")}</span>
      </button>`).join("");
    root.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Lieux</h1><p>Les décors, dessinés une fois et réutilisés dans toutes les scènes qui s'y passent. Un lieu peut avoir plusieurs points de vue.</p></div>
        <div class="row"><button class="btn ai" data-act="new-place">Nouveau lieu pour la suite</button></div></div>
      ${cards ? `<div class="grid">${cards}</div>` : `<div class="empty-state"><h2>Pas encore de lieu</h2><p>Les lieux naissent avec les scènes.</p></div>`}
    </div>`;
  };
  ctx.rerender = paint;
  paint();

  bind(root, {
    open: (el) => {
      if (!el.dataset.aid) return toast(`« ${el.dataset.name} » n'est pas encore créé : utilisez « Écrire avec l'IA › Éléments manquants » sur la carte.`);
      openElement(ctx, el.dataset.aid);
    },
    // Un lieu naît avec une scène : l'IA propose le lieu suivant, on commence la scène.
    "new-place": (el) => busy(el, async () => {
      const { data } = ctx;
      const last = data.scenes[data.scenes.length - 1];
      const context = last?.dialogue?.length ? last.dialogue[last.dialogue.length - 1].text : "";
      const p = await post("/api/atelier/location/propose", { idea: data.idea, existing: data.locations.map((l) => l.name), context });
      const v = await formDialog({
        title: "Nouveau lieu", intro: "Une nouvelle scène commence dans ce lieu, à la fin de l'histoire.",
        fields: [
          { name: "location", label: "Lieu", value: p.name || p.location || "", required: true },
          { name: "summary", label: "Ce qui s'y passe", type: "textarea", rows: 2, value: p.description || p.summary || "" },
          { name: "title", label: "Titre de la scène", value: p.title || p.name || "" },
          { name: "characters", label: "Personnages présents (séparés par des virgules)", value: (p.characters || []).join(", ") },
        ],
        ok: "Commencer la scène",
      });
      if (!v) return;
      const res = await post("/api/atelier/scene/start", { title: v.title || v.location, location: v.location, summary: v.summary,
        characters: v.characters.split(",").map((s) => s.trim()).filter(Boolean) });
      toast("Scène créée");
      await ctx.refresh({ render: false });
      ctx.go(`#/scene/${encodeURIComponent(res.scene)}`);
    }),
  });
}
