from __future__ import annotations

import re
from pathlib import Path

from ..constants import (
    ANIM_GROUP_ORDER,
    CANON_LEGENDS,
    LEGEND_SLUGS,
    WEIGHT_CLASSES,
)

_ANIM_GROUP_RULES = (
    ("finisher", re.compile(r"finish|execut", re.I)),
    ("select", re.compile(r"lobby|menu|select|intro|characterselect", re.I)),
    ("emote", re.compile(r"emote|dance|taunt", re.I)),
    ("pose", re.compile(r"glad|banner|holo|(^|_)pose(_|$)", re.I)),
    ("idle", re.compile(r"idle|wait", re.I)),
    (
        "ingame",
        re.compile(
            r"sprint|fire|aim|run|walk|jump|reload|melee|slide|crouch|land|mantle|"
            r"climb|swim|zip|weapon|shoot|ads|hipfire|throw|heal|revive|ping|"
            r"death|knock|downed|attack|combat|mp_",
            re.I,
        ),
    ),
)


_WEIGHT_RE = re.compile(r"^(light|medium|heavy)$", re.I)


_LEGEND_SKIP = frozenset(
    {
        "aim",
        "mp",
        "npc",
        "pov",
        "ptpov",
        "pilot",
        "class",
        "core",
        "humans",
        "animseq",
        "victim",
        "light",
        "medium",
        "heavy",
        "menu",
        "lobby",
        "idle",
        "emote",
        "glad",
        "gladcard",
        "gladiator",
        "banner",
        "bannerpose",
        "holocard",
        "holospray",
        "pose",
        "poses",
        "execution",
        "finisher",
        "select",
        "intro",
    }
)


_EXEC_VICTIM = re.compile(
    r"(?:^|_)(?:light|medium|heavy)_victim_([a-z][a-z0-9]+)_execution_(.+)$",
    re.I,
)


_EXEC_WEIGHT = re.compile(
    r"(?:^|_)(?:light|medium|heavy)_([a-z][a-z0-9]+)_execution_(.+)$",
    re.I,
)


_EXEC_PLAIN = re.compile(r"(?:^|_)([a-z][a-z0-9]+)_execution_(.+)$", re.I)


def classify_animation(name: str) -> str:
    stem = Path(str(name)).stem
    for key, pattern in _ANIM_GROUP_RULES:
        if pattern.search(stem):
            return key
    return "other"


def animation_group_label(key: str) -> str:
    for item, label in ANIM_GROUP_ORDER:
        if item == key:
            return label
    if key == "finisher":
        return "Finisher Solo"
    return "Other"


def legend_display_name(slug: str) -> str:
    key = (slug or "").strip().lower()
    if key in LEGEND_SLUGS:
        return LEGEND_SLUGS[key]
    slug_compact = key.replace(" ", "")
    for src, label in LEGEND_SLUGS.items():
        if src.replace(" ", "") == slug_compact:
            return label
    return (slug or "Other").replace("_", " ").title() or "Other"


_ANIM_ALIAS_SKIP = frozenset(
    {"holo", "stim", "support", "nova", "bang", "bh", "rev", "valk", "gibby"}
)


def guess_legend_from_anim(name: str) -> str:
    stem = Path(str(name)).stem
    tokens = [t for t in re.split(r"[_\-\s]+", stem) if t]
    for tok in tokens:
        low = tok.lower()
        if low in _LEGEND_SKIP or low in _ANIM_ALIAS_SKIP:
            continue
        if low in LEGEND_SLUGS:
            return LEGEND_SLUGS[low].lower().replace(" ", "")
    return ""


def canon_legend_items() -> list[tuple[str, str, str]]:
    items = []
    for slug in CANON_LEGENDS:
        items.append((slug, LEGEND_SLUGS.get(slug, slug.title()), ""))
    return items


def guess_legend_from_path(path: str | Path) -> str:
    p = Path(path)
    parts = [x.lower() for x in p.parts]
    if "legends" in parts:
        idx = parts.index("legends")
        if idx + 1 < len(parts):
            tok = parts[idx + 1]
            if tok in LEGEND_SLUGS:
                return LEGEND_SLUGS[tok].lower().replace(" ", "")
    return guess_legend_from_anim(p.stem) or guess_legend_from_anim(p.parent.name)


def find_animseq_class_root(start: str | Path) -> Path | None:
    current = Path(start)
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        animseq = parent / "animseq"
        class_dir = animseq / "humans" / "class"
        if class_dir.is_dir():
            return class_dir
        if animseq.is_dir():
            return animseq
        if parent.name.lower() == "class" and parent.parent.name.lower() == "humans":
            return parent
        if parent.name.lower() == "animseq":
            nested = parent / "humans" / "class"
            return nested if nested.is_dir() else parent
    return None


def legend_folder_needles(legend: str) -> list[str]:
    slug = (legend or "").lower().replace(" ", "")
    if not slug:
        return []
    canon = LEGEND_SLUGS.get(slug, slug).lower().replace(" ", "")
    needles = {slug, canon}
    for src, label in LEGEND_SLUGS.items():
        if label.lower().replace(" ", "") == canon:
            needles.add(src.lower())
    needles.discard("")
    return list(needles)


def find_legend_anim_dir(start: str | Path, legend: str) -> Path | None:
    root = find_animseq_class_root(start)
    if root is None:
        return None
    needles = legend_folder_needles(legend)
    if not needles:
        return None
    best: Path | None = None
    best_score = -1
    for dirpath in root.rglob("*"):
        if not dirpath.is_dir():
            continue
        name = dirpath.name.lower()
        if "victim" in name:
            continue
        hit = next((n for n in needles if n in name), "")
        if not hit:
            continue
        score = 0
        if name == hit or name.endswith(f"_{hit}") or name.startswith(f"{hit}_"):
            score += 80
        elif f"_{hit}" in name or name.endswith(hit):
            score += 50
        else:
            continue
        if "pilot" in name:
            score += 20
        try:
            n = sum(1 for p in dirpath.glob("*.cast"))
        except OSError:
            n = 0
        if n == 0:
            continue
        score += min(n, 40)
        if score > best_score:
            best_score = score
            best = dirpath
    return best


def find_legend_model_cast(start: str | Path, legend: str) -> Path | None:
    needle = (legend or "").lower()
    if not needle:
        return None
    current = Path(start)
    legends_root = None
    for parent in [current.parent if current.is_file() else current, *current.parents]:
        if parent.name.lower() == "legends":
            legends_root = parent
            break
        nested = parent / "mdl" / "techart" / "mshop" / "characters" / "legends"
        if nested.is_dir():
            legends_root = nested
            break
        nested = parent / "characters" / "legends"
        if nested.is_dir():
            legends_root = nested
            break
    if legends_root is None:
        return None
    folder = None
    for child in legends_root.iterdir() if legends_root.is_dir() else []:
        if child.is_dir() and child.name.lower() in {needle, legend.lower()}:
            folder = child
            break
        if child.is_dir() and needle in child.name.lower():
            folder = child
            break
    if folder is None:
        return None
    casts = []
    try:
        casts = [p for p in folder.rglob("*.cast") if "lod0" in p.stem.lower()]
        if not casts:
            casts = list(folder.rglob("*.cast"))
    except OSError:
        return None
    if not casts:
        return None

    def rank(path: Path) -> tuple:
        name = path.stem.lower()
        return (
            0 if "lod0" in name else 1,
            0 if "base" in name else 1,
            0 if "level01" in name else 1,
            len(name),
            name,
        )

    casts.sort(key=rank)
    return casts[0]


def bannerpose_display_name(name: str, legend: str = "") -> str:
    from .cosmetics import resolve_banner_name

    stem = Path(str(name)).stem
    cleaned = re.sub(r"_capturemode$", "", stem, flags=re.I)
    hit = resolve_banner_name(cleaned, legend) or resolve_banner_name(name, legend)
    if hit:
        return hit
    text = re.sub(r"^(animated|static)_", "", cleaned, flags=re.I)
    slugs = [legend] if legend else []
    slugs.extend(LEGEND_SLUGS.keys())
    for slug in slugs:
        if not slug or slug == "shared":
            continue
        text = re.sub(rf"^{re.escape(slug)}_gladcards?_?", "", text, flags=re.I)
        text = re.sub(rf"^{re.escape(slug)}_glad_card_?", "", text, flags=re.I)
    text = re.sub(r"^gladcards?_?", "", text, flags=re.I)
    text = re.sub(r"^glad_card_?", "", text, flags=re.I)
    text = re.sub(r"^(animated|static)_", "", text, flags=re.I)
    text = text.strip("_")
    return text or stem


def pose_subtype(name: str, legend: str = "") -> str:
    stem = Path(str(name)).stem.lower()
    if "capturemode" in stem:
        return "capture"
    from .cosmetics import banner_kind_for

    kind = banner_kind_for(name, legend)
    if kind in {"static", "animated"}:
        return kind
    # `_idle` is the still clip of an *animated* pose — do not dump it in Static.
    if re.search(r"(^|_)animated(_|$)", stem):
        return "animated"
    if re.search(r"(^|_)static(_|$)", stem):
        return "static"
    if re.search(r"(^|_)idle(_|$)", stem):
        return "static"
    return ""


def skip_bannerpose(name: str) -> bool:
    stem = Path(str(name)).stem.lower()
    # Lighting helper clips, not the light weight-class prefix on legends.
    return bool(re.search(r"(gladcard|glad_card|banner|pose)_light(_|$)", stem) or stem.endswith("_light"))


def is_capturemode_clip(name: str) -> bool:
    return "capturemode" in Path(str(name)).stem.lower()


def _banner_pick_rank(name: str, rec: dict, want_moving: bool) -> tuple:
    stem = Path(str(name)).stem.lower()
    moving = (rec.get("moving") or "").lower()
    still = (rec.get("still") or "").lower()
    if want_moving:
        if moving and stem == moving:
            return (0, len(stem))
        if moving and moving in stem and "idle" not in stem.split("_"):
            return (1, len(stem))
        if still and stem == still:
            return (4, len(stem))
        if "idle" in stem.split("_"):
            return (5, len(stem))
        return (3, -len(stem))
    if still and stem == still:
        return (0, len(stem))
    if still and still in stem:
        return (1, len(stem))
    if "idle" in stem.split("_"):
        return (2, len(stem))
    return (3, -len(stem))


def pick_banner_list_clips(clips: list[tuple[str, str]], legend: str = "") -> dict[str, list[tuple[str, str]]]:
    """One list row per holocard pose. Idle/light/rarity aliases collapse."""
    from .cosmetics import match_banner

    buckets: dict[str, list[tuple[str, str]]] = {"static": [], "animated": [], "capture": []}
    groups: dict[str, list[tuple[str, str, dict]]] = {}
    leftover: list[tuple[str, str]] = []
    for name, path in clips:
        if skip_bannerpose(name):
            continue
        rec = match_banner(name, legend)
        key = (rec or {}).get("file") or ""
        if key:
            groups.setdefault(key, []).append((name, path, rec))
        else:
            leftover.append((name, path))

    def _choose(items: list[tuple], rec: dict, want_moving: bool) -> tuple[str, str] | None:
        if not items:
            return None
        items = sorted(items, key=lambda it: _banner_pick_rank(it[0], rec, want_moving))
        name, path = items[0][0], items[0][1]
        return name, path

    seen: set[str] = set()
    for _file, items in groups.items():
        rec = items[0][2] or {}
        kind = rec.get("kind") if rec.get("kind") in {"static", "animated"} else ""
        if not kind:
            kind = "animated" if rec.get("moving") or rec.get("hasMoving") else "static"
        cap = [it for it in items if is_capturemode_clip(it[0])]
        body = [it for it in items if not is_capturemode_clip(it[0])]
        chosen = _choose(body, rec, want_moving=(kind == "animated"))
        if chosen and chosen[1] not in seen:
            buckets[kind].append(chosen)
            seen.add(chosen[1])
        captured = _choose(cap, rec, want_moving=False)
        if captured and captured[1] not in seen:
            buckets["capture"].append(captured)
            seen.add(captured[1])

    idle_of = {}
    non_idle = []
    for name, path in leftover:
        stem = Path(name).stem.lower()
        if re.search(r"(^|_)idle(_|$)", stem):
            base = re.sub(r"_idle$", "", stem)
            idle_of.setdefault(base, []).append((name, path))
        else:
            non_idle.append((name, path))
    keep_idle = []
    non_idle_bases = {re.sub(r"_idle$", "", Path(n).stem.lower()) for n, _p in non_idle}
    for base, rows in idle_of.items():
        if base not in non_idle_bases:
            keep_idle.extend(rows)
    for name, path in non_idle + keep_idle:
        if path in seen:
            continue
        sub = pose_subtype(name, legend) or "static"
        if sub not in buckets:
            sub = "static"
        buckets[sub].append((name, path))
        seen.add(path)
    return buckets


def is_banner_clip(name: str) -> bool:
    stem = Path(str(name)).stem.lower()
    if "gladcard" in stem or "glad_card" in stem or "bannerpose" in stem:
        return True
    if "capturemode" in stem:
        return True
    return classify_animation(name) == "pose"


def emote_subtype(name: str) -> str:
    stem = Path(str(name)).stem.lower()
    if "freefall" in stem:
        return "drop"
    if re.search(r"(^|_)ground(_|$)", stem):
        return "ground"
    if re.search(r"(^|_)drop(_|$)", stem):
        return "drop"
    return ""


def emote_display_name(name: str, legend: str = "") -> str:
    from .cosmetics import resolve_emote_name

    hit = resolve_emote_name(name, legend)
    if hit:
        return hit
    text = Path(str(name)).stem
    slugs = [legend] if legend else []
    slugs.extend(LEGEND_SLUGS.keys())
    seen = set()
    for slug in slugs:
        if not slug or slug == "shared" or slug in seen:
            continue
        seen.add(slug)
        text = re.sub(rf"^{re.escape(slug)}_freefall_emote_?", "", text, flags=re.I)
        text = re.sub(rf"^{re.escape(slug)}_ground_emote_?", "", text, flags=re.I)
    text = re.sub(r"^freefall_emote_?", "", text, flags=re.I)
    text = re.sub(r"^ground_emote_?", "", text, flags=re.I)
    leftover = text.strip("_")
    if leftover and len(leftover) >= 3 and not leftover.isdigit():
        return leftover
    return Path(str(name)).stem


def finisher_display_name(name: str, legend: str = "") -> str:
    from .cosmetics import resolve_finisher_name

    hit = resolve_finisher_name(name, legend)
    if hit:
        return hit
    info = parse_execution(name)
    if info:
        return info.get("clip_raw") or info.get("clip") or Path(str(name)).stem
    text = Path(str(name)).stem
    slugs = [legend] if legend else []
    slugs.extend(LEGEND_SLUGS.keys())
    for slug in slugs:
        if not slug or slug == "shared":
            continue
        text = re.sub(
            rf"(?:^|_)(?:light|medium|heavy)_?(?:victim_)?{re.escape(slug)}_execution_?",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(rf"^{re.escape(slug)}_execution_?", "", text, flags=re.I)
    text = re.sub(r"^(?:light|medium|heavy)_", "", text, flags=re.I)
    text = re.sub(r"^execution_?", "", text, flags=re.I)
    return text.strip("_") or Path(str(name)).stem


def strip_unique_trailing_index(names: list[str]) -> list[str]:
    parsed: list[tuple[str, str, str | None]] = []
    for name in names:
        match = re.search(r"^(.*)_(\d+)$", name)
        if match:
            parsed.append((name, match.group(1), match.group(2)))
        else:
            parsed.append((name, name, None))
    counts: dict[str, int] = {}
    for _original, base, _idx in parsed:
        counts[base] = counts.get(base, 0) + 1
    out = []
    for original, base, idx in parsed:
        if idx is not None and counts[base] == 1:
            out.append(base)
        else:
            out.append(original)
    return out


def _clip_stem(raw: str) -> str:
    clip = re.sub(r"_\d+$", "", raw or "")
    return clip.strip("_").lower()


def parse_execution(name: str) -> dict | None:
    stem = Path(str(name)).stem
    match = _EXEC_VICTIM.search(stem)
    if match:
        return {
            "legend": match.group(1).lower(),
            "clip": _clip_stem(match.group(2)),
            "clip_raw": match.group(2).strip("_"),
            "victim": True,
        }
    match = _EXEC_WEIGHT.search(stem)
    if match and match.group(1).lower() != "victim":
        return {
            "legend": match.group(1).lower(),
            "clip": _clip_stem(match.group(2)),
            "clip_raw": match.group(2).strip("_"),
            "victim": False,
        }
    match = _EXEC_PLAIN.search(stem)
    if match:
        legend = match.group(1).lower()
        if legend == "victim":
            return None
        return {
            "legend": legend,
            "clip": _clip_stem(match.group(2)),
            "clip_raw": match.group(2).strip("_"),
            "victim": False,
        }
    return None


def is_victim_execution(name: str) -> bool:
    info = parse_execution(name)
    return bool(info and info["victim"])


def find_class_root(path: str | Path) -> Path | None:
    current = Path(path)
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        if parent.name.lower() == "class":
            return parent
        if parent.name.lower() in WEIGHT_CLASSES and parent.parent.name.lower() == "class":
            return parent.parent
    return None


def weight_from_path(path: str | Path) -> str:
    for part in Path(path).parts:
        if part.lower() in WEIGHT_CLASSES:
            return part.lower()
    return ""


