// Morceaux d'interface communs aux panneaux d'image et d'élément : LoRA, choix d'une image existante.

import { dialog, esc } from "../ui.js";

export function loraEditor(loras, names) {
  const rows = (loras || []).map((l) => loraRow(l, names)).join("");
  return `<div class="stack lora-list" style="gap:6px">${rows}</div>
    <datalist id="lora-names">${(names || []).map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
    <div class="row"><button class="btn small" data-act="lora-add">＋ LoRA</button><button class="btn small" data-act="lora-save">Enregistrer les LoRA</button></div>`;
}

export function loraRow(l = { name: "", strength: 1 }) {
  return `<div class="row lora-row" style="flex-wrap:nowrap">
    <input type="text" list="lora-names" name="lora-name" value="${esc(l.name)}" placeholder="nom du LoRA" style="flex:3">
    <input type="number" name="lora-strength" value="${esc(l.strength ?? 1)}" step="0.05" min="-2" max="2" style="flex:1;min-width:70px">
    <button class="btn quiet small" data-act="lora-remove" aria-label="Retirer">✕</button></div>`;
}

export function readLoras(root) {
  return [...root.querySelectorAll(".lora-row")].map((r) => ({
    name: r.querySelector("[name=lora-name]").value.trim(),
    strength: parseFloat(r.querySelector("[name=lora-strength]").value || "1"),
  })).filter((l) => l.name);
}

export const loraHandlers = (root, save) => ({
  "lora-add": () => root.querySelector(".lora-list").insertAdjacentHTML("beforeend", loraRow()),
  "lora-remove": (el) => el.closest(".lora-row").remove(),
  "lora-save": () => save(readLoras(root)),
});

// Toutes les images déjà dessinées de l'histoire (la « bobine » de l'atelier).
export function allImages(data) {
  const out = [];
  const add = (aid, candidate, image, label, group) => {
    if (image && aid && candidate !== null && candidate !== undefined) out.push({ aid, candidate, image, label, group });
  };
  for (const c of data.characters || []) add(c.aid, c.candidate, c.image, c.name, "Personnages");
  for (const o of data.outfits || []) add(o.aid, o.candidate, o.image, `${o.parent} · ${o.name}`, "Tenues");
  for (const l of data.locations || []) {
    add(l.aid, l.candidate, l.image, l.name, "Lieux");
    for (const v of l.viewpoints || []) add(v.aid, v.candidate, v.image, `${l.name} · ${v.name}`, "Lieux");
  }
  for (const s of data.scenes || []) for (const p of s.plans || []) add(p.aid, p.candidate, p.image, s.title, "Scènes");
  return out;
}

// Fenêtre de choix d'une image existante. Renvoie {aid, candidate} ou null.
export function pickImage(data, title = "Reprendre une image existante") {
  const images = allImages(data);
  const groups = [...new Set(images.map((i) => i.group))];
  const html = images.length ? groups.map((g) => `<p class="section-title">${esc(g)}</p>
    <div class="subgrid">${images.map((im, k) => im.group !== g ? "" : `
      <button class="lib-card" data-pick="${k}" title="${esc(im.label)}"><div class="thumb"><img src="${esc(im.image)}" alt="" loading="lazy"></div>
      <span class="small">${esc(im.label)}</span></button>`).join("")}</div>`).join("")
    : `<p class="muted">Aucune image dessinée pour l'instant.</p>`;
  return new Promise((resolve) => {
    let picked = null;
    dialog({
      title, html, wide: true, buttons: [{ label: "Annuler", value: null }],
      onOpen(root) {
        root.addEventListener("click", (e) => {
          const b = e.target.closest("[data-pick]");
          if (!b) return;
          picked = images[+b.dataset.pick];
          root.querySelector("[data-x]").click();
        });
      },
    }).then(() => resolve(picked ? { aid: picked.aid, candidate: picked.candidate } : null));
  });
}
