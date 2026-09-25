#!/usr/bin/env python3
"""Rebuild per-legend cosmetics catalogs from collector JSON dumps."""
from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTACH = ROOT / "attachments"
OUT = ROOT / "apex_auto_shader" / "asset" / "cosmetics"
MD_PATH = ROOT / "cosmetics_catalog.md"

SLUG_TO_NAME = {
    "alter": "Alter",
    "ash": "Ash",
    "ballistic": "Ballistic",
    "bangalore": "Bangalore",
    "bloodhound": "Bloodhound",
    "catalyst": "Catalyst",
    "caustic": "Caustic",
    "conduit": "Conduit",
    "crypto": "Crypto",
    "fade": "Fade",
    "fuse": "Fuse",
    "gibraltar": "Gibraltar",
    "horizon": "Horizon",
    "lifeline": "Lifeline",
    "loba": "Loba",
    "madmaggie": "Mad Maggie",
    "mirage": "Mirage",
    "newcastle": "Newcastle",
    "octane": "Octane",
    "overdrive": "Axle",
    "axle": "Axle",
    "pathfinder": "Pathfinder",
    "rampart": "Rampart",
    "revenant": "Revenant",
    "seer": "Seer",
    "sparrow": "Sparrow",
    "valkyrie": "Valkyrie",
    "vantage": "Vantage",
    "wattson": "Wattson",
    "wraith": "Wraith",
    "shared": "Shared",
    "dummie": "Dummy",
    "dummy": "Dummy",
}

# Display-name sort: keep legends A–Z, Shared/Dummy last.
LAST = {"Shared", "Dummy"}


def display_name(slug: str) -> str:
    return SLUG_TO_NAME.get(slug.lower(), slug.title())


def slug_of(file_path: str) -> str | None:
    if not file_path or "/" not in file_path:
        return None
    return file_path.split("/", 1)[0].lower()


def rarity_from_file(file_path: str) -> str:
    stem = Path(file_path).stem.lower()
    # order matters: more specific first
    tokens = [
        "heirloom",
        "mythic",
        "legendary",
        "lgnd",
        "epic",
        "rare",
        "common",
        "default",
        "classic",
        "basic",
        "base",
    ]
    for t in tokens:
        if re.search(rf"(?:^|_|-){t}(?:$|_|-|\d)", stem) or stem.startswith(t) or f"_{t}" in stem:
            if t in ("legendary", "lgnd"):
                return "legendary"
            if t == "heirloom":
                return "mythic"
            if t in ("default", "classic", "basic", "base"):
                return "common"
            return t
    return "other"


def banner_kind(rarity: str) -> str:
    if rarity in ("common", "rare"):
        return "static"
    if rarity in ("epic", "legendary", "mythic"):
        return "animated"
    return "animated"


def resolved_name(item: dict) -> str | None:
    name = (item.get("skinName") or "").strip()
    if not name or name.startswith("#"):
        return None
    if name.lower() in ("[temp]", "temp"):
        return None
    return name


def load_items(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit(f"expected list in {path}")
    return data


def item_record(raw: dict, kind: str) -> dict:
    rarity = rarity_from_file(raw["file"])
    return {
        "file": raw["file"],
        "name": resolved_name(raw),
        "locKey": raw.get("localizationKey_NAME") or "",
        "hash": raw.get("hash") or "",
        "rarity": rarity,
        "kind": kind,
    }


def group_simple(raws: list[dict], kind: str, skip_files: set[str] | None = None) -> tuple[dict, list]:
    legends: dict[str, dict] = {}
    unnamed: list[dict] = []
    skip_files = skip_files or set()
    for raw in raws:
        fp = raw.get("file") or ""
        if fp in skip_files or fp.startswith("_"):
            continue
        slug = slug_of(fp)
        if not slug:
            unnamed.append(raw)
            continue
        name = display_name(slug)
        rec = item_record(raw, kind)
        bucket = legends.setdefault(
            name,
            {
                "slug": "overdrive" if name == "Axle" else slug,
                "displayName": name,
                "counts": {"total": 0},
                "items": [],
            },
        )
        bucket["items"].append(rec)
        bucket["counts"]["total"] += 1
        if rec["name"] is None:
            unnamed.append(rec)
    for bucket in legends.values():
        bucket["items"].sort(key=lambda x: ((x["name"] or "~").lower(), x["file"]))
    ordered = OrderedDict(
        (k, legends[k])
        for k in sorted(legends, key=lambda n: (n in LAST, n.lower()))
    )
    return ordered, unnamed


def group_banner(raws: list[dict]) -> tuple[dict, list]:
    legends: dict[str, dict] = {}
    unnamed: list[dict] = []
    for raw in raws:
        fp = raw.get("file") or ""
        if fp.startswith("_") or fp == "_temp.json":
            continue
        slug = slug_of(fp)
        if not slug:
            continue
        name = display_name(slug)
        rarity = rarity_from_file(fp)
        kind = banner_kind(rarity)
        rec = {
            "file": fp,
            "name": resolved_name(raw),
            "locKey": raw.get("localizationKey_NAME") or "",
            "hash": raw.get("hash") or "",
            "rarity": rarity,
            "kind": kind,
        }
        bucket = legends.setdefault(
            name,
            {
                "slug": "overdrive" if name == "Axle" else slug,
                "displayName": name,
                "counts": {"static": 0, "animated": 0, "total": 0},
                "static": [],
                "animated": [],
            },
        )
        bucket[kind].append(rec)
        bucket["counts"][kind] += 1
        bucket["counts"]["total"] += 1
        if rec["name"] is None:
            unnamed.append(rec)
    for bucket in legends.values():
        bucket["static"].sort(key=lambda x: ((x["name"] or "~").lower(), x["file"]))
        bucket["animated"].sort(key=lambda x: ((x["name"] or "~").lower(), x["file"]))
    ordered = OrderedDict(
        (k, legends[k])
        for k in sorted(legends, key=lambda n: (n in LAST, n.lower()))
    )
    return ordered, unnamed


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    # numeric align hint in header already
    out[1] = "|" + "|".join(
        [":---:" if h.lower() in ("static", "animated", "total", "emotes", "finishers") else "---" for h in headers]
    ) + "|"
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main() -> None:
    banners = load_items(ATTACH / "gcard_emotes.json")
    emotes = load_items(ATTACH / "character_emotes.json")
    execs = load_items(ATTACH / "character_execution.json")
    OUT.mkdir(parents=True, exist_ok=True)

    ban_legends, ban_unnamed = group_banner(banners)
    emo_legends, emo_unnamed = group_simple(emotes, "animation")
    exe_legends, exe_unnamed = group_simple(execs, "animation")

    ban_static = sum(v["counts"]["static"] for v in ban_legends.values())
    ban_anim = sum(v["counts"]["animated"] for v in ban_legends.values())

    banner_payload = {
        "type": "banner_poses",
        "note": "Banner Poses (gcard stances). Common/Rare = static, Epic/Legendary/Heirloom/Mythic = animated. Nicht Banner Frames. Slug overdrive → Axle.",
        "stats": {
            "static": ban_static,
            "animated": ban_anim,
            "unnamed": len(ban_unnamed),
            "legends": len(ban_legends),
        },
        "legends": ban_legends,
    }
    emote_payload = {
        "type": "character_emotes",
        "note": "Ground Emotes inkl. Gibraltar (character_emotes.json). Slug overdrive → Axle.",
        "stats": {
            "total": sum(v["counts"]["total"] for v in emo_legends.values()),
            "unnamed": len(emo_unnamed),
            "legends": len(emo_legends),
        },
        "legends": emo_legends,
    }
    exec_payload = {
        "type": "character_executions",
        "note": "Finishers. Dummy und unbenannte Einträge separat gelistet. Slug overdrive → Axle.",
        "stats": {
            "total": sum(v["counts"]["total"] for v in exe_legends.values()),
            "unnamed": len(exe_unnamed),
            "legends": len(exe_legends),
        },
        "legends": exe_legends,
    }

    write_json(OUT / "banner_poses_by_legend.json", banner_payload)
    write_json(OUT / "character_emotes_by_legend.json", emote_payload)
    write_json(OUT / "character_executions_by_legend.json", exec_payload)

    # markdown catalog
    lines = []
    lines.append("# Apex Cosmetics Katalog")
    lines.append("")
    lines.append("Quellen: `gcard_emotes.json` (Banner Poses), `character_emotes.json` (Ground Emotes), `character_execution.json` (Finishers).")
    lines.append("")
    lines.append("- **Overdrive → Axle** (interner Slug bleibt `overdrive`).")
    lines.append("- Banner **Frames** sind nicht enthalten (bringen für das Addon nichts).")
    lines.append("- Skin-Index bleibt in `ncache.bin` (kein sichtbares skins.json).")
    lines.append("")
    lines.append("## Banner Poses")
    lines.append("")
    lines.append("Sortierung: **static** = Common/Rare, **animated** = Epic/Legendary/Heirloom/Mythic.")
    lines.append("")
    lines.append(f"Gesamt: {ban_static} static + {ban_anim} animated = {ban_static + ban_anim} Poses, {len(ban_legends)} Legenden.")
    lines.append("")
    rows = []
    for name, b in ban_legends.items():
        c = b["counts"]
        rows.append([name, c["static"], c["animated"], c["total"]])
    lines.append(md_table(["Legende", "Static", "Animated", "Total"], rows))
    if ban_unnamed:
        lines.append("")
        lines.append("### Unbenannte Banner Poses")
        lines.append("")
        for u in ban_unnamed:
            lines.append(f"- {display_name(slug_of(u['file']) or '')} / `{u['file']}` (`{u.get('locKey','')}`)")
    lines.append("")
    lines.append("## Ground Emotes")
    lines.append("")
    emo_total = emote_payload["stats"]["total"]
    lines.append(f"Gesamt: {emo_total} Emotes, {len(emo_legends)} Gruppen (inkl. Shared). Gibraltar vollständig enthalten.")
    lines.append("")
    rows = [[name, b["counts"]["total"]] for name, b in emo_legends.items()]
    lines.append(md_table(["Legende", "Emotes"], rows))
    if emo_unnamed:
        lines.append("")
        lines.append("### Unbenannte Emotes")
        lines.append("")
        for u in emo_unnamed:
            lines.append(f"- `{u.get('file')}` (`{u.get('locKey','')}`)")
    lines.append("")
    lines.append("## Finishers")
    lines.append("")
    exe_total = exec_payload["stats"]["total"]
    lines.append(f"Gesamt: {exe_total} Finishers, {exec_payload['stats']['unnamed']} ohne aufgelösten Namen.")
    lines.append("")
    rows = [[name, b["counts"]["total"]] for name, b in exe_legends.items()]
    lines.append(md_table(["Legende", "Finishers"], rows))
    if exe_unnamed:
        lines.append("")
        lines.append("### Unbenannte Finishers")
        lines.append("")
        for u in exe_unnamed:
            lines.append(f"- {display_name(slug_of(u.get('file') or '') or '—')} / `{u.get('file')}` (`{u.get('locKey','')}`)")

    # Axle showcase
    if "Axle" in ban_legends:
        ax = ban_legends["Axle"]
        lines.append("")
        lines.append("## Beispiel Axle (ehem. Overdrive) – Banner Poses")
        lines.append("")
        static_names = ", ".join(x["name"] or f"`{x['file']}`" for x in ax["static"])
        anim_names = ", ".join(x["name"] or f"`{x['file']}`" for x in ax["animated"])
        lines.append(f"**Static:** {static_names}")
        lines.append("")
        lines.append(f"**Animated:** {anim_names}")
    if "Axle" in emo_legends:
        names = ", ".join(x["name"] or f"`{x['file']}`" for x in emo_legends["Axle"]["items"])
        lines.append("")
        lines.append(f"**Ground Emotes:** {names}")
    if "Axle" in exe_legends:
        names = ", ".join(x["name"] or f"`{x['file']}`" for x in exe_legends["Axle"]["items"])
        lines.append("")
        lines.append(f"**Finishers:** {names}")

    if "Gibraltar" in emo_legends:
        names = ", ".join(x["name"] or f"`{x['file']}`" for x in emo_legends["Gibraltar"]["items"])
        lines.append("")
        lines.append("## Gibraltar Ground Emotes (jetzt vollständig)")
        lines.append("")
        lines.append(names)

    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("banner", banner_payload["stats"])
    print("emotes", emote_payload["stats"])
    print("execs", exec_payload["stats"])
    print("legends banner:", ", ".join(ban_legends))
    print("legends emotes:", ", ".join(emo_legends))
    print("legends execs:", ", ".join(exe_legends))
    print("unnamed banners:", [(u.get("file"), u.get("locKey")) for u in ban_unnamed])
    print("unnamed emotes:", [(u.get("file"), u.get("locKey")) for u in emo_unnamed])
    print("unnamed execs:", [(u.get("file"), u.get("locKey")) for u in exe_unnamed])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=ATTACH, help="collector dump folder")
    parser.add_argument("--out", type=Path, default=OUT, help="catalog JSON output folder")
    parser.add_argument("--md", type=Path, default=MD_PATH, help="markdown overview path")
    args = parser.parse_args()
    ATTACH = args.src
    OUT = args.out
    MD_PATH = args.md
    main()
