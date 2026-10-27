"""Comparación de versiones de Geometry Dash y semver (mods / loader)."""
from __future__ import annotations

import re

_GD_RE = re.compile(r"^v?(\d+)\.(\d+)$")
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)(?:\.(\d+))?)?$")
_TAG_RANK = {"alpha": 0, "beta": 1, "prerelease": 2, "rc": 3}


def norm_gd(v: str) -> str:
    return v.strip().lstrip("v")


def gd_key(v: str) -> tuple[int, int]:
    """Orden correcto de versiones de GD: 2.206 < 2.207 < 2.2074 < 2.2081 < 2.209 < 2.2091.

    La parte decimal NO es un entero normal (2.209 es posterior a 2.2081), así que se
    rellena con ceros a la derecha antes de comparar.
    """
    m = _GD_RE.match(v.strip())
    if not m:
        raise ValueError(f"versión de GD inválida: {v!r}")
    major, frac = m.groups()
    return int(major), int(frac.ljust(6, "0"))


def semver_key(v: str) -> tuple:
    m = _SEMVER_RE.match(v.strip())
    if not m:
        raise ValueError(f"versión semver inválida: {v!r}")
    major, minor, patch, tag, tagnum = m.groups()
    rank = 9 if tag is None else _TAG_RANK.get(tag.lower(), 0)
    return int(major), int(minor), int(patch), rank, int(tagnum or 0)


def satisfies(version: str, requirement: str) -> bool:
    """Semántica de dependencias de Geode: `>=` = misma major y >=; `<=`; `=`."""
    req = requirement.strip()
    if req in ("", "*"):
        return True
    for op in (">=", "<=", "="):
        if req.startswith(op):
            target = req[len(op):].strip()
            break
    else:
        op, target = "=", req
    have, want = semver_key(version), semver_key(target)
    if op == ">=":
        return have[0] == want[0] and have >= want
    if op == "<=":
        return have <= want
    return have == want
