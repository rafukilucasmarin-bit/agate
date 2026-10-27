"""Estado local de Agate dentro de la carpeta geode/: copias de seguridad, instalación
atómica, cola de pendientes (por si Windows tiene el archivo bloqueado) y reversión."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .geode_pkg import ModPackage


class Store:
    def __init__(self, geode_dir: Path):
        self.geode_dir = Path(geode_dir)
        self.mods_dir = self.geode_dir / "mods"
        self.root = self.geode_dir / "agate"
        self.backups = self.root / "backups"
        self.pending = self.root / "pending"
        self.registry_file = self.root / "ported.json"
        self.last_run_file = self.root / "last-run.json"

    def ensure(self) -> None:
        for d in (self.mods_dir, self.backups, self.pending):
            d.mkdir(parents=True, exist_ok=True)

    # -- registro de portados ------------------------------------------------
    def registry(self) -> dict:
        try:
            return json.loads(self.registry_file.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def record(self, mod_id: str, **info) -> None:
        reg = self.registry()
        reg[mod_id] = {**info, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self._write_json(self.registry_file, reg)

    def write_last_run(self, doc: dict) -> None:
        self._write_json(self.last_run_file, doc)

    @staticmethod
    def _write_json(path: Path, doc: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, path)

    # -- instalación ---------------------------------------------------------
    def backup(self, pkg: ModPackage) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = self.backups / pkg.id / f"{stamp}-{pkg.version}.geode"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pkg.path, dest)
        return dest

    def install(self, new_file: Path, mod_id: str, replacing: ModPackage | None) -> str:
        """Instala `new_file` como mods/<id>.geode. Devuelve 'installed' o 'pending'."""
        self.ensure()
        target = replacing.path if replacing else self.mods_dir / f"{mod_id}.geode"
        if replacing:
            self.backup(replacing)
        staged = target.with_name(target.name + ".agate-new")
        shutil.copyfile(new_file, staged)
        try:
            os.replace(staged, target)
            return "installed"
        except OSError:
            # Archivo bloqueado (juego abierto en Windows): se aplica en el próximo arranque.
            staged.unlink(missing_ok=True)
            hold = self.pending / f"{mod_id}.geode"
            shutil.copyfile(new_file, hold)
            self._write_json(self.pending / f"{mod_id}.target.json", {"target": str(target)})
            return "pending"

    def apply_pending(self) -> list[str]:
        applied = []
        if not self.pending.exists():
            return applied
        for meta in self.pending.glob("*.target.json"):
            mod_id = meta.name[: -len(".target.json")]
            src = self.pending / f"{mod_id}.geode"
            try:
                target = Path(json.loads(meta.read_text("utf-8"))["target"])
                if src.exists():
                    os.replace(src, target)
                meta.unlink()
                applied.append(mod_id)
            except (OSError, ValueError, KeyError):
                continue  # sigue bloqueado: se reintenta la próxima vez
        return applied

    # -- reversión -----------------------------------------------------------
    def rollback(self, mod_id: str) -> Path | None:
        folder = self.backups / mod_id
        files = sorted(folder.glob("*.geode")) if folder.exists() else []
        if not files:
            return None
        latest = files[-1]
        target = self.mods_dir / f"{mod_id}.geode"
        for cand in self.mods_dir.glob("*.geode"):
            try:
                if ModPackage.load(cand).id == mod_id:
                    target = cand
                    break
            except Exception:
                continue
        shutil.copyfile(latest, target.with_name(target.name + ".agate-new"))
        os.replace(target.with_name(target.name + ".agate-new"), target)
        latest.unlink()
        return target
