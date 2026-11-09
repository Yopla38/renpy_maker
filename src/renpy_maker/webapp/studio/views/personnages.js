// Personnages : la distribution et la garde-robe.

import { post } from "../api.js";
import { bind, busy, esc, formDialog, thumb, toast, plural } from "../ui.js";
import { openElement } from "./element.js";

let proposed = []; // propositions de l'IA pas encore acceptées (gardées d'un rendu à l'autre)

export function render(root, ctx) {
  const paint = () => {
    const { data } = ctx;
    const cards = data.characters.map((c) => {
      const outfits = data.outfits.filter((o) => o.parent === c.name);
      return `<button class="lib-card" data-act="open" data-aid="${esc(c.aid || "")}" data-name="${esc(c.name)}">
        ${thumb(c.image, "portrait", "À dessiner", false)}
        <b>${esc(c.name)}</b>
        <span class="sub">${esc(c.descriptor || "genre et âge à préciser")} · ${plural(outfits.length, "tenue", "tenues")}</span>
      </button>`;
    }).join("");
    root.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Personnages</h1><p>La distribution de l'histoire. Chaque personnage a son portrait, son genre et son âge (pour le dessin), et sa garde-robe.</p></div>
        <div class="row"><button class="btn ai" data-act="propose">Proposer des personnages</button><button class="btn" data-act="add">＋ Personnage</button></div></div>
      ${proposed.length ? `<section class="stack" style="margin-bottom:24px"><p class="section-title">Propositions de l'IA</p><div class="proposals">${proposed.map((p, i) => `
        <div class="card stack" style="gap:8px" data-i="${i}">
          <input type="text" name="name" value="${esc(p.name)}" aria-label="Nom">
          <textarea name="description" rows="3" aria-label="Apparence">${esc(p.description || "")}</textarea>
          <input type="text" name="descriptor" value="${esc(p.descriptor || "")}" placeholder="genre et âge (anglais)" aria-label="Genre et âge">
          <div class="row end"><button class="btn quiet small" data-act="drop" data-i="${i}">Écarter</button><button class="btn primary small" data-act="accept" data-i="${i}">Ajouter</button></div>
        </div>`).join("")}</div></section>` : ""}
      ${cards ? `<div class="grid">${cards}</div>` : `<div class="empty-state"><h2>Pas encore de personnage</h2><p>Demandez des propositions à l'IA, ou ajoutez-les vous-même.</p></div>`}
    </div>`;
  };
  ctx.rerender = paint;
  paint();

  bind(root, {
    open: (el) => {
      if (!el.dataset.aid) return toast(`« ${el.dataset.name} » n'est pas encore créé : utilisez « Écrire avec l'IA › Éléments manquants » sur la carte.`);
      openElement(ctx, el.dataset.aid);
    },
    propose: (el) => busy(el, async () => {
      const res = await post("/api/atelier/characters/propose", {
        idea: ctx.data.idea, existing: [...ctx.data.characters.map((c) => c.name), ...proposed.map((p) => p.name)], count: 3 });
      proposed = [...proposed, ...res.characters];
      paint();
    }),
    drop: (el) => { proposed.splice(+el.dataset.i, 1); paint(); },
    accept: (el) => busy(el, async () => {
      const card = el.closest(".card"); // la carte de la proposition (le bouton porte aussi data-i)
      const v = (n) => card.querySelector(`[name=${n}]`).value;
      await post("/api/atelier/characters/add", { name: v("name"), description: v("description"), descriptor: v("descriptor") });
      proposed.splice(+el.dataset.i, 1);
      toast(`${v("name")} rejoint la distribution`);
      await ctx.refresh({ render: false });
      paint();
    }),
    add: async () => {
      const v = await formDialog({ title: "Nouveau personnage", fields: [
        { name: "name", label: "Nom", required: true },
        { name: "description", label: "Apparence", type: "textarea", rows: 3 },
        { name: "descriptor", label: "Genre et âge (en anglais)", placeholder: "Par exemple : old man, about 70" }] });
      if (!v) return;
      await post("/api/atelier/characters/add", v);
      await ctx.refresh({ render: false });
      paint();
    },
  });
}
