#!/usr/bin/env python3
"""Compact an itemflav_extract.json dump into asset/cosmetics/itemflav_clips.json.

The standalone Windows extractor is not in this repo. Drop its JSON here:
    python scripts/ingest_itemflav.py path/to/itemflav_extract.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apex_auto_shader" / "asset" / "cosmetics" / "itemflav_clips.json"

BANNER_KEYS = ("still", "moving", "stillLight", "movingLight")
EMOTE_KEYS = ("anim", "animLoop", "anim3p")
FINISHER_KEYS = ("attacker", "victimLight", "victimMedium", "victimHeavy", "victimNpc")
LIGHT_NUM = (
    ("brightness", "brightness", 4),
    ("distance", "distance", 2),
    ("cone", "cone", 2),
    ("innercone", "inner", 2),
    ("inner", "inner", 2),
    ("halfbrightfrac", "half", 4),
    ("half", "half", 4),
)
_VEC = re.compile(r"[-0-9.]+")


def _clip(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null"}:
        return ""
    return Path(text.replace("\\", "/")).stem


def _fov(value: object) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not (1.0 <= num <= 170.0):
        return None
    rounded = round(num, 2)
    return int(rounded) if rounded == int(rounded) else rounded


def _num(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cam_offset(value: object) -> list[float] | None:
    nums = [float(x) for x in _VEC.findall(str(value or ""))]
    if len(nums) < 3:
        return None
    xyz = [round(n, 4) for n in nums[:3]]
    if all(abs(n) < 1e-6 for n in xyz):
        return None
    return xyz


def _as_light_list(block: object, raw: dict) -> list[dict]:
    if isinstance(block, list):
        return [item for item in block if isinstance(item, dict)]
    if isinstance(block, dict) and block:
        rows = []
        for idx in range(4):
            item = block.get(str(idx), block.get(idx))
            if isinstance(item, dict):
                rows.append(item)
        if rows:
            return rows
    src: list[dict] = []
    for idx in range(4):
        prefix = f"light{idx}_"
        row = {
            "brightness": raw.get(f"{prefix}brightness"),
            "distance": raw.get(f"{prefix}distance"),
            "cone": raw.get(f"{prefix}cone"),
            "innercone": raw.get(f"{prefix}innercone"),
            "halfbrightfrac": raw.get(f"{prefix}halfbrightfrac"),
            "pbrfalloff": raw.get(f"{prefix}pbrfalloff"),
            "castshadows": raw.get(f"{prefix}castshadows"),
        }
        if all(v is None or v == "" for v in row.values()):
            continue
        src.append(row)
    return src


def _compact_light(item: dict) -> dict:
    row: dict = {}
    seen: set[str] = set()
    for src, dest, digits in LIGHT_NUM:
        if dest in seen or src not in item:
            continue
        num = _num(item.get(src))
        if num is None:
            continue
        row[dest] = round(num, digits)
        seen.add(dest)
    if item.get("pbrfalloff") is False or item.get("pbr") is False:
        row["pbr"] = False
    if item.get("castshadows") is False or item.get("shadow") is False:
        row["shadow"] = False
    return row


def _lights(raw: dict) -> list[dict] | None:
    rows = [_compact_light(item) for item in _as_light_list(raw.get("lights"), raw)]
    rows = [row for row in rows if row]
    return rows or None


def _seq_stems(value: object) -> list[str]:
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = item if isinstance(item, str) else ""
        if isinstance(item, dict):
            text = str(item.get("animSeq") or item.get("anim3p") or item.get("seq") or "")
        stem = _clip(text)
        if stem and stem not in out:
            out.append(stem)
    return out


def compact_row(kind: str, raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    if kind == "banner":
        for key in BANNER_KEYS:
            clip = _clip(raw.get(key))
            if clip:
                out[key] = clip
        fov = _fov(raw.get("fov"))
        if fov is not None:
            out["fov"] = fov
        if raw.get("hasMoving") is True or out.get("moving"):
            out["hasMoving"] = True
        offset = _cam_offset(raw.get("camOffset") or raw.get("inspectMenuCameraOffset"))
        if offset:
            out["camOffset"] = offset
        lights = _lights(raw)
        if lights:
            out["lights"] = lights
        if not out.get("still") and not out.get("moving"):
            return None
    elif kind == "emote":
        for key in EMOTE_KEYS:
            clip = _clip(raw.get(key))
            if clip:
                out["anim" if key == "anim3p" and "anim" not in out else key] = clip
        if "anim" not in out:
            return None
        out.pop("anim3p", None)
        height = _num(raw.get("camHeight") or raw.get("cameraHeightOffset"))
        if height:
            out["camHeight"] = round(height, 4)
    else:
        for key in FINISHER_KEYS:
            clip = _clip(raw.get(key))
            if clip:
                out[key] = clip
        extra = _seq_stems(raw.get("extraAttacker") or raw.get("additionalAttackerAnimSeq"))
        if extra:
            out["extraAttacker"] = extra
        per_char = _seq_stems(raw.get("victimPerChar") or raw.get("victimPerCharacterAnimSeq"))
        if per_char:
            out["victimPerChar"] = per_char
        if "attacker" not in out:
            return None
    return out or None


def compact_extract(payload: dict) -> dict:
    buckets: dict[str, dict] = {"banner": {}, "emote": {}, "finisher": {}}
    for kind in buckets:
        block = payload.get(kind) or {}
        if not isinstance(block, dict):
            continue
        for file_key, raw in block.items():
            key = str(file_key).replace("\\", "/").lstrip("/")
            if not key or key.startswith("_") or "/_" in key:
                continue
            row = compact_row(kind, raw)
            if row:
                buckets[kind][key] = row
    lit = sum(1 for row in buckets["banner"].values() if row.get("lights"))
    return {
        "note": "Compact itemflav clips. CAST names live here; display names stay in *_by_legend.json.",
        "stats": {kind: len(rows) for kind, rows in buckets.items()} | {"bannerLights": lit},
        **buckets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extract", type=Path, help="itemflav_extract.json from the standalone extractor")
    parser.add_argument("-o", "--output", type=Path, default=OUT)
    args = parser.parse_args()
    payload = json.loads(args.extract.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("extract must be a JSON object")
    compact = compact_extract(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(compact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    stats = compact["stats"]
    print(
        f"wrote {args.output}  banner={stats['banner']} "
        f"bannerLights={stats.get('bannerLights', 0)} "
        f"emote={stats['emote']} finisher={stats['finisher']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
