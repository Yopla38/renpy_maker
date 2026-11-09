// Petits outils d'interface partagés par tous les espaces du studio.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Branche les actions d'un bloc : data-act="nom" (clic) et data-change="nom" (changement de valeur).
// Le gestionnaire reçoit (élément, évènement) ; une promesse rejetée s'affiche en message d'erreur.
export function bind(root, handlers) {
  const call = (name, el, ev) => {
    const fn = handlers[name];
    if (!fn) return;
    Promise.resolve().then(() => fn(el, ev)).catch((e) => toast(e.message || String(e), "error"));
  };
  root.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el || !root.contains(el)) return;
    ev.preventDefault();
    call(el.dataset.act, el, ev);
  });
  root.addEventListener("change", (ev) => {
    const el = ev.target.closest("[data-change]");
    if (el && root.contains(el)) call(el.dataset.change, el, ev);
  });
}

// Bouton occupé pendant une action : évite le double clic.
export async function busy(btn, fn) {
  if (!btn || btn.classList.contains("busy")) return;
  btn.classList.add("busy");
  try { return await fn(); } finally { btn.classList.remove("busy"); }
}

export function toast(message, kind = "") {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  box.append(el);
  while (box.children.length > 2) box.firstElementChild.remove(); // les deux derniers messages suffisent
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
}

export function lightbox(src) {
  const el = document.createElement("div");
  el.className = "lightbox";
  el.innerHTML = `<img src="${esc(src)}" alt="">`;
  el.onclick = () => el.remove();
  document.addEventListener("keydown", function k(e) { if (e.key === "Escape") { el.remove(); document.removeEventListener("keydown", k); } });
  document.body.append(el);
}

// Fenêtre modale. html : contenu ; buttons : [{label, value, kind}]. Renvoie la valeur du bouton (null : fermée).
export function dialog({ title, html, buttons = [{ label: "Fermer", value: null }], wide = false, onOpen }) {
  return new Promise((resolve) => {
    const scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.innerHTML = `
      <div class="dialog ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <header><h2>${esc(title)}</h2><button class="btn quiet" data-x aria-label="Fermer">✕</button></header>
        <div class="content">${html}</div>
        <footer>${buttons.map((b, i) => `<button class="btn ${b.kind || ""}" data-i="${i}">${esc(b.label)}</button>`).join("")}</footer>
      </div>`;
    const close = (value) => { scrim.remove(); document.removeEventListener("keydown", onKey); resolve(value); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    scrim.addEventListener("click", (e) => {
      if (e.target === scrim || e.target.closest("[data-x]")) return close(null);
      const b = e.target.closest("[data-i]");
      if (!b) return;
      const spec = buttons[+b.dataset.i];
      const value = typeof spec.value === "function" ? spec.value(scrim) : spec.value;
      if (value === undefined) return; // validation refusée : la fenêtre reste ouverte
      close(value);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(scrim);
    const first = scrim.querySelector("input, textarea, select");
    (first || scrim.querySelector("footer .btn:last-child"))?.focus();
    if (onOpen) onOpen(scrim);
  });
}

export const confirmDialog = (title, text, okLabel = "Confirmer", kind = "primary") =>
  dialog({ title, html: `<p>${esc(text)}</p>`,
           buttons: [{ label: "Annuler", value: false }, { label: okLabel, value: true, kind }] });

// Formulaire simple. fields : [{name, label, type: text|textarea|select|number, value, options:[{value,label}], hint}]
export function formDialog({ title, intro = "", fields, ok = "Valider", wide = false }) {
  const html = (intro ? `<p class="muted">${esc(intro)}</p>` : "") + fields.map((f) => {
    const id = `f-${f.name}`;
    let input;
    if (f.type === "textarea") input = `<textarea id="${id}" name="${f.name}" rows="${f.rows || 3}" placeholder="${esc(f.placeholder || "")}">${esc(f.value || "")}</textarea>`;
    else if (f.type === "select") input = `<select id="${id}" name="${f.name}">${f.options.map((o) =>
      `<option value="${esc(o.value)}" ${String(o.value) === String(f.value ?? "") ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
    else input = `<input id="${id}" name="${f.name}" type="${f.type || "text"}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder || "")}" ${f.min !== undefined ? `min="${f.min}"` : ""} ${f.max !== undefined ? `max="${f.max}"` : ""}>`;
    return `<label class="field" for="${id}"><span>${esc(f.label)}</span>${input}${f.hint ? `<small>${esc(f.hint)}</small>` : ""}</label>`;
  }).join("");
  return dialog({
    title, html, wide,
    buttons: [{ label: "Annuler", value: null }, {
      label: ok, kind: "primary", value: (root) => {
        const out = {};
        for (const f of fields) {
          const v = root.querySelector(`[name="${f.name}"]`).value;
          if (f.required && !v.trim()) { toast(`${f.label} : à remplir`, "error"); return undefined; }
          out[f.name] = v;
        }
        return out;
      },
    }],
  });
}

// Panneau latéral (détails d'une image, d'un personnage…). render(contentEl, api) remplit le contenu.
export function drawer(title, render) {
  const scrim = document.createElement("div");
  scrim.className = "drawer-scrim";
  const el = document.createElement("aside");
  el.className = "drawer";
  el.setAttribute("role", "dialog");
  el.innerHTML = `<header><h2>${esc(title)}</h2><button class="btn quiet" data-x aria-label="Fermer">✕</button></header><div class="content"></div>`;
  const content = el.querySelector(".content");
  const handle = {
    el, content,
    close() { scrim.remove(); el.remove(); document.removeEventListener("keydown", onKey); handle.onClose?.(); },
    setTitle(t) { el.querySelector("h2").textContent = t; },
  };
  const onKey = (e) => { if (e.key === "Escape" && !document.querySelector(".scrim")) handle.close(); };
  scrim.onclick = () => handle.close();
  el.querySelector("[data-x]").onclick = () => handle.close();
  document.addEventListener("keydown", onKey);
  document.body.append(scrim, el);
  render(content, handle);
  return handle;
}

// Champ de texte qui grandit avec son contenu.
export function autosize(ta) {
  const fit = () => { ta.style.height = "auto"; ta.style.height = `${ta.scrollHeight + 2}px`; };
  ta.addEventListener("input", fit);
  requestAnimationFrame(fit);
}

// zoom : un clic sur l'image l'agrandit (désactivé dans une carte cliquable, qui ouvre son panneau).
export const thumb = (src, cls = "", alt = "", zoom = true) => src
  ? `<div class="thumb ${cls}"><img src="${esc(src)}" alt="${esc(alt)}" loading="lazy">${zoom ? `<span class="zoom" data-act="zoom" data-src="${esc(src)}"></span>` : ""}</div>`
  : `<div class="thumb empty ${cls}">${esc(alt || "Pas encore d'image")}</div>`;

export const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
