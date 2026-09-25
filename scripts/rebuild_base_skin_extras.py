#!/usr/bin/env python3
"""Set ncache extras for Common/Rare/Epic palettes to legend_rare_01 etc.

Those skins share the base CAST. The extra must name the texture prefix so
Find Skins can overlay the right maps instead of every palette looking like Original.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMP = Path("/workspace/attachments/character_skins.json")
WRAITH = ROOT / "apex_auto_shader" / "asset" / "wraith"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import smoke_import  # noqa: E402

smoke_import._mock_bpy()

from apex_auto_shader import pack  # noqa: E402
from apex_auto_shader.constants import LEGEND_SLUGS  # noqa: E402

_BASE_STEM = {"classic", "default", "base"}


def _label_for_folder(folder: str) -> str:
    return LEGEND_SLUGS.get(folder.lower(), folder[:1].upper() + folder[1:] if folder else folder)


def _wrap_b64(blob: bytes) -> None:
    compact = base64.b64encode(blob).decode("ascii")
    wrapped = "\n".join(compact[i : i + 76] for i in range(0, len(compact), 76))
    if not wrapped.endswith("\n"):
        wrapped += "\n"
    (WRAITH.parent.parent.parent / "ncache.b64") if False else None
    chunk = (len(compact) + 3) // 4
    parts = [compact[i : i + chunk] for i in range(0, len(compact), chunk)]
    while len(parts) < 4:
        parts.append("")
    for i, part in enumerate(parts[:4]):
        text = "\n".join(part[j : j + 76] for j in range(0, len(part), 76))
        if part and not text.endswith("\n"):
            text += "\n"
        (WRAITH / f"ncache.b64.{i:02d}").write_text(text)


def main() -> int:
    dumps = json.loads(DUMP.read_text(encoding="utf-8"))
    rows = pack.load_index()
    by_name: dict[tuple[str, str], list[int]] = {}
    for i, (lg, name, extra) in enumerate(rows):
        by_name.setdefault((lg.lower(), name.lower()), []).append(i)

    patched = 0
    skipped = 0
    missing = 0
    for d in dumps:
        path = Path(d.get("file") or "")
        if not path.parts:
            continue
        folder = path.parts[0].lower()
        stem = path.stem.lower()
        name = (d.get("skinName") or "").strip()
        if not name:
            continue
        label = _label_for_folder(folder)
        idxs = by_name.get((label.lower(), name.lower())) or by_name.get(
            (folder.lower(), name.lower())
        )
        if not idxs:
            missing += 1
            continue
        i = idxs[0]
        lg, nm, extra = rows[i]
        if not extra.endswith("_base"):
            skipped += 1
            continue
        prefix = extra[: -len("_base")]
        if stem in _BASE_STEM:
            continue
        extra2 = f"{prefix}_{stem}"
        if extra2 == extra:
            continue
        rows[i] = (lg, nm, extra2)
        patched += 1

    legends: list[str] = []
    seen: set[str] = set()
    records: list[tuple[int, str, str]] = []
    for lg, name, extra in rows:
        if lg not in seen:
            seen.add(lg)
            legends.append(lg)
        records.append((legends.index(lg), name, extra))

    out_bin = WRAITH / "ncache.bin"
    pack.write_index(out_bin, legends, records)
    blob = out_bin.read_bytes()
    _wrap_b64(blob)
    pack._ROWS = None
    check = pack.load_index()
    print("rows", len(check), "patched", patched, "skipped_unique", skipped, "unmatched_dump", missing)
    sample = [r for r in check if r[0] == "Alter" and r[1] in {"Original", "Wallflower", "Fiber Optics", "Fashion Fatale", "Alterior Motive"}]
    for row in sample:
        print(" ", row)
    bases = sum(1 for lg, n, e in check if e.endswith("_base") and lg == "Alter")
    print("alter *_base extras", bases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
