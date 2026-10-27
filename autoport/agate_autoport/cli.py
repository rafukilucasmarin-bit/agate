"""Interfaz de línea de comandos de agate-autoport."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__
from .index import DEFAULT_BASE, IndexClient, IndexError_
from .porter import Context, Report, run
from .store import Store

LABELS = {
    "updated": "actualizado (Index)", "retargeted": "re-apuntado (solo recursos)",
    "built": "recompilado", "installed-dependency": "dependencia instalada",
    "skipped": "sin cambios", "failed": "ERROR",
    "would-updated": "se actualizaría (Index)", "would-retargeted": "se re-apuntaría",
    "would-built": "se recompilaría",
}


def default_platform() -> str:
    return "win" if sys.platform.startswith("win") else "mac"


def exe_path() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()


def guess_geode_dir(platform: str) -> Path:
    """El instalador deja el ejecutable en <juego>/agate/ (Windows) o
    <App>/Contents/Resources/agate/ (macOS). Geode guarda sus datos en <juego>/geode
    (Windows) y <App>/Contents/geode (macOS)."""
    here = exe_path().parent
    if platform == "win":
        return here.parent / "geode"
    return here.parent.parent / "geode"  # .../Contents/geode


def notify(title: str, text: str, platform: str) -> None:
    try:
        if platform == "win":
            import ctypes  # noqa: PLC0415
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
        else:
            safe = text.replace("\\", "\\\\").replace('"', "'")
            subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
                           check=False, timeout=10)
    except Exception:  # noqa: BLE001 - una notificación nunca debe romper nada
        pass


def print_report(rep: Report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
        return
    print(f"Última GD conocida: {rep.target_gd}  |  GD instalada: {rep.installed_gd or 'desconocida'}")
    if rep.skipped_reason:
        print(f"No se portó nada: {rep.skipped_reason}")
    for o in rep.outcomes:
        ver = f" {o.old_version}→{o.new_version}" if o.new_version and o.old_version != o.new_version else ""
        extra = " (se aplicará al cerrar el juego)" if o.applied == "pending" else ""
        print(f" - {o.mod_id}: {LABELS.get(o.status, o.status)}{ver}{extra}"
              f"{' — ' + o.detail if o.detail and o.status in ('skipped', 'failed') else ''}")
    if not rep.outcomes and not rep.skipped_reason:
        print("Todos los mods ya son compatibles.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agate-autoport", description=__doc__)
    p.add_argument("command", nargs="?", default="run", choices=["run", "status", "rollback"])
    p.add_argument("mod_id", nargs="?", help="solo para 'rollback'")
    p.add_argument("--geode-dir", type=Path)
    p.add_argument("--platform", choices=["win", "mac"], default=default_platform())
    p.add_argument("--installed-gd", help="versión de GD en uso (la pasa el mod de Agate)")
    p.add_argument("--target-gd", help="forzar versión objetivo (por defecto: la última del Index)")
    p.add_argument("--index-url", default=DEFAULT_BASE)
    p.add_argument("--allow-build", action="store_true",
                   help="permitir recompilar desde código fuente (ejecuta código de terceros)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="portar aunque tu GD no sea la última")
    p.add_argument("--notify", action="store_true", help="avisar con una notificación si hubo cambios")
    p.add_argument("--json", action="store_true")
    p.add_argument("--version", action="version", version=f"agate-autoport {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    geode_dir = args.geode_dir or guess_geode_dir(args.platform)
    store = Store(geode_dir)

    if args.command == "status":
        print(json.dumps({"registry": store.registry(),
                          "last_run": json.loads(store.last_run_file.read_text("utf-8"))
                          if store.last_run_file.exists() else None}, indent=2, ensure_ascii=False))
        return 0
    if args.command == "rollback":
        if not args.mod_id:
            print("Indica el id del mod: agate-autoport rollback <mod.id>", file=sys.stderr)
            return 2
        restored = store.rollback(args.mod_id)
        print(f"Restaurado: {restored}" if restored else "No hay copias de seguridad de ese mod.")
        return 0 if restored else 1

    client = IndexClient(args.index_url, user_agent=f"agate-autoport/{__version__} ({args.platform})")
    try:
        loader = client.latest_loader(args.platform)
        target = args.target_gd or loader.gd.get(args.platform) or loader.gd.get("*")
        if not target:
            raise IndexError_("el Index no indica la versión de GD de esta plataforma")
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo consultar el Geode Index: {e}", file=sys.stderr)
        return 2

    ctx = Context(store=store, platform=args.platform, client=client, target_gd=target.lstrip("v"),
                  loader_tag=loader.tag, installed_gd=(args.installed_gd or "").lstrip("v") or None,
                  allow_build=args.allow_build, dry_run=args.dry_run, force=args.force)
    report = run(ctx)
    print_report(report, args.json)
    if args.notify and report.changed:
        notify("Agate", f"Se actualizaron {len(report.changed)} mod(s) para GD {report.target_gd}. "
                        f"Reinicia el juego para aplicarlos.", args.platform)
    return 1 if any(o.status == "failed" for o in report.outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
