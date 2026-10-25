"""Tâches longues du parcours simple : une à la fois, suivies par la page."""

from __future__ import annotations

import threading
import traceback
import uuid

from renpy_maker.facile_base import _ensure_token

JOBS: dict[str, dict] = {}

_busy = threading.Lock()

def _start(label: str, work, *args) -> dict:
    if not _busy.acquire(blocking=False):
        raise ValueError("Une création est déjà en cours : elle apparaîtra dès qu'elle sera terminée.")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"state": "running", "label": label, "message": "", "error": None, "progress": None,
                    "cancel_requested": False, "comfy_prompt": None}

    def run():
        try:
            _ensure_token()
            work(job_id, *args)
            JOBS[job_id]["state"] = "done"
        except Exception as e:  # le message est montré à l'utilisateur, la trace reste dans le journal serveur
            if JOBS[job_id]["cancel_requested"]:
                JOBS[job_id].update(state="cancelled", message="Génération arrêtée")
            else:
                traceback.print_exc()
                JOBS[job_id].update(state="error", error=f"{type(e).__name__}: {e}")
        finally:
            _busy.release()

    threading.Thread(target=run, daemon=True).start()
    return {"job": job_id}

def _say(job_id: str, message: str) -> None:
    JOBS[job_id]["message"] = message
    JOBS[job_id]["progress"] = None  # une nouvelle étape repart de zéro

class Cancelled(Exception):
    """Arrêt demandé par l'auteur : la tâche s'arrête entre deux images."""

def _check_cancel(job_id: str) -> None:
    if JOBS[job_id]["cancel_requested"]:
        raise Cancelled("arrêtée")

def _submit(job_id: str):
    """Mémorise l'identifiant ComfyUI de la génération en cours, pour pouvoir l'arrêter."""
    def remember(prompt_id: str) -> None:
        JOBS[job_id]["comfy_prompt"] = prompt_id
    return remember

def cancel_job(job_id: str) -> dict:
    """Arrête une tâche en cours. ComfyUI n'est interrompu que si cette tâche a une génération en cours là-bas."""
    job = JOBS.get(job_id)
    if job is None or job["state"] != "running":
        raise ValueError("Cette tâche n'est plus en cours")
    job["cancel_requested"] = True
    if job.get("comfy_prompt"):
        from renpy_maker import comfy_client as CC
        from renpy_maker import comfy_image
        try:
            CC.interrupt(comfy_image.base_url(), job["comfy_prompt"])
        except OSError:
            pass  # ComfyUI injoignable : la tâche s'arrête à l'étape suivante
    return {"ok": True}

def _progress(job_id: str):
    """Callback d'avancement de ComfyUI pour une tâche : étape courante sur le total."""
    def update(value: int, maximum: int) -> None:
        if job_id in JOBS and maximum > 0:
            JOBS[job_id]["progress"] = {"value": value, "max": maximum}
    return update
