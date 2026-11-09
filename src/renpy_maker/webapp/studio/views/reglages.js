// Réglages : une seule roue pour toute l'application (histoire, écriture, images, clé, outils avancés).

import { get, post } from "../api.js";
import { dialog, esc, toast } from "../ui.js";

export async function open(ctx) {
  let s;
  try { s = await get("/api/facile/settings"); } catch (e) { return toast(e.message, "error"); }
  const d = ctx.data;
  const providers = s.text.choices;
  const providerOptions = (cur, withDefault) => (withDefault ? `<option value="">(comme l'écriture)</option>` : "")
    + providers.map((p) => `<option value="${esc(p.name)}" ${p.name === cur ? "selected" : ""}>${esc(p.label)}${p.key ? "" : " · clé absente"}</option>`).join("");
  const current = providers.find((p) => p.name === s.text.provider) || {};
  const engines = Object.entries(s.engine_labels || { replicate: "Replicate" });
  const html = `
    <section class="stack"><p class="section-title">Cette histoire</p>
      <label class="check"><input type="checkbox" name="auto_draw" ${d.recit?.auto_draw ? "checked" : ""}><span>Dessiner tout de suite chaque nouveau moment gardé</span></label>
      <div class="row">
        <label class="field" style="flex:1"><span>Images proposées par scène (découpage IA)</span>
          <select name="max_plans">${(d.plan_limits || [0, 1, 2, 3, 4, 5, 6, 7, 8]).map((n) => `<option ${n === d.max_plans ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label class="field" style="flex:1"><span>Personnages</span><select name="character_mode">
          <option value="auto" ${d.character_mode !== "designer" ? "selected" : ""}>Dessinés automatiquement</option>
          <option value="designer" ${d.character_mode === "designer" ? "selected" : ""}>Je les décris d'abord (Designer)</option></select></label>
      </div>
      ${s.kids ? "" : `<label class="check"><input type="checkbox" name="explicit" ${d.explicit ? "checked" : ""}><span>Contenu pour adultes autorisé <small class="muted">(transmis au modèle, qui peut refuser)</small></span></label>`}
    </section>

    <section class="stack"><p class="section-title">Écriture (modèle de langage)</p>
      <div class="row">
        <label class="field" style="flex:2"><span>Fournisseur</span><select name="text_provider">${providerOptions(s.text.provider)}</select></label>
        <label class="field" style="flex:2"><span>Modèle</span><input type="text" name="text_model" placeholder="${esc(current.model || "")}"></label>
      </div>
      ${s.kids ? "" : `<details><summary class="small"><b>Par tâche</b> (fournisseur et modèle différents selon le travail)</summary>
        <div class="stack" style="margin-top:8px">${s.tasks.map((t) => `<div class="row task-row" data-task="${esc(t.task)}">
          <span class="small" style="flex:2;min-width:160px">${esc(t.label)}</span>
          <select name="task_provider" style="flex:2">${providerOptions(t.provider, true)}</select>
          <input type="text" name="task_model" value="${esc(t.model || "")}" placeholder="modèle" style="flex:2"></div>`).join("")}</div></details>`}
    </section>

    ${s.kids ? "" : `<section class="stack"><p class="section-title">Images</p>
      ${s.image_rows.map((r) => `<div class="row image-row" data-role="${esc(r.role)}" style="align-items:flex-end">
        <span class="small" style="flex:2;min-width:150px;font-weight:700">${esc(r.label)}</span>
        <label class="field" style="flex:2"><span>Moteur</span><select name="engine">${engines.map(([k, l]) => `<option value="${esc(k)}" ${k === r.engine ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
        <label class="field" style="flex:3"><span>Workflow ComfyUI</span><select name="workflow"><option value="">(par défaut)</option>${r.choices.map((c) => `<option ${c === r.workflow ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
        <label class="field" style="flex:1;min-width:80px"><span>Étapes</span><input type="number" name="steps" value="${esc(r.steps)}" min="1" max="100"></label></div>`).join("")}
      <label class="check small"><input type="checkbox" name="comfy_free_memory" ${s.comfy_free_memory ? "checked" : ""}><span>Libérer la mémoire de ComfyUI avant chaque génération</span></label>
      <label class="check small"><input type="checkbox" name="unload_ollama_before_comfy" ${s.unload_ollama_before_comfy ? "checked" : ""}><span>Décharger Ollama avant une génération ComfyUI</span></label>
      <label class="check small"><input type="checkbox" name="free_comfy_before_ollama" ${s.free_comfy_before_ollama ? "checked" : ""}><span>Libérer ComfyUI avant un appel à Ollama</span></label>
    </section>`}

    <section class="stack"><p class="section-title">Clé Replicate</p>
      <label class="field"><span>${s.replicate_key ? "Une clé est enregistrée. Pour la remplacer :" : "Aucune clé : les images (et l'écriture par Replicate) en ont besoin."}</span>
        <input type="password" name="replicate_key" autocomplete="off" placeholder="r8_…"></label>
      <small class="muted">Les clés Anthropic et OpenAI se donnent par variable d'environnement (voir le README).</small>
    </section>

    ${s.kids ? "" : `<details class="card"><summary><b>Outils avancés</b> <small class="muted">(anciennes pages, en attendant leur reprise dans le studio)</small></summary>
      <ul class="list small" style="margin-top:8px">
        <li><a href="/recit">Récit plein écran</a> : la scène de théâtre et le micro</li>
        <li><a href="/atelier">Atelier</a> : graphe des références, glisser-déposer depuis la bobine</li>
        <li><a href="/histoire">Éditeur expert</a> : verrouillage, expression par réplique, angle de caméra, graine</li>
        <li><a href="/">Registre d'actifs</a> : objets, candidats écartés, format et graine</li>
        <li><a href="/automatique">Pipeline automatique</a> : plusieurs chapitres d'un coup</li>
        <li><a href="/facile">Parcours guidé</a> : l'ancien pas à pas</li>
      </ul></details>`}`;

  const res = await dialog({
    title: "Réglages", html, wide: true,
    buttons: [{ label: "Fermer", value: null }, { label: "Enregistrer", kind: "primary", value: (root) => root }],
  });
  if (!res) return;
  const root = res;
  const val = (n) => root.querySelector(`[name=${n}]`);
  try {
    const body = {
      text_provider: val("text_provider").value, text_model: val("text_model").value,
      tasks: [...root.querySelectorAll(".task-row")].map((r) => ({
        task: r.dataset.task, provider: r.querySelector("[name=task_provider]").value || null,
        model: r.querySelector("[name=task_model]").value })),
    };
    if (!s.kids) {
      body.images = [...root.querySelectorAll(".image-row")].map((r) => ({
        role: r.dataset.role, engine: r.querySelector("[name=engine]").value,
        workflow: r.querySelector("[name=workflow]").value, steps: r.querySelector("[name=steps]").value }));
      for (const k of ["comfy_free_memory", "unload_ollama_before_comfy", "free_comfy_before_ollama"]) body[k] = val(k).checked;
    }
    await post("/api/facile/settings", body);
    if (val("auto_draw").checked !== !!d.recit?.auto_draw) await post("/api/recit/options", { auto_draw: val("auto_draw").checked });
    if (+val("max_plans").value !== d.max_plans) await post("/api/facile/settings/max-plans", { max_plans: +val("max_plans").value });
    if (val("character_mode").value !== (d.character_mode || "auto")) await post("/api/facile/character-mode", { mode: val("character_mode").value });
    if (!s.kids && val("explicit").checked !== !!d.explicit) await post("/api/story/settings", { explicit_content: val("explicit").checked });
    const key = val("replicate_key").value.trim();
    if (key) await post("/api/facile/secret", { name: "REPLICATE_API_TOKEN", value: key });
    toast("Réglages enregistrés");
    await ctx.refresh();
  } catch (e) {
    toast(e.message, "error");
  }
}
