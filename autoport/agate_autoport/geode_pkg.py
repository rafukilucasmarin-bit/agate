"""Lectura / reescritura de paquetes .geode (ZIP con mod.json)."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_MANIFEST_BYTES = 1 << 20
NATIVE_SUFFIXES = (".dll", ".dylib", ".so", ".apk")
ANY = "*"


class PackageError(Exception):
    pass


def _check_names(zf: zipfile.ZipFile) -> None:
    for name in zf.namelist():
        p = PurePosixPath(name.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts:
            raise PackageError(f"ruta peligrosa dentro del paquete: {name!r}")


def read_manifest(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            _check_names(zf)
            try:
                info = zf.getinfo("mod.json")
            except KeyError as e:
                raise PackageError("el paquete no contiene mod.json") from e
            if info.file_size > MAX_MANIFEST_BYTES:
                raise PackageError("mod.json demasiado grande")
            return json.loads(zf.read(info))
    except (zipfile.BadZipFile, json.JSONDecodeError) as e:
        raise PackageError(f"paquete corrupto: {e}") from e


@dataclass
class ModPackage:
    path: Path
    manifest: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ModPackage":
        return cls(Path(path), read_manifest(Path(path)))

    @property
    def id(self) -> str:
        return str(self.manifest.get("id", ""))

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", "v0.0.0"))

    def gd_target(self, platform: str) -> str | None:
        """Versión de GD objetivo: '*' = cualquiera, None = no soporta esa plataforma."""
        gd = self.manifest.get("gd")
        if isinstance(gd, str):
            return ANY if gd == ANY else gd.strip().lstrip("v")
        if isinstance(gd, dict):
            val = gd.get(platform)
            if val is None:
                return None
            return ANY if val == ANY else str(val).strip().lstrip("v")
        return None

    def is_resource_only(self) -> bool:
        with zipfile.ZipFile(self.path) as zf:
            return not any(n.lower().endswith(NATIVE_SUFFIXES) for n in zf.namelist())

    def dependencies(self) -> list[tuple[str, str, bool]]:
        """(id, requisito, obligatoria?) soportando ambos formatos de mod.json."""
        out: list[tuple[str, str, bool]] = []
        deps = self.manifest.get("dependencies") or {}
        if isinstance(deps, dict):
            for dep_id, spec in deps.items():
                if isinstance(spec, str):
                    out.append((dep_id, spec, True))
                elif isinstance(spec, dict):
                    imp = str(spec.get("importance", "required")).lower()
                    out.append((dep_id, str(spec.get("version", "*")), imp == "required"))
        elif isinstance(deps, list):
            for d in deps:
                if isinstance(d, dict) and "id" in d:
                    imp = str(d.get("importance", "required")).lower()
                    out.append((d["id"], str(d.get("version", "*")), imp == "required"))
        return out


def with_target(manifest: dict, platform: str, gd: str, loader_tag: str | None = None) -> dict:
    """Copia del manifest apuntando a `gd` en `platform` (no toca otras plataformas)."""
    new = json.loads(json.dumps(manifest))
    cur = new.get("gd")
    if isinstance(cur, dict):
        cur[platform] = gd
    else:
        new["gd"] = {platform: gd}
    if loader_tag:
        new["geode"] = loader_tag
    return new


def write_with_manifest(src: Path, dst: Path, manifest: dict) -> None:
    """Reescribe `src` en `dst` sustituyendo únicamente mod.json."""
    with zipfile.ZipFile(src) as zin:
        _check_names(zin)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.filename == "mod.json":
                    zout.writestr("mod.json", json.dumps(manifest, indent=2))
                else:
                    zout.writestr(info, zin.read(info))
