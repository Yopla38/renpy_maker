// Studio : coquille de l'application. Une seule source de données (GET /api/recit), des espaces qui la
// lisent, et une barre de tâche commune.

import { get, onJob, cancelJob } from "./api.js";
import { $, $$, esc, toast } from "./ui.js";
import * as carte from "./views/carte.js";
import * as scene from "./views/scene.js";
import * as personnages from "./views/personnages.js";
import * as lieux from "./views/lieux.js";
import * as lecture from "./views/lecture.js";
import * as exporter from "./views/export.js";
import * as commencer from "./views/commencer.js";
import * as reglages from "./views/reglages.js";

const VIEWS = { carte, scene, personnages, lieux, lecture, export: exporter, commencer };

export const store = {
  data: null,          // vue complète de l'histoire
  lastScene: null,     // dernière scène ouverte (lien « Scènes » du rail)
};

let cleanup = null;    // nettoyage de l'espace affiché (carte cytoscape, lecteur…)
let busyPoll = null;

// ---------- Données ----------
export async function refresh({ render = true } = {}) {
  store.data = await get("/api/recit");
  chrome();
  if (render) show();
  return store.data;
}

export const scenes = () => store.data?.scenes || [];
export const sceneById = (sid) => scenes().find((s) => s.id === sid);
export const sceneState = (sid) => store.data?.recit?.scenes?.[sid] || {};
export const isEmpty = () => scenes().length === 0;

// Image qui représente une scène : celle de son premier plan dessiné.
export function sceneImage(sc) {
  return (sc?.plans || []).map((p) => p.image).find(Boolean) || "";
}

// ---------- Navigation ----------
export function go(hash) {
  if (location.hash === hash) show();
  else location.hash = hash;
}

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  let [name, ...params] = parts;
  if (!name) name = isEmpty() ? "commencer" : "carte";
  if (!VIEWS[name]) name = "carte";
  return { name, params };
}

function show() {
  if (!store.data) return;
  const { name, params } = route();
  if (cleanup) { try { cleanup(); } catch { /* espace déjà retiré */ } cleanup = null; }
  // Un élément neuf à chaque rendu : les écouteurs de l'espace précédent disparaissent avec l'ancien.
  const old = $("#view");
  const root = old.cloneNode(false);
  old.replaceWith(root);
  root.className = "view";
  $$("#rail a").forEach((a) => { if (a.dataset.view !== name) a.removeAttribute("aria-current"); else a.setAttribute("aria-current", "page"); });
  const view = VIEWS[name];
  try {
    // ctx.data lit toujours la dernière vue chargée (après un refresh sans nouveau rendu aussi).
    const ctx = { params, refresh, go, store, get data() { return store.data; } };
    cleanup = view.render(root, ctx) || null;
  } catch (e) {
    console.error(e);
    root.innerHTML = `<div class="page"><div class="notice warn">Cet espace n'a pas pu s'afficher : ${esc(e.message)}</div></div>`;
  }
  root.scrollTop = 0;
}

// ---------- Barre du haut ----------
function chrome() {
  const d = store.data;
  $("#story-title").textContent = d.title || "Histoire sans titre";
  $("#story-idea").textContent = d.idea || "";
  document.title = `${d.title || "Histoire"} · Studio`;
  $("#rail-export").classList.toggle("hidden", !!d.kids);
  const sceneLink = $('#rail a[data-view="scene"]');
  sceneLink.href = store.lastScene && store.data.scenes.some((s) => s.id === store.lastScene)
    ? `#/scene/${encodeURIComponent(store.lastScene)}` : "#/scene";
  // Une tâche lancée ailleurs (autre onglet, ancienne page) : on suit l'état « occupé » du moteur.
  if (d.busy && !busyPoll && !$("#job-slot .job[data-id]")) {
    renderJob({ id: "", label: "Une création est en cours", state: "running", message: "", progress: null });
    busyPoll = setInterval(async () => {
      const fresh = await get("/api/recit").catch(() => null);
      if (fresh && !fresh.busy) { clearInterval(busyPoll); busyPoll = null; renderJob(null); refresh(); }
    }, 3000);
  }
}

function renderJob(job) {
  const slot = $("#job-slot");
  if (!job) { slot.innerHTML = ""; return; }
  const p = job.progress;
  const pct = p && p.max ? Math.round((100 * p.value) / p.max) : null;
  const text = job.state === "done" ? `${job.label} : terminé`
    : job.state === "error" ? `${job.label} : échec` : (job.message || job.label);
  slot.innerHTML = `
    <div class="job" ${job.id ? `data-id="${esc(job.id)}"` : ""} title="${esc(job.label)}">
      <span class="msg">${esc(text)}${pct !== null ? ` · ${pct} %` : ""}</span>
      ${job.state === "running" ? `<span class="bar ${pct === null ? "indet" : ""}"><i style="width:${pct ?? 0}%"></i></span>` : ""}
      ${job.state === "running" && job.id ? `<button class="btn small" id="job-stop">Arrêter</button>` : ""}
    </div>`;
  $("#job-stop")?.addEventListener("click", async (e) => {
    e.target.classList.add("busy");
    try { await cancelJob(); toast("Arrêt demandé : la tâche s'arrête dès que possible."); }
    catch (err) { toast(err.message, "error"); }
  });
}

// ---------- Démarrage ----------
async function boot() {
  onJob(renderJob);
  $("#settings-btn").addEventListener("click", () => reglages.open({ get data() { return store.data; }, refresh, go }));
  window.addEventListener("hashchange", () => {
    const { name, params } = route();
    if (name === "scene" && params[0]) store.lastScene = params[0];
    show();
  });
  try {
    await refresh({ render: false });
  } catch (e) {
    $("#view").innerHTML = `<div class="page"><div class="notice warn">${esc(e.message)}</div>
      <p><a class="btn" href="/projets">Mes histoires</a></p></div>`;
    return;
  }
  const { name, params } = route();
  if (name === "scene" && params[0]) store.lastScene = params[0];
  show();
  // Nouvelle histoire, ou « Réglages » depuis Mes histoires : la roue s'ouvre tout de suite.
  if (new URLSearchParams(location.search).has("reglages")) {
    history.replaceState(null, "", location.pathname + location.hash);
    reglages.open({ get data() { return store.data; }, refresh, go });
  }
}

boot();
