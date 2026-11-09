// Accès au serveur local. Chaque requête qui modifie l'histoire porte l'en-tête X-Renpy-Maker
// (protection contre les autres sites, voir server.py).

export class ApiError extends Error {}

export async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", "X-Renpy-Maker": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError("Le moteur ne répond pas : l'application est-elle toujours lancée ?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `Erreur ${res.status}`);
  return data;
}

export const get = (path) => api("GET", path);
export const post = (path, body = {}) => api("POST", path, body);

// ---------- Tâches longues (une à la fois côté serveur) ----------
// Une route qui renvoie {job} lance un travail de fond : on le suit jusqu'au bout.

const listeners = new Set();
let current = null; // {id, label, state, message, progress, error}

export function onJob(fn) { listeners.add(fn); fn(current); return () => listeners.delete(fn); }
function emit() { for (const fn of listeners) fn(current); }
export const currentJob = () => current;

export function track(jobId, label) {
  return new Promise((resolve, reject) => {
    current = { id: jobId, label, state: "running", message: "", progress: null };
    emit();
    const tick = async () => {
      let job;
      try {
        job = await get(`/api/facile/jobs/${jobId}`);
      } catch (e) {
        setTimeout(tick, 2500); // moteur occupé ou coupure brève : on réessaie
        return;
      }
      current = { id: jobId, label: job.label || label, state: job.state, message: job.message,
                  progress: job.progress, error: job.error };
      emit();
      if (job.state === "running") return setTimeout(tick, 1000);
      const done = current;
      setTimeout(() => { if (current && current.id === jobId) { current = null; emit(); } }, job.state === "done" ? 1200 : 0);
      if (job.state === "done") resolve(done);
      else if (job.state === "cancelled") reject(new ApiError("Arrêté"));
      else reject(new ApiError(job.error || "La tâche a échoué"));
    };
    setTimeout(tick, 600);
  });
}

export async function cancelJob() {
  if (!current) return;
  await post("/api/facile/job/cancel", { job: current.id });
}

// Lance une route ; si elle démarre une tâche, attend sa fin.
export async function run(path, body, label) {
  const res = await post(path, body);
  if (res && res.job) return track(res.job, label);
  return res;
}
