// Lecture : l'histoire comme le jeu final, avec ses choix. Même ordre que l'export Ren'Py :
// une image seule avant sa réplique, puis l'image du plan et ses répliques ; à la fin de la scène,
// un menu de choix, la scène suivante, une fin, ou une ligne qui attend sa suite.

import { esc } from "../ui.js";
import { sceneById, sceneState } from "../app.js";

const NARRATOR = "Narration";

function steps(sc) {
  const lines = sc.dialogue || [];
  const plans = [...(sc.plans || [])].sort((a, b) => a.from_line - b.from_line || (a.pause ? 0 : 1) - (b.pause ? 0 : 1));
  const out = [];
  let image = "";
  for (let i = 0; i <= lines.length; i++) {
    for (const p of plans.filter((x) => x.from_line === i && x.pause)) {
      out.push({ image: p.image || image, speaker: p.speech ? p.speaker || NARRATOR : "", text: p.speech || "" });
      if (p.image) image = p.image;
    }
    for (const p of plans.filter((x) => x.from_line === i && !x.pause)) if (p.image) image = p.image;
    if (i < lines.length) out.push({ image, speaker: lines[i].speaker, text: lines[i].text });
  }
  return out;
}

export function render(root, ctx) {
  const { data, params } = ctx;
  const start = sceneById(params[0]) ? params[0] : data.map?.start;
  if (!start) {
    root.innerHTML = `<div class="page"><div class="empty-state"><h2>Rien à lire pour l'instant</h2><a class="btn primary" href="#/commencer">Commencer l'histoire</a></div></div>`;
    return;
  }
  root.innerHTML = `<div class="player" tabindex="0">
    <div class="stage" id="stage"></div>
    <div class="crumb" id="crumb"></div>
    <div class="hud"><button class="btn small" id="restart">Recommencer</button><a class="btn small" href="#/carte">Quitter</a></div>
    <div class="box" id="box"><div class="who" id="who"></div><div class="text" id="text"></div></div>
    <div class="menu hidden" id="menu"></div>
  </div>`;
  const player = root.querySelector(".player");
  const $ = (id) => root.querySelector(`#${id}`);
  let history = []; // [{sid, k}]
  let sid = start, k = 0, list = [];

  const enter = (id) => { sid = id; k = 0; list = steps(sceneById(id)); show(); };
  const show = () => {
    const sc = sceneById(sid);
    $("crumb").textContent = `${sc.chapter_title || `Chapitre ${sc.chapter}`} · ${sc.title}`;
    $("menu").classList.add("hidden");
    if (k >= list.length) return end();
    const step = list[k];
    if (step.image) $("stage").style.backgroundImage = `url("${step.image}")`;
    $("who").textContent = step.speaker && step.speaker !== NARRATOR ? step.speaker : "";
    $("text").classList.toggle("voice", step.speaker === NARRATOR);
    if (step.text) $("text").textContent = step.text;
    else $("text").innerHTML = `<span class="faint">…</span>`; // image seule : un clic pour continuer
  };
  const end = () => {
    const st = sceneState(sid);
    const edges = (data.map?.edges || []).filter((e) => e.source === sid && sceneById(e.target));
    const choices = edges.filter((e) => e.kind === "choice");
    const next = edges.find((e) => e.kind === "next");
    const menu = $("menu");
    if (choices.length) {
      menu.innerHTML = choices.map((c, i) => `<button data-to="${esc(c.target)}">${i + 1}. ${esc(c.label || "Continuer")}</button>`).join("");
    } else if (next) {
      history.push({ sid, k }); enter(next.target); return;
    } else if (st.open) {
      menu.innerHTML = `<p style="text-align:center;font:26px var(--serif)">Cette ligne attend sa suite.</p>
        <button data-write="${esc(sid)}">L'écrire maintenant</button><button data-restart>Recommencer</button>`;
    } else {
      menu.innerHTML = `<p style="text-align:center;font:34px var(--serif)">Fin</p><button data-restart>Recommencer</button><button data-map>Retour à la carte</button>`;
    }
    menu.classList.remove("hidden");
  };
  const advance = () => {
    if (!$("menu").classList.contains("hidden")) return;
    history.push({ sid, k });
    k += 1;
    show();
  };
  const back = () => {
    const prev = history.pop();
    if (!prev) return;
    if (prev.sid !== sid) { sid = prev.sid; list = steps(sceneById(sid)); }
    k = prev.k;
    show();
  };
  const restart = () => { history = []; enter(data.map?.start || start); };

  $("box").addEventListener("click", advance);
  $("stage").addEventListener("click", advance);
  $("restart").addEventListener("click", restart);
  $("menu").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.to) { history.push({ sid, k }); enter(b.dataset.to); }
    else if (b.dataset.write) ctx.go(`#/scene/${encodeURIComponent(b.dataset.write)}/suite`);
    else if ("restart" in b.dataset) restart();
    else if ("map" in b.dataset) ctx.go("#/carte");
  });
  const onKey = (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if ([" ", "Enter", "ArrowRight"].includes(e.key)) { e.preventDefault(); advance(); }
    else if (e.key === "ArrowLeft") back();
    else if (e.key === "Escape") ctx.go("#/carte");
    else if (/^[1-4]$/.test(e.key)) $("menu").querySelectorAll("button[data-to]")[+e.key - 1]?.click();
  };
  document.addEventListener("keydown", onKey);
  enter(start);
  player.focus();
  return () => document.removeEventListener("keydown", onKey);
}
