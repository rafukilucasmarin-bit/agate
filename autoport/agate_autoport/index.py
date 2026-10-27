"""Cliente mínimo del Geode Index (https://api.geode-sdk.org/v1).

Endpoints usados (confirmados en el código del loader de Geode):
  /loader/versions/latest?platform=<win|mac>
  /mods/{id}
  /mods/{id}/versions/{version|latest}?platform=..&gd=..

Los nombres exactos de los campos del JSON están aislados en `_parse_*` para poder
ajustarlos en un único sitio si el servidor cambia. Nada de lo que devuelve el servidor
se da por bueno sin comprobarlo: el paquete descargado se verifica con SHA-256 y se
revisa su mod.json antes de instalarlo (ver porter.py).
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE = "https://api.geode-sdk.org/v1"
MAX_DOWNLOAD = 256 * 1024 * 1024


class IndexError_(Exception):
    pass


@dataclass
class LoaderInfo:
    tag: str
    gd: dict[str, str]


@dataclass
class VersionInfo:
    mod_id: str
    version: str
    download_link: str
    sha256: str | None
    gd: dict[str, str] = field(default_factory=dict)


def _payload(doc: dict):
    if not isinstance(doc, dict) or "payload" not in doc:
        raise IndexError_("respuesta inesperada del Index")
    if doc.get("error"):
        raise IndexError_(str(doc["error"]))
    return doc["payload"]


def _gd_map(raw) -> dict[str, str]:
    if isinstance(raw, dict):
        return {k: str(v).lstrip("v") for k, v in raw.items() if v}
    if isinstance(raw, str):
        return {"*": raw.lstrip("v")}
    return {}


def _parse_loader(payload: dict) -> LoaderInfo:
    tag = payload.get("tag") or payload.get("version")
    if not tag:
        raise IndexError_("el Index no devolvió la versión del loader")
    return LoaderInfo(str(tag), _gd_map(payload.get("gd")))


def _parse_version(payload: dict) -> VersionInfo:
    link = payload.get("download_link")
    if not link:
        raise IndexError_("la versión no trae enlace de descarga")
    return VersionInfo(
        mod_id=str(payload.get("mod_id") or payload.get("id") or ""),
        version=str(payload.get("version", "")),
        download_link=str(link),
        sha256=(payload.get("hash") or payload.get("sha256") or None),
        gd=_gd_map(payload.get("gd")),
    )


class IndexClient:
    def __init__(self, base: str = DEFAULT_BASE, user_agent: str = "agate-autoport",
                 require_https: bool = True, timeout: float = 20.0, opener=None):
        self.base = base.rstrip("/")
        self.ua = user_agent
        self.require_https = require_https
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    # -- internals ---------------------------------------------------------
    def _check_url(self, url: str) -> None:
        scheme = urllib.parse.urlparse(url).scheme
        if self.require_https and scheme != "https":
            raise IndexError_(f"se rechaza URL no HTTPS: {url}")

    def _get(self, url: str):
        self._check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "application/json"})
        return self._open(req, timeout=self.timeout)

    def _get_json(self, path: str, **query):
        q = {k: v for k, v in query.items() if v is not None}
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        with self._get(url) as resp:
            return json.loads(resp.read(8 * 1024 * 1024))

    # -- API ---------------------------------------------------------------
    def latest_loader(self, platform: str) -> LoaderInfo:
        return _parse_loader(_payload(self._get_json("/loader/versions/latest", platform=platform)))

    def latest_version(self, mod_id: str, platform: str, gd: str) -> VersionInfo | None:
        """Última versión del mod compatible con `gd`; None si no existe (404)."""
        path = f"/mods/{urllib.parse.quote(mod_id, safe='')}/versions/latest"
        try:
            return _parse_version(_payload(self._get_json(path, platform=platform, gd=gd)))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise IndexError_(f"HTTP {e.code} consultando {mod_id}") from e

    def mod_repository(self, mod_id: str) -> str | None:
        path = f"/mods/{urllib.parse.quote(mod_id, safe='')}"
        try:
            p = _payload(self._get_json(path))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise IndexError_(f"HTTP {e.code} consultando {mod_id}") from e
        links = p.get("links") or {}
        return p.get("repository") or links.get("source") or links.get("repository")

    def download(self, url: str, dest: Path, expected_sha256: str | None) -> str:
        """Descarga a `dest` y verifica SHA-256. Sin hash esperado => se rechaza."""
        if not expected_sha256:
            raise IndexError_("el Index no proporcionó hash; no se instala nada sin verificarlo")
        h = hashlib.sha256()
        size = 0
        with self._get(url) as resp:
            if self.require_https and urllib.parse.urlparse(resp.geturl()).scheme != "https":
                raise IndexError_("la descarga fue redirigida a una URL no HTTPS")
            with open(dest, "wb") as out:
                while chunk := resp.read(1 << 16):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise IndexError_("descarga demasiado grande")
                    h.update(chunk)
                    out.write(chunk)
        digest = h.hexdigest()
        if digest.lower() != expected_sha256.strip().lower():
            dest.unlink(missing_ok=True)
            raise IndexError_(f"SHA-256 no coincide (esperado {expected_sha256[:12]}…, obtenido {digest[:12]}…)")
        return digest
