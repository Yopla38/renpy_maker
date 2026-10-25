"""Client ComfyUI minimal : charge un workflow (format éditeur ou API), le convertit
au besoin, l'envoie à /prompt, attend la fin et récupère les fichiers produits.

Usage (test) :
    python comfy_client.py <workflow.json> [--set NODE_ID.input=valeur ...] [--out DIR]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8188"
SEED_CONTROLS = {"fixed", "increment", "decrement", "randomize"}


def _get(url: str, base: str) -> dict:
    with urllib.request.urlopen(base + url, timeout=30) as r:
        return json.loads(r.read())


def _post(path: str, payload: dict, base: str) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def is_api_format(wf: dict) -> bool:
    return "nodes" not in wf and all(
        isinstance(v, dict) and "class_type" in v for v in wf.values()
    )


def ui_to_api(wf: dict, object_info: dict) -> dict:
    """Convertit un workflow éditeur (nodes + links) en graphe API.

    Les valeurs de widgets sont associées aux entrées dans l'ordre déclaré par
    /object_info (required puis optional). Les entrées reliées par un lien sont
    prises dans les liens. Une valeur de contrôle de graine ('randomize', etc.)
    est sautée.
    """
    links = {l[0]: l for l in wf.get("links", [])}
    api: dict[str, dict] = {}
    for node in wf["nodes"]:
        ctype = node["type"]
        if ctype in ("Note", "MarkdownNote", "PrimitiveNode", "Reroute"):
            continue
        info = object_info.get(ctype)
        if info is None:
            raise ValueError(f"Nœud inconnu côté serveur : {ctype} (id {node['id']})")
        spec = info["input"]
        ordered = list(spec.get("required", {}).items()) + list(
            spec.get("optional", {}).items()
        )
        linked = {}
        for inp in node.get("inputs", []):
            if inp.get("link") is not None and inp["name"] in dict(ordered):
                linked[inp["name"]] = links[inp["link"]][1:3]  # [src_id, src_slot]
        widgets = list(node.get("widgets_values") or [])
        entry: dict = {"class_type": ctype, "inputs": {}}
        wi = 0
        for name, decl in ordered:
            if name in linked:
                entry["inputs"][name] = [str(linked[name][0]), linked[name][1]]
                continue
            kind = decl[0]
            if isinstance(kind, list) or kind in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                if wi >= len(widgets):
                    break
                entry["inputs"][name] = widgets[wi]
                wi += 1
                if (
                    name in ("seed", "noise_seed")
                    and wi < len(widgets)
                    and isinstance(widgets[wi], str)
                    and widgets[wi] in SEED_CONTROLS
                ):
                    wi += 1
        api[str(node["id"])] = entry
    # Liens restants vers des nœuds ignorés (Reroute, Note) : non gérés, à signaler.
    return api


def load_workflow(path: Path, base: str = DEFAULT_URL) -> dict:
    wf = json.loads(path.read_text(encoding="utf-8"))
    if is_api_format(wf):
        return wf
    needed = {n["type"] for n in wf["nodes"]}
    object_info = {}
    for t in needed:
        try:
            object_info.update(_get(f"/object_info/{urllib.parse.quote(t)}", base))
        except Exception:
            pass
    return ui_to_api(wf, object_info)


def set_input(api: dict, dotted: str, value) -> None:
    """dotted = 'NODE_ID.input_name', ex. '64.text'."""
    node_id, name = dotted.split(".", 1)
    api[node_id]["inputs"][name] = value


class WebSocketConnection:
    """Client WebSocket minimal (bibliothèque standard) pour le canal /ws de ComfyUI.

    Il ne lit que les messages du serveur (texte JSON : avancement, états) et répond aux pings.
    """

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""

    @classmethod
    def open(cls, base: str, client_id: str, timeout: float = 10.0) -> "WebSocketConnection":
        u = urllib.parse.urlparse(base)
        port = u.port or 80
        sock = socket.create_connection((u.hostname, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET /ws?clientId={client_id} HTTP/1.1\r\nHost: {u.hostname}:{port}\r\n"
                      "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(1024)
            if not chunk:
                sock.close()
                raise ConnectionError("WebSocket fermé pendant la poignée de main")
            head += chunk
        header, _, rest = head.partition(b"\r\n\r\n")
        if b" 101 " not in header.split(b"\r\n")[0]:
            sock.close()
            raise ConnectionError("Connexion WebSocket refusée par ComfyUI")
        conn = cls(sock)
        conn.buf = rest
        return conn

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("WebSocket fermé")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def recv(self, timeout: float) -> tuple[int, bytes] | None:
        """Prochain message (opcode, données), ou None si rien n'arrive pendant « timeout » secondes."""
        self.sock.settimeout(timeout)
        try:
            if not self.buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("WebSocket fermé")
                self.buf += chunk
        except socket.timeout:
            return None
        self.sock.settimeout(60)
        opcode = self._read(1)[0] & 0x0F
        length = self._read(1)[0] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(length)
        if opcode == 9:  # ping : le serveur attend un pong (masqué, côté client)
            self._send_frame(10, payload)
            return self.recv(timeout)
        if opcode == 8:
            raise ConnectionError("WebSocket fermé par ComfyUI")
        return opcode, payload

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        else:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def interrupt(base: str = DEFAULT_URL, prompt_id: str | None = None) -> None:
    """Arrête la génération en cours et retire la génération demandée de la file d'attente."""
    _post("/interrupt", {}, base)
    if prompt_id:
        _post("/queue", {"delete": [prompt_id]}, base)


def run(api: dict, base: str = DEFAULT_URL, timeout_s: int = 1800, on_progress=None, on_submit=None) -> list[dict]:
    """Envoie le graphe et renvoie la liste des fichiers produits (dict nom/subfolder/type).

    on_progress(valeur, maximum) est appelé à chaque étape d'échantillonnage, si le canal WebSocket
    est disponible. Sans lui, la génération reste suivie par interrogation, comme avant.
    """
    client_id = str(uuid.uuid4())
    ws = None
    try:
        ws = WebSocketConnection.open(base, client_id)
    except OSError:
        ws = None  # pas de suivi en direct, mais la génération se fait quand même
    try:
        resp = _post("/prompt", {"prompt": api, "client_id": client_id}, base)
        if "error" in resp or resp.get("node_errors"):
            raise RuntimeError(f"Refus du serveur : {resp}")
        pid = resp["prompt_id"]
        if on_submit is not None:
            on_submit(pid)  # permet d'arrêter cette génération précise
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if ws is not None:
                try:
                    while True:
                        message = ws.recv(timeout=0.5)
                        if message is None:
                            break
                        opcode, payload = message
                        if opcode != 1:
                            continue  # images d'aperçu (binaire) : ignorées
                        event = json.loads(payload)
                        if event.get("type") == "progress" and on_progress is not None:
                            data = event.get("data", {})
                            if data.get("prompt_id", pid) == pid:
                                on_progress(int(data.get("value", 0)), int(data.get("max", 0)))
                except (ConnectionError, OSError, ValueError):
                    ws.close()
                    ws = None
            hist = _get(f"/history/{pid}", base)
            if pid in hist:
                status = hist[pid].get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"Erreur d'exécution : {status}")
                files = []
                for out in hist[pid].get("outputs", {}).values():
                    for key in ("images", "gifs", "videos"):
                        files.extend(out.get(key, []))
                if files:
                    return files
            if ws is None:
                time.sleep(2)
        raise TimeoutError(f"Pas de résultat après {timeout_s}s pour {pid}")
    finally:
        if ws is not None:
            ws.close()


def upload_image(path: Path, base: str = DEFAULT_URL, overwrite: bool = True) -> str:
    """Envoie une image dans le dossier input de ComfyUI et renvoie son nom."""
    boundary = uuid.uuid4().hex
    data = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + data + (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        f"{'true' if overwrite else 'false'}\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        base + "/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["name"]


def download(files: list[dict], out_dir: Path, base: str = DEFAULT_URL) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        q = urllib.parse.urlencode(
            {"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}
        )
        dest = out_dir / f["filename"]
        with urllib.request.urlopen(f"{base}/view?{q}", timeout=120) as r:
            dest.write_bytes(r.read())
        saved.append(dest)
    return saved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", type=Path)
    ap.add_argument("--set", action="append", default=[], help="NODE_ID.input=valeur")
    ap.add_argument("--out", type=Path, default=Path("work/comfy_out"))
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args()

    api = load_workflow(args.workflow, args.url)
    for kv in args.set:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        set_input(api, k, v)
    files = run(api, args.url)
    for p in download(files, args.out, args.url):
        print(p)


if __name__ == "__main__":
    main()
