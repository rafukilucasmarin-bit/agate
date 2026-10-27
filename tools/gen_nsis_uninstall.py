#!/usr/bin/env python3
"""Genera la lista de borrado del desinstalador NSIS a partir del payload del loader."""
import sys
from pathlib import Path

payload, out = Path(sys.argv[1]), Path(sys.argv[2])
files = sorted(p.relative_to(payload) for p in payload.rglob("*") if p.is_file())
dirs = sorted({d for f in files for d in f.parents if str(d) != "."}, key=lambda d: -len(d.parts))
lines = [f'Delete "$INSTDIR\\{str(f).replace("/", chr(92))}"' for f in files]
lines += [f'RMDir "$INSTDIR\\{str(d).replace("/", chr(92))}"' for d in dirs]  # solo borra si quedan vacías
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(files)} ficheros, {len(dirs)} carpetas -> {out}")
