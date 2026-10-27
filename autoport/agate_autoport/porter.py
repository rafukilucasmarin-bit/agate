"""Lógica central de AutoPort.

Para cada mod instalado cuyo mod.json apunte a una versión de GD anterior a la última,
se prueban estas estrategias en orden (la primera que funcione gana):

 1. ÍNDICE  – el Geode Index ya publica una versión del mod para la última versión de GD.
              Se descarga, se verifica el SHA-256 y se revisa su mod.json.
 2. RETARGET – solo mods SIN binarios nativos (recursos puros): basta con cambiar el campo
              `gd` de mod.json. Con binarios NO se hace nunca: un .dll/.dylib compilado para
              otra versión de GD tiene offsets distintos y cerraría el juego.
 3. COMPILAR – opt-in (--allow-build): clona el repositorio publicado en el Index, apunta
              mod.json a la versión nueva y compila con la CLI de Geode contra el SDK
              actual. Ejecuta código de terceros, por eso está desactivado por defecto.

Si nada funciona, el mod se deja intacto (Geode lo mostrará como incompatible).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .geode_pkg import ANY, ModPackage, PackageError, read_manifest, with_target, write_with_manifest
from .index import IndexClient, IndexError_
from .store import Store
from .versions import gd_key, satisfies, semver_key

ALLOWED_GIT_HOSTS = {"github.com", "gitlab.com", "codeberg.org"}


class BuildError(Exception):
    pass


class Incompatible(Exception):
    """Motivo 'blando': se prueba la siguiente estrategia."""


@dataclass
class Outcome:
    mod_id: str
    status: str  # updated | retargeted | built | installed-dependency | skipped | failed | would-*
    detail: str = ""
    old_version: str = ""
    new_version: str = ""
    applied: str = ""  # installed | pending

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    path: Path | None
    manifest: dict | None
    source: str  # index | retarget | build
    version: str = ""


def default_runner(cmd: list[str], cwd: Path, timeout: int):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise BuildError(f"herramienta no encontrada: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise BuildError(f"tiempo agotado ejecutando {' '.join(cmd[:2])}") from e


@dataclass
class Context:
    store: Store
    platform: str
    client: IndexClient
    target_gd: str
    loader_tag: str
    installed_gd: str | None = None
    allow_build: bool = False
    dry_run: bool = False
    force: bool = False
    runner: Callable = default_runner
    max_depth: int = 4
    work_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="agate-")))
    installed: dict[str, ModPackage] = field(default_factory=dict)


@dataclass
class Report:
    target_gd: str
    installed_gd: str | None
    skipped_reason: str = ""
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def changed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.status in ("updated", "retargeted", "built", "installed-dependency")]

    def to_dict(self) -> dict:
        return {
            "target_gd": self.target_gd,
            "installed_gd": self.installed_gd,
            "skipped_reason": self.skipped_reason,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


# --------------------------------------------------------------------------- scan
def scan(ctx: Context) -> tuple[list[ModPackage], list[Outcome]]:
    """Devuelve (mods desactualizados, avisos). Rellena ctx.installed."""
    outdated: list[ModPackage] = []
    notes: list[Outcome] = []
    ctx.installed.clear()
    for f in sorted(ctx.store.mods_dir.glob("*.geode")):
        try:
            pkg = ModPackage.load(f)
        except PackageError as e:
            notes.append(Outcome(f.stem, "failed", str(e)))
            continue
        if not pkg.id:
            notes.append(Outcome(f.stem, "failed", "mod.json sin id"))
            continue
        ctx.installed[pkg.id] = pkg
        target = pkg.gd_target(ctx.platform)
        if target is None or target == ANY:
            continue  # no soporta esta plataforma / sirve para cualquier versión
        try:
            if gd_key(target) < gd_key(ctx.target_gd):
                outdated.append(pkg)
        except ValueError:
            notes.append(Outcome(pkg.id, "failed", f"versión de GD ilegible en mod.json: {target!r}"))
    return outdated, notes


def guard(ctx: Context) -> str:
    """Motivo para no portar nada, o '' si se puede continuar."""
    if ctx.force or not ctx.installed_gd:
        return ""
    have, want = gd_key(ctx.installed_gd), gd_key(ctx.target_gd)
    if have < want:
        return (f"tu GD ({ctx.installed_gd}) es anterior a la última ({ctx.target_gd}); "
                f"portar los mods los rompería en tu versión. Actualiza el juego o usa --force.")
    if have > want:
        return (f"tu GD ({ctx.installed_gd}) es más reciente que la última versión que el Index "
                f"conoce ({ctx.target_gd}); aún no hay nada a lo que portar.")
    return ""


# -------------------------------------------------------------------- strategies
def _verify(cand_path: Path, mod_id: str, ctx: Context, current: ModPackage | None) -> dict:
    manifest = read_manifest(cand_path)
    pkg = ModPackage(cand_path, manifest)
    if pkg.id != mod_id:
        raise PackageError(f"el paquete descargado es de otro mod ({pkg.id!r} ≠ {mod_id!r})")
    t = pkg.gd_target(ctx.platform)
    if t is None:
        raise Incompatible("la versión del Index no soporta esta plataforma")
    if t != ANY and gd_key(t) != gd_key(ctx.target_gd):
        raise Incompatible(f"la versión del Index apunta a GD {t}, no a {ctx.target_gd}")
    if current is not None:
        try:
            if semver_key(pkg.version) < semver_key(current.version):
                raise Incompatible(f"el Index solo ofrece {pkg.version}, anterior a la instalada ({current.version})")
        except ValueError:
            pass
    return manifest


def _from_index(mod_id: str, ctx: Context, current: ModPackage | None, soft: list[str]) -> Candidate | None:
    info = ctx.client.latest_version(mod_id, ctx.platform, ctx.target_gd)
    if info is None:
        soft.append("el Index no tiene versión para la última GD")
        return None
    if ctx.dry_run:
        return Candidate(None, None, "index", info.version)
    tmp = ctx.work_dir / f"{uuid.uuid4().hex}.geode"
    ctx.client.download(info.download_link, tmp, info.sha256)  # errores de hash = fallo duro
    try:
        manifest = _verify(tmp, mod_id, ctx, current)
    except Incompatible as e:
        soft.append(str(e))
        tmp.unlink(missing_ok=True)
        return None
    return Candidate(tmp, manifest, "index", str(manifest.get("version", info.version)))


def _retarget(pkg: ModPackage, ctx: Context) -> Candidate | None:
    if ctx.dry_run:
        return Candidate(None, None, "retarget", pkg.version)
    manifest = with_target(pkg.manifest, ctx.platform, ctx.target_gd)
    out = ctx.work_dir / f"{uuid.uuid4().hex}.geode"
    write_with_manifest(pkg.path, out, manifest)
    return Candidate(out, manifest, "retarget", pkg.version)


def _newest_geode(root: Path) -> Path | None:
    files = [p for p in root.rglob("*.geode") if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _from_source(pkg: ModPackage, ctx: Context, soft: list[str]) -> Candidate | None:
    repo = ctx.client.mod_repository(pkg.id)
    if not repo:
        soft.append("el Index no publica repositorio de código")
        return None
    u = urlparse(repo)
    if u.scheme != "https" or (u.hostname or "") not in ALLOWED_GIT_HOSTS:
        soft.append(f"repositorio no permitido para compilar: {repo}")
        return None
    if ctx.dry_run:
        return Candidate(None, None, "build", pkg.version)

    work = ctx.work_dir / f"build-{uuid.uuid4().hex[:8]}"
    src = work / "src"
    work.mkdir(parents=True)
    ver = pkg.version.lstrip("v")
    for ref in (f"v{ver}", ver, None):
        cmd = ["git", "clone", "--depth", "1"] + (["--branch", ref] if ref else []) + [repo, str(src)]
        if ctx.runner(cmd, work, 300).returncode == 0:
            break
        shutil.rmtree(src, ignore_errors=True)
    else:
        raise BuildError("no se pudo clonar el repositorio")

    mj = src / "mod.json"
    try:
        manifest = with_target(json.loads(mj.read_text("utf-8")), ctx.platform, ctx.target_gd, ctx.loader_tag)
    except (OSError, ValueError) as e:
        raise BuildError(f"mod.json ilegible en el repositorio: {e}") from e
    mj.write_text(json.dumps(manifest, indent=2), "utf-8")

    res = ctx.runner(["geode", "build"], src, 1800)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()[-3:]
        raise BuildError("falló la compilación contra el SDK actual: " + " | ".join(tail))
    built = _newest_geode(src)
    if not built:
        raise BuildError("la compilación no produjo ningún .geode")
    try:
        manifest = _verify(built, pkg.id, ctx, pkg)
    except Incompatible as e:
        raise BuildError(str(e)) from e
    return Candidate(built, manifest, "build", str(manifest.get("version", pkg.version)))


# ----------------------------------------------------------------------- driving
_STATUS = {"index": "updated", "retarget": "retargeted", "build": "built"}


def port_one(pkg: ModPackage, ctx: Context, depth: int = 0) -> list[Outcome]:
    soft: list[str] = []
    try:
        cand = _from_index(pkg.id, ctx, pkg, soft)
        if cand is None and pkg.is_resource_only():
            cand = _retarget(pkg, ctx)
        if cand is None and ctx.allow_build:
            cand = _from_source(pkg, ctx, soft)
        elif cand is None:
            soft.append("compilar desde código está desactivado (--allow-build)")
    except (IndexError_, PackageError, BuildError, OSError) as e:
        return [Outcome(pkg.id, "failed", str(e), old_version=pkg.version)]

    if cand is None:
        return [Outcome(pkg.id, "skipped", "; ".join(soft) or "sin versión compatible", old_version=pkg.version)]
    if ctx.dry_run:
        return [Outcome(pkg.id, f"would-{_STATUS[cand.source]}", "simulacro, no se modificó nada",
                        old_version=pkg.version, new_version=cand.version)]

    applied = ctx.store.install(cand.path, pkg.id, pkg)
    old_target = pkg.gd_target(ctx.platform)
    ctx.store.record(pkg.id, source=cand.source, from_gd=old_target, to_gd=ctx.target_gd,
                     old_version=pkg.version, new_version=cand.version, applied=applied)
    ctx.installed[pkg.id] = ModPackage(pkg.path, cand.manifest or pkg.manifest)
    outs = [Outcome(pkg.id, _STATUS[cand.source], f"GD {old_target} → {ctx.target_gd}",
                    old_version=pkg.version, new_version=cand.version, applied=applied)]
    outs += _ensure_deps(cand.manifest or {}, ctx, depth + 1, {pkg.id})
    return outs


def _dep_ok(have: ModPackage | None, req: str) -> bool:
    if have is None:
        return False
    try:
        return satisfies(have.version, req)
    except ValueError:
        return True  # versión rara: no insistir


def _ensure_deps(manifest: dict, ctx: Context, depth: int, seen: set[str]) -> list[Outcome]:
    outs: list[Outcome] = []
    if depth > ctx.max_depth:
        return outs
    holder = ModPackage(Path("."), manifest)
    for dep_id, req, required in holder.dependencies():
        if dep_id == "geode.loader" or not required or dep_id in seen:
            continue
        have = ctx.installed.get(dep_id)
        if _dep_ok(have, req):
            continue  # presente (si está desactualizado respecto a GD, tiene su propio turno)
        seen.add(dep_id)
        soft: list[str] = []
        try:
            cand = _from_index(dep_id, ctx, have, soft)
        except (IndexError_, PackageError, OSError) as e:
            outs.append(Outcome(dep_id, "failed", f"dependencia requerida: {e}"))
            continue
        if cand is None:
            outs.append(Outcome(dep_id, "failed", "dependencia requerida no disponible para esta GD: " + "; ".join(soft)))
            continue
        if ctx.dry_run:
            outs.append(Outcome(dep_id, "would-updated", "dependencia", new_version=cand.version))
            continue
        applied = ctx.store.install(cand.path, dep_id, have)
        ctx.store.record(dep_id, source="index", dependency_of=True, to_gd=ctx.target_gd,
                         new_version=cand.version, applied=applied)
        ctx.installed[dep_id] = ModPackage(cand.path, cand.manifest or {})
        outs.append(Outcome(dep_id, "installed-dependency", "instalada porque otro mod la necesita",
                            old_version=have.version if have else "", new_version=cand.version, applied=applied))
        outs += _ensure_deps(cand.manifest or {}, ctx, depth + 1, seen)
    return outs


def run(ctx: Context) -> Report:
    ctx.store.ensure()
    report = Report(ctx.target_gd, ctx.installed_gd)
    if not ctx.dry_run:
        for mod_id in ctx.store.apply_pending():
            report.outcomes.append(Outcome(mod_id, "updated", "aplicada tras cerrar el juego", applied="installed"))
    outdated, notes = scan(ctx)
    report.outcomes += notes
    reason = guard(ctx)
    if reason:
        report.skipped_reason = reason
    else:
        for pkg in outdated:
            report.outcomes += port_one(pkg, ctx)
    if not ctx.dry_run:
        ctx.store.write_last_run({**report.to_dict(), "notified": False})
    shutil.rmtree(ctx.work_dir, ignore_errors=True)
    return report
