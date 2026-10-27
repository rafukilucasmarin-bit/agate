#!/usr/bin/env python3
"""Descarga la última release OFICIAL de Geode (github.com/geode-sdk/geode) y extrae los
ficheros del loader para Windows y macOS en build/payload/<plataforma>.

Se ejecuta en CI al empaquetar los instaladores. Es deliberadamente estricto: si la release
cambia de forma (nombres de assets, contenido del zip), FALLA en lugar de empaquetar algo roto.

Uso: python tools/fetch_geode.py --out build [--tag v5.x.y]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "geode-sdk/geode"
API = f"https://api.github.com/repos/{REPO}/releases"
ASSET_RE = {
    "win": re.compile(r"^geode-v[\w.\-]+-win\.zip$", re.I),
    "mac": re.compile(r"^geode-v[\w.\-]+-mac\.zip$", re.I),
}
# Ficheros que DEBEN existir tras extraer (según la documentación del instalador oficial).
# Win: según GeodeUpdater (reemplaza XInput1_4.dll, Geode.dll y recursos).
# Mac: según el postinstall oficial (Geode.dylib + GeodeBootstrapper.dylib en Contents/Frameworks y un
#      libfmod.dylib sustituto). Esto último viene de documentación secundaria: si el zip oficial no
#      lo trae, el build FALLA a propósito para que alguien compare con installer/mac/Scripts/postinstall.
REQUIRED = {
    "win": ["Geode.dll", "XInput1_4.dll"],
    "mac": ["Geode.dylib", "GeodeBootstrapper.dylib", "libfmod.dylib"],
}


def http_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agate-ci"})
    if tok := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pick_asset(assets: list[dict], platform: str) -> dict:
    hits = [a for a in assets if ASSET_RE[platform].match(a["name"])]
    if len(hits) != 1:
        names = ", ".join(a["name"] for a in assets)
        raise SystemExit(f"No pude elegir un único asset '{platform}' (candidatos: {len(hits)}). "
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
        raise SystemExit(f"Layout inesperado en el zip de {platform}: faltan {missing}.\n"
                         f"Contenido: {listing}\nRevisa installer/ del repo oficial de Geode y ajusta REQUIRED.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("build"))
    ap.add_argument("--tag")
    args = ap.parse_args()

    rel = http_json(f"{API}/tags/{args.tag}" if args.tag else f"{API}/latest")
    print(f"Release oficial de Geode: {rel['tag_name']}")
    (args.out).mkdir(parents=True, exist_ok=True)
    (args.out / "geode-release.json").write_text(json.dumps({"tag": rel["tag_name"]}))

    for platform in ("win", "mac"):
        asset = pick_asset(rel["assets"], platform)
        zip_path = args.out / asset["name"]
        print(f"  {platform}: {asset['name']}")
        download(asset["browser_download_url"], zip_path, asset.get("digest"))
        payload = args.out / "payload" / platform
        shutil.rmtree(payload, ignore_errors=True)
        payload.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract(zf, payload)
        check_layout(platform, payload)
    print("OK")


if __name__ == "__main__":
    sys.exit(main())
