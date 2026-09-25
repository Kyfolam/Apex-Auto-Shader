"""Localized names for banner poses, ground emotes, and finishers."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..constants import LEGEND_SLUGS

_DIR = Path(__file__).resolve().parent.parent / "asset" / "cosmetics"

_GENERIC = frozenset(
    {
        "gcard", "stance", "animated", "static", "name", "ground", "emote",
        "character", "execution", "finisher", "char", "ptpov", "pov",
        "gladcard", "gladcards", "glad", "card", "idle", "pose", "poses", "light",
        "medium", "heavy", "victim", "pilot", "class", "shared", "menu",
        "holo", "common", "rare", "epic", "legendary", "lgnd", "mythic",
        "heirloom", "default", "base", "classic", "basic", "prestige", "one", "arm",
        "attacker", "stare",
    }
)

_LOC_PREFIXES = (
    r"gcard_animated_", r"gcard_stance_", r"ground_emote_",
    r"character_emote_", r"character_execution_", r"char_emote_", r"emote_",
)

# gladcards_ (plural) is used on some Ballistic/Caustic/Vantage clips.
_CLIP_PREFIX = re.compile(
    r"^(?:ptpov_|p2_|firstperson_|animated_|static_|gladcards?_|glad_card_|"
    r"freefall_emote_|ground_emote_|emote_|execution_?|capturemode_|"
    r"mp_|menu_|ai_|pilot_|holo_|holocard_|bannerpose_)",
    re.I,
)

_POSE_ID = re.compile(
    r"(?:(?P<season>s\d+e\d+|season\d+(?:_event\d+)?)_)?"
    r"(?P<rarity>common|rare|epicp?|lgnd|legendary|heirloom|mythic|icon)"
    r"(?:_(?P<idx>\d{2}))?",
    re.I,
)

_ANIM_PREFIX = re.compile(
    r"^(?:[a-z0-9]+_)?(?:gladcards?_|glad_card_|ground_emote_|freefall_emote_|"
    r"emote_|execution_)",
    re.I,
)
_ANIM_KEYS = (
    "still", "moving", "anim", "animLoop", "anim3p", "attacker",
    "victimLight", "victimMedium", "victimHeavy", "victimNpc",
)
_TRIM_TAIL = re.compile(r"_(?:start|loop)$", re.I)
_KINDS = ("banner", "emote", "finisher")

_CACHE: dict | None = None

# Used when a pose omitted a light0–3 slot.
_DEFAULT_LIGHTS = (
    {"brightness": 0.05, "distance": 800.0, "cone": 40.0, "inner": 1.0, "half": 0.25},
    {"brightness": 0.30, "distance": 800.0, "cone": 50.0, "inner": 1.0, "half": 0.25},
    {"brightness": 0.12, "distance": 400.0, "cone": 20.0, "inner": 1.0, "half": 0.25},
    {"brightness": 0.40, "distance": 500.0, "cone": 80.0, "inner": 1.0, "half": 0.25},
)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _pose_id(text: str) -> str:
    found = list(_POSE_ID.finditer(text or ""))
    if not found:
        return ""
    m = found[-1]
    season = (m.group("season") or "").lower()
    rarity = (m.group("rarity") or "").lower()
    if rarity in {"legendary", "lgnd"}:
        rarity = "lgnd"
    idx = m.group("idx") or ""
    return "_".join(p for p in (season, rarity, idx) if p)


def _anim_stem(path: str) -> str:
    text = Path(str(path or "")).stem.lower().replace("-", "_")
    text = text.replace("gladcards_", "gladcard_").replace("glad_cards_", "gladcard_")
    text = re.sub(r"gladcards$", "gladcard", text)
    text = re.sub(r"_light$", "", text)
    text = re.sub(r"_idle$", "", text)
    text = re.sub(r"_stare$", "", text)
    return text.strip("_")


def _parse_cam_offset(raw: object) -> list[float] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return [float(raw[0]), float(raw[1]), float(raw[2])]
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        text = raw.strip()
        m = re.match(
            r"^<?\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*>?$",
            text,
        )
        if m:
            try:
                return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
            except ValueError:
                return None
    return None

def _anim_nick(path: str) -> str:
    text = _anim_stem(path)
    if not text:
        return ""
    text = _ANIM_PREFIX.sub("", text).strip("_")
    text = re.sub(r"^(static_|animated_)", "", text)
    return text.strip("_")


def _aliases(stem: str) -> list[str]:
    """Full stem plus a start/loop-stripped form (boxing_start → boxing)."""
    text = (stem or "").strip("_")
    if not text:
        return []
    out = [text]
    trimmed = _TRIM_TAIL.sub("", text).strip("_")
    if trimmed and trimmed != text:
        out.append(trimmed)
    return out


def _contained(needle: str, hay: str) -> bool:
    if not needle or not hay:
        return False
    if needle == hay:
        return True
    return f"_{needle}_" in f"_{hay}_"


def legend_keys(legend: str) -> set[str]:
    raw = (legend or "").strip().lower().replace(" ", "")
    if not raw:
        return set()
    keys = {raw}
    if raw in LEGEND_SLUGS:
        keys.add(LEGEND_SLUGS[raw].lower().replace(" ", ""))
    for src, label in LEGEND_SLUGS.items():
        compact = label.lower().replace(" ", "")
        if raw in {src, compact}:
            keys.add(src)
            keys.add(compact)
    keys.discard("")
    return keys


def _iter_items(payload: dict):
    legends = payload.get("legends") or {}
    for bucket in legends.values():
        slug = (bucket.get("slug") or "").lower()
        display = bucket.get("displayName") or ""
        for key in ("static", "animated", "items"):
            for rec in bucket.get(key) or []:
                yield slug, display, rec


def _loc_clip(loc: str, slugs: set[str]) -> str:
    text = (loc or "").lstrip("#")
    text = re.sub(r"_NAME$", "", text, flags=re.I)
    low = text.lower()
    for prefix in _LOC_PREFIXES:
        if low.startswith(prefix.rstrip("_") + "_") or low.startswith(prefix):
            low = re.sub(rf"^{prefix}", "", low)
            break
    for slug in sorted(slugs, key=len, reverse=True):
        if slug and low.startswith(slug + "_"):
            low = low[len(slug) + 1 :]
            break
        if slug and low.endswith("_" + slug):
            low = low[: -(len(slug) + 1)]
            break
    low = re.sub(r"^(stance_|animated_|ground_emote_|emote_|execution_)", "", low).strip("_")
    return re.sub(r"_stare$", "", low).strip("_")


def _stem_clip(stem: str, slugs: set[str]) -> str:
    text = Path(str(stem)).stem.lower().replace("-", "_")
    text = re.sub(r"^(ptpov_|p2|firstperson_)", "", text)
    changed = True
    while changed:
        changed = False
        stripped = _CLIP_PREFIX.sub("", text)
        if stripped != text:
            text = stripped.strip("_")
            changed = True
            continue
        for slug in sorted(slugs, key=len, reverse=True):
            if slug and text.startswith(slug + "_"):
                text = text[len(slug) + 1 :].strip("_")
                changed = True
                break
        if changed:
            continue
        weight = re.match(r"^(?:light|medium|heavy)_?(?:victim_)?", text)
        if weight and weight.end() > 0:
            text = text[weight.end() :].strip("_")
            changed = True
    text = re.sub(r"^(animated_|static_|capturemode_)", "", text)
    text = re.sub(r"_capturemode$", "", text)
    text = re.sub(r"_idle$", "", text)
    return text.strip("_")


def _distinctive(text: str, slugs: set[str] | None = None) -> list[str]:
    skip = _GENERIC | {s.lower() for s in (slugs or set()) if s}
    out = []
    for tok in _tokens(text):
        if tok in skip or tok.isdigit() or len(tok) < 4:
            continue
        if re.fullmatch(r"s\d{1,2}(?:e\d{1,2})?", tok) or re.fullmatch(r"v\d{2}", tok):
            continue
        out.append(tok)
    return out


def _load_json(name: str) -> dict:
    try:
        payload = json.loads((_DIR / name).read_text(encoding="utf-8"))
    except OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_rigs() -> dict[str, dict]:
    """Kind-scoped clip maps. Emote and finisher both use legend/default.json."""
    out: dict[str, dict] = {kind: {} for kind in _KINDS}
    for name in ("itemflav_clips.json", "gcard_stance_rigs.json"):
        payload = _load_json(name)
        legacy = payload.get("rigs")
        if isinstance(legacy, dict):
            out["banner"].update(legacy)
        for kind in _KINDS:
            block = payload.get(kind)
            if isinstance(block, dict):
                out[kind].update(block)
    return out


def _keep_nick(nick: str) -> bool:
    return bool(nick) and len(nick) >= 3 and nick not in _GENERIC and not nick.isdigit()


def _merge_lights(raw: object) -> list[dict]:
    """Four holocard spots. Missing brightness on a present slot means the lamp is off."""
    fallback = [dict(row) for row in _DEFAULT_LIGHTS]
    if not isinstance(raw, list) or not raw:
        return fallback
    aliases = (
        ("brightness", "brightness"),
        ("distance", "distance"),
        ("cone", "cone"),
        ("inner", "inner"),
        ("innercone", "inner"),
        ("half", "half"),
        ("halfbrightfrac", "half"),
        ("pbr", "pbr"),
        ("shadow", "shadow"),
    )
    out: list[dict] = []
    for idx in range(4):
        spec = raw[idx] if idx < len(raw) and isinstance(raw[idx], dict) else None
        if not spec:
            out.append(dict(fallback[idx]))
            continue
        row = dict(fallback[idx])
        for src, dest in aliases:
            if src in spec and spec[src] is not None:
                row[dest] = spec[src]
        if spec.get("brightness") is None:
            row["brightness"] = 0.0
        out.append(row)
    return out


def _attach_rig(prepared: dict, rig: dict) -> None:
    anims: list[str] = []
    nicks: list[str] = []

    def _add_anim(raw: str) -> None:
        for alias in _aliases(_anim_stem(raw)):
            if alias and alias not in anims:
                anims.append(alias)
        for alias in _aliases(_anim_nick(raw)):
            if _keep_nick(alias) and alias not in nicks:
                nicks.append(alias)
            compact = alias.replace("_", "")
            if _keep_nick(compact) and compact != alias and compact not in nicks:
                nicks.append(compact)

    for key in _ANIM_KEYS:
        raw = (rig.get(key) or prepared.get(key) or "")
        if raw:
            _add_anim(str(raw))
    fov = rig.get("fov", prepared.get("fov"))
    try:
        fov = float(fov) if fov is not None else None
    except (TypeError, ValueError):
        fov = None
    prepared["_anims"] = anims
    prepared["_nicks"] = nicks
    if fov is not None and 1.0 <= fov <= 170.0:
        prepared["fov"] = fov
    for key in ("still", "moving", "stillLight", "movingLight"):
        val = rig.get(key) or prepared.get(key)
        if val:
            prepared[key] = val
    if rig.get("hasMoving") or prepared.get("hasMoving"):
        prepared["hasMoving"] = True
    parsed = _parse_cam_offset(rig.get("camOffset", prepared.get("camOffset")))
    if parsed is not None:
        prepared["camOffset"] = parsed
    lights = rig.get("lights") or prepared.get("lights")
    if isinstance(lights, list) and lights:
        prepared["lights"] = lights


def _unique_hit(hits: list[tuple[int, dict]], prefer_stem: str = "") -> dict | None:
    if not hits:
        return None
    hits.sort(key=lambda item: -item[0])
    top = hits[0][0]
    winners = []
    seen = set()
    for score, rec in hits:
        if score != top:
            break
        ident = rec.get("file") or id(rec)
        if ident in seen:
            continue
        seen.add(ident)
        winners.append(rec)
    if len(winners) == 1:
        return winners[0]
    prefer_n = _anim_stem(prefer_stem) if prefer_stem else ""
    if prefer_n:
        preferred = [
            rec
            for rec in winners
            if prefer_n
            in {
                _anim_stem(rec.get("still") or ""),
                _anim_stem(rec.get("moving") or ""),
            }
        ]
        if len(preferred) == 1:
            return preferred[0]
        if preferred:
            winners = preferred
    named = [rec for rec in winners if rec.get("name")]
    return named[0] if len(named) == 1 else None


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    banners = _load_json("banner_poses_by_legend.json")
    emotes = _load_json("character_emotes_by_legend.json")
    execs = _load_json("character_executions_by_legend.json")
    rigs = _load_rigs()
    tables = {"banner": banners, "emote": emotes, "finisher": execs}
    by_legend: dict[str, dict[str, list[dict]]] = {kind: {} for kind in _KINDS}
    for kind, payload in tables.items():
        kind_rigs = rigs.get(kind) or {}
        for slug, display, rec in _iter_items(payload):
            keys = legend_keys(slug) | legend_keys(display)
            prepared = dict(rec)
            prepared["_file_stem"] = Path(rec.get("file") or "").stem.lower()
            prepared["_slugs"] = keys
            prepared["_loc_clip"] = _loc_clip(rec.get("locKey") or "", keys)
            _attach_rig(prepared, kind_rigs.get(prepared.get("file") or "") or {})
            for key in keys:
                by_legend[kind].setdefault(key, []).append(prepared)
    _CACHE = {"tables": tables, "by_legend": by_legend}
    return _CACHE


def _score(rec: dict, stem: str, clip: str, slugs: set[str] | None = None) -> int:
    file_stem = rec.get("_file_stem") or ""
    loc_clip = rec.get("_loc_clip") or ""
    stem_l = _anim_stem(stem)
    clip_l = (clip or "").lower().strip("_")
    id_clip = _pose_id(clip_l) or _pose_id(stem_l)
    id_file = _pose_id(file_stem)
    id_loc = _pose_id(loc_clip)
    ids_conflict = bool(id_clip and id_file and id_clip != id_file)
    best = 0
    for nick in rec.get("_nicks") or []:
        if not _keep_nick(nick):
            continue
        if clip_l == nick or clip_l.endswith("_" + nick):
            best = max(best, 1300 + len(nick))
        elif _contained(nick, stem_l) or nick in clip_l.split("_"):
            best = max(best, 1250 + len(nick))
    for anim in rec.get("_anims") or []:
        if anim and _contained(anim, stem_l):
            best = max(best, 1200 + len(anim))
    if id_clip and id_file and id_clip == id_file:
        best = max(best, 1100 + len(id_file))
    if id_clip and id_loc and id_clip == id_loc:
        best = max(best, 1080 + len(id_loc))
    if clip_l and file_stem and clip_l == file_stem:
        best = max(best, 1000 + len(file_stem))
    if clip_l and loc_clip and clip_l == loc_clip:
        best = max(best, 950 + len(loc_clip))
    if not ids_conflict:
        if file_stem and _contained(file_stem, stem_l):
            best = max(best, 800 + len(file_stem))
        if loc_clip and loc_clip not in _GENERIC and _contained(loc_clip, stem_l):
            best = max(best, 750 + len(loc_clip))
        if clip_l and file_stem and (file_stem.startswith(clip_l) or clip_l.startswith(file_stem)):
            if min(len(clip_l), len(file_stem)) >= 4:
                best = max(best, 500 + min(len(clip_l), len(file_stem)))
    dist = _distinctive(file_stem, slugs) or _distinctive(loc_clip, slugs)
    if dist and all(t in stem_l for t in dist) and not ids_conflict:
        best = max(best, 400 + sum(len(t) for t in dist))
    return best


def _pool_for(kind: str, slugs: set[str]) -> list[dict]:
    data = _load()
    pool: list[dict] = []
    seen = set()
    for key in slugs or [""]:
        for rec in data["by_legend"][kind].get(key, []):
            ident = rec.get("file") or id(rec)
            if ident in seen:
                continue
            seen.add(ident)
            pool.append(rec)
    return pool


def _clip_first(pool: list[dict], stem: str, clip: str) -> dict | None:
    """Prefer the itemflav CAST clip over loose locKey tokens like `_stare`."""
    stem_n = _anim_stem(stem)
    clip_l = (clip or "").lower().strip("_")
    hits = []
    for rec in pool:
        anims = rec.get("_anims") or []
        still = (rec.get("still") or "").lower()
        moving = (rec.get("moving") or "").lower()
        if stem_n and stem_n in {_anim_stem(still), _anim_stem(moving)} | set(anims):
            hits.append((2500 + len(stem_n), rec))
            continue
        best = 0
        for anim in anims:
            if anim and _contained(anim, stem_n):
                best = max(best, 1500 + len(anim))
        for nick in rec.get("_nicks") or []:
            if not _keep_nick(nick):
                continue
            if clip_l == nick or (nick and clip_l.endswith("_" + nick)):
                best = max(best, 800 + len(nick))
        if best:
            hits.append((best, rec))
    return _unique_hit(hits, prefer_stem=stem)


def _unlisted_clip(*parts: object) -> bool:
    try:
        from ..pack import is_unreleased
        return is_unreleased(*parts)
    except Exception:
        return False


def _match(kind: str, name: str, legend: str = "") -> dict | None:
    if _unlisted_clip(name, legend):
        return None
    stem = Path(str(name)).stem
    slugs = legend_keys(legend)
    if not slugs:
        from .anim import guess_legend_from_anim

        slugs = legend_keys(guess_legend_from_anim(stem))
    clip = _stem_clip(stem, slugs)
    pool = _pool_for(kind, slugs)
    if not pool and not slugs:
        return None
    hit = _clip_first(pool, stem, clip)
    if hit is not None:
        return hit
    ranked = []
    for rec in pool:
        score = _score(rec, stem, clip, slugs)
        if score > 0:
            ranked.append((score, rec))
    return _unique_hit(ranked, prefer_stem=stem)


def match_banner(name: str, legend: str = "") -> dict | None:
    return _match("banner", name, legend)


def match_emote(name: str, legend: str = "") -> dict | None:
    stem = Path(str(name)).stem.lower()
    if "freefall" in stem:
        return None
    if re.search(r"(^|_)drop(_|$)", stem) and "ground_emote" not in stem:
        return None
    return _match("emote", name, legend)


def match_finisher(name: str, legend: str = "") -> dict | None:
    return _match("finisher", name, legend)


def resolve_banner_name(name: str, legend: str = "") -> str:
    return (match_banner(name, legend) or {}).get("name") or ""


def resolve_emote_name(name: str, legend: str = "") -> str:
    return (match_emote(name, legend) or {}).get("name") or ""


def resolve_finisher_name(name: str, legend: str = "") -> str:
    return (match_finisher(name, legend) or {}).get("name") or ""


def banner_kind_for(name: str, legend: str = "") -> str:
    kind = (match_banner(name, legend) or {}).get("kind") or ""
    return kind if kind in {"static", "animated"} else ""


def banner_fov_for(name: str, legend: str = "") -> float | None:
    fov = (match_banner(name, legend) or {}).get("fov")
    try:
        val = float(fov)
    except (TypeError, ValueError):
        return None
    if 1.0 <= val <= 170.0:
        return val
    return None


def banner_setup_for(name: str, legend: str = "") -> dict:
    """FOV, lighting-rig clip, and 4-spot holocard fields for a banner CAST."""
    rec = match_banner(name, legend) or {}
    raw = Path(str(name)).stem.lower()
    stem = _anim_stem(name)
    moving = (rec.get("moving") or "").lower()
    still = (rec.get("still") or "").lower()
    moving_n = _anim_stem(moving) if moving else ""
    still_n = _anim_stem(still) if still else ""
    is_idle = bool(re.search(r"(^|_)idle(_|$)", raw))
    use_moving = bool(
        moving
        and not is_idle
        and (stem == moving_n or raw == moving or _contained(moving_n or moving, stem))
    )
    light = rec.get("movingLight") if use_moving else rec.get("stillLight")
    if not light:
        light = rec.get("stillLight") or rec.get("movingLight") or ""
    offset = _parse_cam_offset(rec.get("camOffset"))
    kind = rec.get("kind") or ""
    if kind not in {"static", "animated"}:
        kind = "animated" if rec.get("hasMoving") or moving else ("static" if still else "")
    return {
        "name": rec.get("name") or "",
        "file": rec.get("file") or "",
        "kind": kind,
        "fov": rec.get("fov"),
        "offset": tuple(float(x) for x in offset) if offset else None,
        "light": light,
        "still": still,
        "moving": moving,
        "lights": _merge_lights(rec.get("lights")),
    }

