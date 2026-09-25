#!/usr/bin/env python3
"""Pack hide-tokens into ncache (Unlisted category).

Usage (from repo root):

    python scripts/pack_unlisted.py token [token ...]

Tokens are substring filters (name, folder, prefix).
The addon ships no plaintext token list — only this packed category.
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
    tokens = [a.strip().lower() for a in argv if a.strip()]
    if not tokens:
        print("usage: python scripts/pack_unlisted.py token [token ...]", file=sys.stderr)
        return 2
    write_unlisted, unreleased_needles, load_index = _boot()
    write_unlisted(tokens)
    blob = (WRAITH / "ncache.bin").read_bytes()
    _rewrite_seeds(blob)
    load_index()
    print("packed", ", ".join(unreleased_needles()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
