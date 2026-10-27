"""Servidor falso del Geode Index (solo localhost) y utilidades para fabricar .geode."""
from __future__ import annotations

import hashlib
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def make_geode(path: Path, manifest: dict, native: bool = False, extra: dict[str, bytes] | None = None) -> bytes:
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mod.json", json.dumps(manifest))
        z.writestr("resources/readme.txt", "hola")
        if native:
            z.writestr(f"{manifest['id']}.dll", b"MZ\x00fake")
            z.writestr(f"{manifest['id']}.dylib", b"\xcf\xfa\xed\xfefake")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path.read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MockIndex:
    def __init__(self):
        self.loader = {"tag": "v9.9.9", "gd": {"win": "2.2081", "mac": "2.2081"}}
        self.versions: dict[str, dict] = {}   # mod_id -> payload de /versions/latest
        self.repos: dict[str, str] = {}       # mod_id -> url del repo
        self.files: dict[str, bytes] = {}     # nombre -> contenido
        self.requests: list[str] = []
        self._srv: HTTPServer | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_port}"

    def offer(self, manifest: dict, data: bytes, hash_override: str | None = "auto", no_hash: bool = False):
        name = f"{manifest['id']}-{manifest['version']}.geode"
        self.files[name] = data
        payload = {"mod_id": manifest["id"], "version": manifest["version"],
                   "download_link": f"{self.base}/files/{name}", "gd": manifest.get("gd")}
        if not no_hash:
            payload["hash"] = sha256(data) if hash_override == "auto" else hash_override
        self.versions[manifest["id"]] = payload

    def start(self) -> "MockIndex":
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencio
                pass

            def _send(self, code, body: bytes, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                outer.requests.append(self.path)
                if path == "/v1/loader/versions/latest":
                    return self._send(200, json.dumps({"error": "", "payload": outer.loader}).encode())
                if path.startswith("/files/"):
                    data = outer.files.get(path[len("/files/"):])
                    return self._send(200, data, "application/octet-stream") if data else self._send(404, b"{}")
                parts = path.split("/")  # ['', 'v1', 'mods', id, 'versions', 'latest']
                if len(parts) == 6 and parts[2] == "mods" and parts[4] == "versions":
                    p = outer.versions.get(parts[3])
                    return self._send(200, json.dumps({"error": "", "payload": p}).encode()) if p else self._send(404, b"{}")
                if len(parts) == 4 and parts[2] == "mods":
                    repo = outer.repos.get(parts[3])
                    body = {"error": "", "payload": {"id": parts[3], "repository": repo}}
                    return self._send(200, json.dumps(body).encode())
                self._send(404, b"{}")

        self._srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
