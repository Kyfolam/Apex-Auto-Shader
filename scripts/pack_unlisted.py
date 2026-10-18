#!/usr/bin/env python3
"""Pack hide-tokens into ncache (Unlisted category).

Usage (from repo root):

    python scripts/pack_unlisted.py token [token ...]
    python scripts/pack_unlisted.py --clear

Tokens are substring filters (name, folder, prefix).
`--clear` ships no hidden skins. The addon keeps no plaintext token list.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "apex_auto_shader"
WRAITH = ADDON / "asset" / "wraith"


def _boot():
    sys.path.insert(0, str(ROOT))
    try:
        import bpy  # noqa: F401
    except ModuleNotFoundError:
        import importlib.machinery

        loader = importlib.machinery.SourceFileLoader(
            "smoke_import", str(ROOT / "scripts" / "smoke_import.py")
        )
        loader.load_module()._mock_bpy()
    from apex_auto_shader.pack import write_unlisted, unreleased_needles, load_index

    return write_unlisted, unreleased_needles, load_index


def _rewrite_seeds(blob: bytes) -> None:
    raw = base64.b64encode(blob).decode("ascii")
    wrapped = "\n".join(raw[i : i + 76] for i in range(0, len(raw), 76)) + "\n"
    parts = 4
    chunk = max((len(wrapped) + parts - 1) // parts, 1)
    for i in range(parts):
        (WRAITH / f"ncache.b64.{i:02d}").write_text(wrapped[i * chunk : (i + 1) * chunk], encoding="ascii")


def main(argv: list[str]) -> int:
    tokens = [a.strip().lower() for a in argv if a.strip() and a != "--clear"]
    if not tokens and "--clear" not in argv:
        print("usage: python scripts/pack_unlisted.py token [token ...] | --clear", file=sys.stderr)
        return 2
    write_unlisted, unreleased_needles, load_index = _boot()
    write_unlisted(tokens)
    blob = (WRAITH / "ncache.bin").read_bytes()
    _rewrite_seeds(blob)
    # Drop the in-process cache so the rewritten seed is what gets read.
    import apex_auto_shader.pack as pack

    pack._ROWS = None
    pack._UNRELEASED = None
    load_index()
    got = unreleased_needles()
    print("packed", ", ".join(got) if got else "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
