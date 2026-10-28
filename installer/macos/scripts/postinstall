#!/usr/bin/env python3
"""Descarga la última release OFICIAL de Geode (github.com/geode-sdk/geode) y deja los ficheros del
loader en build/payload/<plataforma>. Se ejecuta en CI al empaquetar los instaladores.

  win : se extrae el zip oficial (geode-vX-win.zip).
  mac : el zip oficial NO basta (no trae el libfmod.dylib sustituto ni los recursos). El contenido
        completo sale del instalador oficial .pkg: se expande con `pkgutil` (solo existe en macOS) y se
        usa su carpeta Payload/ (Geode.dylib, GeodeBootstrapper.dylib, libfmod.dylib, resources/).

Es deliberadamente estricto: si una release cambia de forma, FALLA en vez de empaquetar algo roto.

Uso: python tools/fetch_geode.py --out build [--platforms win,mac] [--tag v5.x.y]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "geode-sdk/geode"
API = f"https://api.github.com/repos/{REPO}/releases"
ASSET_RE = {
    "win": re.compile(r"^geode-v[\w.\-]+-win\.zip$", re.I),
    "mac": re.compile(r"^geode-v[\w.\-]+-mac\.zip$", re.I),                 # zip: ya no se usa para el instalador
    "macpkg": re.compile(r"^geode-installer-v[\w.\-]+-mac\.pkg$", re.I),    # instalador oficial: fuente del payload mac
}
# Win: según GeodeUpdater (reemplaza XInput1_4.dll, Geode.dll y recursos).
# Mac: comprobado contra el instalador oficial v5.11.2 (su Payload/ y su Scripts/postinstall).
REQUIRED = {
    "win": ["Geode.dll", "XInput1_4.dll"],
    "mac": ["Geode.dylib", "GeodeBootstrapper.dylib", "libfmod.dylib", "mod.json"],
}


def http_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agate-ci"})
    if tok := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pick_asset(assets: list[dict], key: str) -> dict:
    hits = [a for a in assets if ASSET_RE[key].match(a["name"])]
    if len(hits) != 1:
        names = ", ".join(a["name"] for a in assets)
        raise SystemExit(f"No pude elegir un único asset '{key}' (candidatos: {len(hits)}). "
                         f"Assets de la release: {names}. Ajusta ASSET_RE en tools/fetch_geode.py.")
    return hits[0]


def download(url: str, dest: Path, digest: str | None) -> None:
    h = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "agate-ci"}), timeout=300) as r, \
            open(dest, "wb") as f:
        while chunk := r.read(1 << 16):
            h.update(chunk)
            f.write(chunk)
    if digest and digest.startswith("sha256:") and h.hexdigest() != digest.split(":", 1)[1]:
        raise SystemExit(f"SHA-256 de {dest.name} no coincide con el publicado por GitHub")


def safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for m in zf.namelist():
        if not (root / m).resolve().is_relative_to(root):
            raise SystemExit(f"entrada peligrosa en el zip: {m}")
    zf.extractall(dest)


def check_layout(platform: str, payload: Path) -> None:
    present = {p.name.lower() for p in payload.rglob("*") if p.is_file()}
    missing = [f for f in REQUIRED[platform] if f.lower() not in present]
    if missing:
        listing = sorted(str(p.relative_to(payload)) for p in payload.rglob("*"))[:40]
        raise SystemExit(f"Layout inesperado en el payload de {platform}: faltan {missing}.\n"
                         f"Contenido: {listing}\nRevisa installer/ del repo oficial de Geode y ajusta REQUIRED.")


def expand_mac_pkg(pkg: Path, payload: Path, run=subprocess.run) -> None:
    """Expande el .pkg oficial y copia su Payload/ a `payload`."""
    if run is subprocess.run and sys.platform != "darwin":
        raise SystemExit("Extraer el .pkg oficial requiere macOS (pkgutil): ejecuta este paso en el runner de macOS.")
    expanded = pkg.parent / (pkg.stem + ".expanded")
    shutil.rmtree(expanded, ignore_errors=True)   # pkgutil exige que el destino no exista
    run(["pkgutil", "--expand-full", str(pkg), str(expanded)], check=True)
    src = expanded / "Payload"
    if not src.is_dir():
        raise SystemExit(f"El .pkg oficial no tiene Payload/ (hay: {[p.name for p in expanded.iterdir()]})")
    shutil.rmtree(payload, ignore_errors=True)
    shutil.copytree(src, payload)
    check_layout("mac", payload)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("build"))
    ap.add_argument("--tag")
    ap.add_argument("--platforms", default="win,mac", help="lista separada por comas")
    args = ap.parse_args()

    rel = http_json(f"{API}/tags/{args.tag}" if args.tag else f"{API}/latest")
    print(f"Release oficial de Geode: {rel['tag_name']}")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "geode-release.json").write_text(json.dumps({"tag": rel["tag_name"]}))

    for platform in [p.strip() for p in args.platforms.split(",") if p.strip()]:
        payload = args.out / "payload" / platform
        if platform == "win":
            asset = pick_asset(rel["assets"], "win")
            print(f"  win: {asset['name']}")
            zip_path = args.out / asset["name"]
            download(asset["browser_download_url"], zip_path, asset.get("digest"))
            shutil.rmtree(payload, ignore_errors=True)
            payload.mkdir(parents=True)
            with zipfile.ZipFile(zip_path) as zf:
                safe_extract(zf, payload)
            check_layout("win", payload)
        elif platform == "mac":
            asset = pick_asset(rel["assets"], "macpkg")
            print(f"  mac: {asset['name']}")
            pkg_path = args.out / asset["name"]
            download(asset["browser_download_url"], pkg_path, asset.get("digest"))
            expand_mac_pkg(pkg_path, payload)
        else:
            raise SystemExit(f"plataforma desconocida: {platform}")
    print("OK")


if __name__ == "__main__":
    sys.exit(main())
