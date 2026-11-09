// Commencer : le cadre de l'histoire (titre, idée, ambiance, style), puis deux départs :
// l'IA écrit le plan, ou l'on écrit en jouant (premier moment, à la manière du récit).

import { post, run } from "../api.js";
import { bind, busy, esc, plural, toast } from "../ui.js";

let firstMoment = null; // proposition du tout premier moment

export function render(root, ctx) {
  const paint = () => {
    const { data } = ctx;
    const started = data.scenes.length > 0;
    const styleLocked = (!!data.written || started) && !!data.style; // un style manquant peut toujours être choisi
    const ambiances = data.recit?.ambiances || [];
    root.innerHTML = `<div class="start">
      <div><h1>${started ? "Le cadre de l'histoire" : "Une nouvelle histoire"}</h1>
        <p class="muted">${started ? "Le cadre guide l'IA à chaque proposition. Il reste modifiable, sauf le style des images une fois l'histoire commencée."
          : "Posez le décor : quelques phrases suffisent. Ensuite, choisissez comment commencer."}</p></div>
      <section class="card print stack">
        <label class="field"><span>Titre</span><input type="text" name="title" value="${esc(data.title)}" placeholder="Par exemple : Le phare"></label>
        <label class="field"><span>De quoi parle l'histoire ?</span><textarea name="idea" rows="4" placeholder="Une gardienne de phare trouve un message dans une bouteille…">${esc(data.idea)}</textarea></label>
        <label class="field"><span>Ambiance</span><input type="text" name="ambiance" value="${esc(data.recit?.ambiance || "")}" placeholder="Par exemple : mystérieuse, sous la pluie">
          <div class="chips" style="margin-top:4px">${ambiances.map((a) => `<button class="chip" data-act="ambiance" data-v="${esc(a)}">${esc(a)}</button>`).join("")}</div></label>
        <div class="field"><span>Style des images</span>
          <div class="styles">${(data.styles || []).map((s) => `<button class="style-card" data-act="style" data-key="${esc(s.key)}" aria-pressed="${s.key === data.style}" ${styleLocked && s.key !== data.style ? "disabled" : ""}>
            <b>${esc(s.name)}</b><small>${esc(s.desc)}</small></button>`).join("")}</div>
          ${styleLocked ? `<small>L'histoire a commencé : le style ne change plus.</small>` : started ? `<small>Aucun style choisi : choisissez-en un pour pouvoir dessiner.</small>` : ""}</div>
        <div class="row end"><button class="btn primary" data-act="save">Enregistrer le cadre</button></div>
      </section>
      ${started ? `<div class="row"><a class="btn" href="#/carte">Aller à la carte</a></div>` : starts(data)}
    </div>`;
  };
  ctx.rerender = paint;
  paint();
  let chosenStyle = null;

  const frame = async () => {
    const v = (n) => root.querySelector(`[name=${n}]`).value;
    await post("/api/recit/frame", { title: v("title"), idea: v("idea"), ambiance: v("ambiance"), style: chosenStyle || ctx.data.style || null });
    await ctx.refresh({ render: false });
  };

  bind(root, {
    ambiance: (el) => { root.querySelector("[name=ambiance]").value = el.dataset.v; },
    style: (el) => {
      chosenStyle = el.dataset.key;
      root.querySelectorAll(".style-card").forEach((b) => b.setAttribute("aria-pressed", b === el));
    },
    save: (el) => busy(el, async () => { await frame(); toast("Cadre enregistré"); paint(); }),
    plan: (el) => busy(el, async () => {
      await frame();
      if (!ctx.data.style) return toast("Choisissez d'abord le style des images", "error");
      const count = +root.querySelector("[name=count]").value;
      const explicit = !!root.querySelector("[name=explicit]")?.checked;
      await run("/api/facile/story", { title: ctx.data.title, idea: ctx.data.idea, count, explicit }, "Écriture de l'histoire");
      toast("Le plan est écrit : voici la carte de l'histoire.");
      await ctx.refresh({ render: false });
      ctx.go("#/carte");
    }),
    "first-propose": (el) => busy(el, async () => {
      await frame();
      if (!ctx.data.style) return toast("Choisissez d'abord le style des images", "error");
      firstMoment = await post("/api/recit/propose", { scene: null, previous: firstMoment });
      paint();
    }),
    "first-keep": (el) => busy(el, async () => {
      const box = root.querySelector("#first");
      const v = (n) => box.querySelector(`[name=${n}]`).value;
      const m = { ...firstMoment, voix_off: v("voix_off"), speaker: v("speaker"), text: v("text"),
                  location: { ...(firstMoment.location || {}), name: v("location") } };
      const res = await post("/api/recit/moment", { scene: null, moment: m });
      firstMoment = null;
      toast("L'histoire commence !");
      await ctx.refresh({ render: false });
      ctx.go(`#/scene/${encodeURIComponent(res.scene)}/suite`);
    }),
  });
}

function starts(data) {
  const counts = data.counts || [3, 4, 5, 6];
  const cast = data.characters.length;
  const m = firstMoment;
  return `<section class="stack"><h2>Comment commencer ?</h2>
    <div class="paths">
      <div class="card stack">
        <h3>L'IA écrit le plan</h3>
        <p class="small muted">Un premier chapitre complet : les scènes, leurs répliques, les personnages et les lieux. Vous corrigez ensuite tout ce que vous voulez.</p>
        <label class="field"><span>Nombre de scènes</span><select name="count">${counts.map((n) => `<option ${n === (data.count || 4) ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        ${data.kids ? "" : `<label class="check small"><input type="checkbox" name="explicit" ${data.explicit ? "checked" : ""}><span>Contenu pour adultes autorisé</span></label>`}
        <button class="btn ai primary" data-act="plan">Écrire le plan</button>
      </div>
      <div class="card stack">
        <h3>Écrire en jouant</h3>
        <p class="small muted">L'histoire s'écrit moment après moment : l'IA propose, vous gardez, vous modifiez, ou vous lui dites ce qui doit changer. Les choix ouvrent des lignes.</p>
        <p class="small">${cast ? `${plural(cast, "personnage", "personnages")} prêt${cast > 1 ? "s" : ""}.` : `Commencez par <a href="#/personnages">les personnages</a> (conseillé).`}</p>
        ${m ? "" : `<button class="btn ai primary" data-act="first-propose">Proposer le premier moment</button>`}
      </div>
    </div>
    ${m ? `<div class="proposal" id="first">
      <p class="section-title" style="margin:0">Le premier moment</p>
      <label class="field"><span>Lieu</span><input type="text" name="location" value="${esc(m.location?.name || "")}"></label>
      <label class="field"><span>Voix off</span><textarea class="voice" name="voix_off" rows="2">${esc(m.voix_off || "")}</textarea></label>
      <div class="row" style="align-items:flex-start">
        <label class="field" style="width:180px"><span>Qui parle</span><select name="speaker">${["", "Narration", ...data.characters.map((c) => c.name)].map((n) => `<option value="${esc(n)}" ${n === (m.speaker || "") ? "selected" : ""}>${n ? esc(n) : "(pas de réplique)"}</option>`).join("")}</select></label>
        <label class="field" style="flex:1;min-width:220px"><span>Réplique</span><textarea name="text" rows="2">${esc(m.text || "")}</textarea></label>
      </div>
      <div class="row end"><button class="btn" data-act="first-propose">Une autre proposition</button><button class="btn primary" data-act="first-keep">Commencer ici</button></div>
    </div>` : ""}
  </section>`;
}
