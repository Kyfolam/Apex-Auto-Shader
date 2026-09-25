from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from ..constants import (
    CANON_LEGENDS,
    EYE_HASH_MESHES,
    EXPECTED_SLOTS,
    IMAGE_SUFFIX_RANK,
    IMAGE_SUFFIXES,
    LEGEND_SLUGS,
    LEVEL_CODES,
    MESH_PARTS,
    MIN_OBJECT_PREFIX_TOKENS,
    PREFIX_TOKEN_COUNT,
    RARITY_DIR,
    RARITY_LABELS,
    RECOLOR_CODES,
    SKIP_DIR_NAMES,
    SKIP_SLOTS,
    SLOT_ALIASES,
    SLOT_SHORT,
    TECHART_LEGENDS_PARTS,
)

# rt01 / rc02 / shared01, plus compound dumps like rt01rc01
_RECOLOR_TOKEN = re.compile(
    r"^(?:(?:rt|rc)\d{2}){1,2}$|^shared0[12]$",
    re.IGNORECASE,
)
# Palette skins that reuse the legend base CAST / bodyModel
_BASE_SKIN_REST = re.compile(r"^(common|rare|epicp?)(?:_|$)", re.IGNORECASE)


_LEVEL_CYCLE = re.compile(r"level0([123])", re.IGNORECASE)


_LEVEL_IN_PATH = re.compile(r"(?:^|_|/)(level0[123])(?:_|/|$)", re.IGNORECASE)


HAIR_PARTS = frozenset({"hair", "hair02", "hair_l", "hair_r", "lash", "lashes", "eyebrow", "brows"})
SKIN_PARTS = frozenset({"body", "head", "arms", "legs", "skin", "face", "hand", "hands", "torso"})
_LOD_TOKEN = re.compile(r"lod(\d+)", re.IGNORECASE)

_CAST_LOD_GROUP = re.compile(r"^(body|kit|hair|gear|head|arms|legs|glass)_\d+_", re.IGNORECASE)
_MESH_INDEX_PREFIX = re.compile(r"^(?P<part>[A-Za-z]+)_\d+_", re.IGNORECASE)
IGNORED_BODYPART_TOKENS = {
    "lod0",
    "lod1",
    "lod2",
    "lod3",
    "w",
    "m",
    "f",
    "colpass",
    "prepass",
    "shadow",
    "tightshadow",
    "vsm",
    "skel",
    "cast",
}
AUX_BODYPART_SUFFIXES = frozenset(
    {"colpass", "prepass", "shadow", "tightshadow", "vsm"}
)

HIDE_ON_SHADE_MATERIALS = frozenset()
HIDE_ON_SHADE_LAST_TOKENS = frozenset()
EYE_MATERIALS = frozenset(
    {
        "body_0_wraith_base_eyecornea",
        "body_0_wraith_base_eyeshadow",
    }
)
EYE_LAST_TOKENS = frozenset({"eyecornea", "eyeshadow"})

_BLENDER_DUP = re.compile(r"\.\d{3}$")


@dataclass(frozen=True)
class TextureRef:
    path: str
    filename: str
    prefix: str
    bodypart: str
    slot_raw: str
    slot: str | None

    @property
    def known(self) -> bool:
        return self.slot is not None


@dataclass
class MatchResult:
    source_name: str
    prefix: str
    textures: list[TextureRef] = field(default_factory=list)
    unmatched_files: list[str] = field(default_factory=list)
    recolor_code: str = ""

    def bodyparts(self) -> list[str]:
        seen: list[str] = []
        for tex in self.textures:
            if tex.bodypart not in seen:
                seen.append(tex.bodypart)
        return seen

    def by_bodypart(self) -> dict[str, list[TextureRef]]:
        grouped: dict[str, list[TextureRef]] = defaultdict(list)
        for tex in self.textures:
            grouped[tex.bodypart].append(tex)
        return dict(grouped)

    def slots_for(self, bodypart: str) -> dict[str, TextureRef]:
        out: dict[str, TextureRef] = {}
        for tex in self.textures:
            if tex.bodypart == bodypart and tex.slot:
                out[tex.slot] = tex
        return out


def tokenize(name: str) -> list[str]:
    stem = Path(str(name)).stem
    stem = _BLENDER_DUP.sub("", stem)
    return [t for t in stem.split("_") if t]


def strip_blender_suffix(name: str) -> str:
    return _BLENDER_DUP.sub("", Path(str(name)).stem)


def strip_cast_lod_group(name: str) -> str:
    return _CAST_LOD_GROUP.sub("", strip_blender_suffix(name))


def is_variant_token(token: str) -> bool:
    key = (token or "").lower()
    if key in LEVEL_CODES or key == "base":
        return True
    return bool(_RECOLOR_TOKEN.match(key))


def is_recolor_code(token: str) -> bool:
    return bool(_RECOLOR_TOKEN.match(token or ""))


def file_variant(name: str, parent_name: str = "") -> str:
    toks = [t.lower() for t in tokenize(name)]
    if parent_name:
        toks.extend(t.lower() for t in tokenize(parent_name))
    for tok in toks:
        if is_recolor_code(tok):
            return tok
    for lv in reversed(LEVEL_CODES):
        if lv in toks:
            return lv
    if "base" in toks:
        return "base"
    return ""


def recolor_tokens_in(name: str) -> list[str]:
    found = []
    for tok in tokenize(name):
        key = tok.lower()
        if _RECOLOR_TOKEN.match(key) and key not in found:
            found.append(key)
    return found


def split_recolor_prefix(name: str) -> tuple[str, str]:
    """Split ``legend_skin_rc01`` into ``(legend_skin, rc01)``.

    Recolor skins reuse the base CAST / bodyModel. The rc/rt token lives on
    the itemflav filename and the exported material folders, not the mesh.
    """
    toks = [t for t in tokenize(name) if t]
    code = ""
    kept: list[str] = []
    for tok in toks:
        if is_recolor_code(tok):
            code = tok.lower()
        else:
            kept.append(tok)
    return "_".join(kept), code


def with_recolor_prefix(base: str, code: str) -> str:
    base = (base or "").strip("_")
    code = (code or "").strip("_").lower()
    if not code:
        return base
    if not base:
        return code
    existing_base, existing_code = split_recolor_prefix(base)
    stem = existing_base or base
    if existing_code == code:
        return stem + "_" + code if stem else code
    return f"{stem}_{code}" if stem else code


def legend_slug_from_prefix(prefix: str) -> str:
    low = (prefix or "").lower()
    if not low:
        return ""
    for slug in sorted(LEGEND_SLUGS.keys(), key=len, reverse=True):
        if low == slug or low.startswith(slug + "_"):
            return slug
    toks = tokenize(low)
    return toks[0] if toks else ""


def split_mesh_variant(prefix: str) -> tuple[str, str]:
    """Split a skin-index extra into ``(cast_prefix, variant)``.

    Legendary recolors: ``alter_lgnd_x_rc02`` → ``(alter_lgnd_x, rc02)``.
    Common/Rare/Epic palettes share the base CAST: ``alter_rare_01`` →
    ``(alter_base, rare_01)``.
    """
    raw = (prefix or "").strip()
    if not raw:
        return "", ""
    base, rc = split_recolor_prefix(raw)
    text = base or raw
    slug = legend_slug_from_prefix(text)
    if not slug:
        return text, rc
    rest = text[len(slug) :].lstrip("_")
    rest_l = rest.lower()
    if rest_l in {"", "base", "classic", "default"}:
        return f"{slug}_base", rc
    if _BASE_SKIN_REST.match(rest_l):
        return f"{slug}_base", rest_l
    return text, rc


def cast_search_prefixes(prefix: str) -> list[str]:
    """CAST stems to try for a skin-index extra (recolor / palette → base mesh)."""
    raw = (prefix or "").strip()
    if not raw:
        return []
    mesh, _variant = split_mesh_variant(raw)
    base, _code = split_recolor_prefix(raw)
    out: list[str] = []
    for item in (raw, base, mesh):
        if item and item not in out:
            out.append(item)
    return out


def pick_recolor_code(names: Iterable[str], parents: Iterable[str] | None = None) -> str:
    present = set()
    for name in names:
        present.update(recolor_tokens_in(name))
    if parents:
        for name in parents:
            present.update(recolor_tokens_in(name))
    for code in RECOLOR_CODES:
        if code in present:
            return code
    return next(iter(sorted(present)), "")


def available_recolor_codes(
    names: Iterable[str], parents: Iterable[str] | None = None
) -> list[str]:
    present = set()
    for name in names:
        present.update(recolor_tokens_in(name))
    if parents:
        for name in parents:
            present.update(recolor_tokens_in(name))
    ordered = [code for code in RECOLOR_CODES if code in present]
    extra = [code for code in sorted(present) if code not in ordered]
    return ordered + extra


def cycle_recolor_code(available: Iterable[str], current: str | None) -> str:
    cycle = [""] + [code for code in RECOLOR_CODES if code in set(available)]
    if len(cycle) == 1:
        return ""
    cur = current or ""
    if cur not in cycle:
        return cycle[1]
    return cycle[(cycle.index(cur) + 1) % len(cycle)]


def list_folder_recolors(folder: str | Path, prefix: str) -> list[str]:
    names: list[str] = []
    parents: list[str] = []
    for root in recolor_search_roots(folder, prefix):
        for path in iter_texture_files(root):
            names.append(path.name)
            parents.append(path_variant_blob(path))
    return available_recolor_codes(names, parents)


def path_variant_blob(path: Path) -> str:
    parts = [path.name]
    parts.extend(reversed(path.parts[-5:]))
    return "_".join(parts)


def detect_target_level(prefix: str, names: Iterable[str] | None = None) -> str:
    ident = parse_skin_identity(prefix)
    if ident.level in LEVEL_CODES:
        return ident.level
    pv = file_variant(prefix)
    if pv in LEVEL_CODES:
        return pv
    present = set()
    for name in names or []:
        fv = file_variant(name)
        if fv in LEVEL_CODES or fv == "base":
            present.add(fv)
    for lv in reversed(LEVEL_CODES):
        if lv in present:
            return lv
    if "base" in present:
        return "base"
    return ""


def fallback_chain(target_level: str) -> list[str]:
    chain = [""]
    if target_level in LEVEL_CODES:
        for lv in reversed(LEVEL_CODES):
            chain.append(lv)
    return chain


def level_rank(fv: str) -> int:
    if fv in LEVEL_CODES:
        return LEVEL_CODES.index(fv) + 1
    return 0


def variant_priority(fv: str, target: str, recolor: str = "") -> int:
    fv = fv or ""
    target = target or ""
    recolor = recolor or ""
    if recolor and fv == recolor:
        return 800
    if is_recolor_code(fv):
        return -1
    if fv == "base" and target != "base":
        return -1
    if target in LEVEL_CODES or fv in LEVEL_CODES:
        if fv in LEVEL_CODES:
            return 200 + level_rank(fv)
        if fv == "":
            return 40
        return -1
    if fv in LEVEL_CODES:
        return -1
    return 100


def should_hide_on_shade(name: str) -> bool:
    return False


def is_eye_material(name: str) -> bool:
    if not name:
        return False
    stem = strip_blender_suffix(name).lower()
    if stem in EYE_MATERIALS:
        return True
    toks = tokenize(stem)
    return bool(toks) and toks[-1] in EYE_LAST_TOKENS


def is_numeric_filler_mesh(name: str) -> bool:
    if eye_hash_kind(name):
        return False
    toks = tokenize(strip_blender_suffix(name))
    if len(toks) < 3:
        return False
    if toks[0].lower() != "body" or not toks[1].isdigit():
        return False
    return all(t.isdigit() for t in toks[2:])



def eye_hash_kind(name: str) -> str:
    for tok in tokenize(strip_blender_suffix(name)):
        kind = EYE_HASH_MESHES.get(tok)
        if kind:
            return kind
    return ""


def mesh_slot_prefix(name: str) -> str:
    found = _MESH_INDEX_PREFIX.match(strip_blender_suffix(name or ""))
    return found.group("part").lower() if found else ""


def last_name_token(name: str) -> str:
    toks = [t.lower() for t in tokenize(strip_blender_suffix(name))]
    return toks[-1] if toks else ""


def should_hide_base_hair(names: Iterable[str]) -> bool:
    tokens = {last_name_token(n) for n in names if n}
    return "hair" in tokens and "hair02" in tokens


def cycled_level_name(name: str) -> str:
    found = _LEVEL_CYCLE.search(name or "")
    if not found:
        return ""

    def _swap(match: re.Match) -> str:
        digit = int(match.group(1))
        nxt = 1 if digit == 3 else digit + 1
        return match.group(0)[:-1] + str(nxt)

    return _LEVEL_CYCLE.sub(_swap, name, count=1)


_VERSION_TOKEN = re.compile(r"^v\d+", re.I)


@dataclass(frozen=True)
class SkinIdentity:
    legend: str
    rarity: str
    rarity_label: str
    version: str
    skin: str
    level: str
    key: str
    display: str


def strip_model_suffix(name: str) -> str:
    stem = strip_blender_suffix(Path(str(name)).stem)
    kind, key = normalize_vw_part(stem)
    text = key if kind else stem
    text = re.sub(r"_?lod\d+$", "", text, flags=re.I)
    return text.strip("_")


def parse_skin_identity(name: str) -> SkinIdentity:
    stem = strip_model_suffix(name)
    toks = tokenize(stem)
    legend = toks[0].lower() if toks else ""
    idx = 1
    rarity = ""
    if idx < len(toks) and toks[idx].lower() in RARITY_LABELS:
        rarity = toks[idx].lower()
        idx += 1
    version = ""
    if idx < len(toks) and _VERSION_TOKEN.match(toks[idx]):
        version = toks[idx].lower()
        idx += 1
    rest: list[str] = []
    level = ""
    skip = {"w", "v", "lod0", "lod1", "lod2", "lod3"}
    for tok in toks[idx:]:
        low = tok.lower()
        if low in LEVEL_CODES:
            level = low
        elif low in skip or is_recolor_code(low):
            continue
        else:
            rest.append(tok)
    while rest:
        low = rest[-1].lower()
        if low in SLOT_ALIASES or low in MESH_PARTS:
            rest.pop()
            continue
        break
    skin = "_".join(rest)
    display = skin or rarity or version or legend or stem
    if not rarity and level:
        rarity = "mythic"
    rarity_label = RARITY_LABELS.get(rarity, "Other")
    legend_canon = LEGEND_SLUGS.get(legend, legend)
    key = "_".join(part for part in (legend, rarity, version, skin, level) if part)
    return SkinIdentity(
        legend=legend_canon.lower().replace(" ", "") if legend_canon else legend,
        rarity=rarity,
        rarity_label=rarity_label,
        version=version,
        skin=skin,
        level=level,
        key=key.lower(),
        display=display,
    )


def unique_skin_casts(paths: Iterable[Path]) -> list[Path]:
    best: dict[str, Path] = {}
    scores: dict[str, tuple] = {}
    order: list[str] = []
    for path in paths:
        ident = parse_skin_identity(path.name)
        if not ident.skin:
            folder = parse_skin_identity(path.parent.name)
            if folder.skin or folder.level:
                ident = folder
        key = ident.key or str(path).lower()
        kind, _ = path_vw_identity(path)
        score = (1 if kind == "w" else 0, -len(path.parts), -len(path.name))
        if key not in best:
            order.append(key)
            best[key] = path
            scores[key] = score
        elif score > scores[key]:
            best[key] = path
            scores[key] = score
    return [best[key] for key in order]


def find_cycled_cast(current: Path, extra_roots: Iterable[Path] | None = None) -> Path | None:
    current = Path(current)
    file_next = cycled_level_name(current.name)
    dir_next = cycled_level_name(current.parent.name)
    if not file_next and not dir_next:
        return None
    if file_next and not file_next.lower().endswith(".cast"):
        file_next = f"{file_next}.cast"
    target_name = file_next or (f"{dir_next}.cast" if dir_next else "")
    target = parse_skin_identity(target_name or current.name)
    candidates: list[Path] = []
    if file_next:
        candidates.append(current.with_name(file_next))
        if dir_next:
            candidates.append(current.parent.parent / dir_next / file_next)
    roots = [current.parent, current.parent.parent]
    if extra_roots:
        roots.extend(Path(p) for p in extra_roots)
    seen_root: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key in seen_root or not root.is_dir():
            continue
        seen_root.add(key)
        if file_next:
            direct = root / file_next
            if direct.is_file():
                candidates.append(direct)
            for hit in root.rglob(file_next):
                if hit.is_file():
                    candidates.append(hit)
        if dir_next:
            folder = root / dir_next
            if folder.is_dir():
                candidates.extend(collect_lod0_casts(folder))
    found: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            if not path.is_file():
                continue
            ident = str(path.resolve())
        except OSError:
            continue
        if ident in seen:
            continue
        seen.add(ident)
        found.append(path)
    found = unique_skin_casts(prefer_world_lod0(found, current.parent.parent))
    for path in found:
        ident = parse_skin_identity(path.name)
        if not ident.skin:
            ident = parse_skin_identity(path.parent.name)
        if target.legend and ident.legend and ident.legend != target.legend:
            continue
        if target.skin and ident.skin and ident.skin != target.skin:
            continue
        if target.level and ident.level and ident.level != target.level:
            continue
        return path
    return found[0] if found else None


def skin_prefix(name: str, token_count: int = PREFIX_TOKEN_COUNT) -> str:
    ident = parse_skin_identity(name)
    toks = tokenize(strip_cast_lod_group(name))
    while toks and toks[-1].lower() in IGNORED_BODYPART_TOKENS:
        toks.pop()
    if not toks:
        return ""
    if ident.level and ident.level not in {t.lower() for t in toks}:
        toks.append(ident.level)
    return "_".join(toks)


def model_dir_name(name: str) -> str:
    """CAST / mesh stem without body_N_ group prefix or trailing _LOD#."""
    stem = strip_cast_lod_group(Path(str(name)).stem)
    return re.sub(r"_?lod\d+$", "", stem, flags=re.I).strip("_")


def model_dir_names(name: str) -> list[str]:
    full = model_dir_name(name)
    names: list[str] = []
    seen: set[str] = set()
    for cand in (full,):
        key = cand.lower()
        if cand and key not in seen:
            seen.add(key)
            names.append(cand)
    kind, key = normalize_vw_part(full)
    if kind and key and key.lower() not in seen:
        names.append(key)
    return names


def is_canon_legend_slug(slug: str) -> bool:
    key = (slug or "").lower().replace(" ", "")
    if not key:
        return False
    if key in CANON_LEGENDS:
        return True
    label = LEGEND_SLUGS.get(key, "")
    compact = label.lower().replace(" ", "")
    if compact in CANON_LEGENDS:
        return True
    return compact in {c.replace(" ", "") for c in CANON_LEGENDS}


def is_legend_character_name(name: str) -> bool:
    ident = parse_skin_identity(name)
    return is_canon_legend_slug(ident.legend)


def is_legend_character_path(path: str | Path) -> bool:
    p = Path(path)
    parts = [x.lower() for x in p.parts]
    if "legends" in parts:
        idx = parts.index("legends")
        if idx + 1 < len(parts) and is_canon_legend_slug(parts[idx + 1]):
            return True
    return is_legend_character_name(p.name)


_NUMERIC_INDEX = re.compile(r"^\d+$")
_GENERIC_OBJECT_SUBDIRS = frozenset(
    {"skins", "shared", "textures", "texture", "images", "maps", "materials"}
)


def _object_tokens(name: str) -> list[str]:
    toks = [t.lower() for t in tokenize(Path(str(name)).stem)]
    return [t for t in toks if t not in IGNORED_BODYPART_TOKENS]


def shared_leading_tokens(a: str, b: str) -> list[str]:
    ta = _object_tokens(a)
    tb = _object_tokens(b)
    shared: list[str] = []
    for x, y in zip(ta, tb):
        if x != y:
            break
        shared.append(x)
    return shared


def min_object_prefix_len(model_name: str) -> int:
    toks = _object_tokens(model_name)
    while toks and _NUMERIC_INDEX.match(toks[-1]):
        toks.pop()
    if len(toks) <= 1:
        return max(1, len(toks))
    return min(MIN_OBJECT_PREFIX_TOKENS, len(toks))


def object_prefixes_match(model_name: str, filename: str) -> bool:
    shared = shared_leading_tokens(model_name, filename)
    need = min_object_prefix_len(model_name)
    return len(shared) >= need


def mesh_lod(name: str) -> int:
    found = _LOD_TOKEN.search(strip_blender_suffix(name or ""))
    return int(found.group(1)) if found else 0


def is_model_cast(name: str) -> bool:
    stem = Path(str(name)).stem
    return bool(_LOD_TOKEN.search(stem))


def is_lod0_cast(name: str) -> bool:
    found = _LOD_TOKEN.search(Path(str(name)).stem)
    return bool(found) and int(found.group(1)) == 0


_VW_PART = re.compile(r"(^|_)([vw])(_lod\d+)?$", re.I)


def normalize_vw_part(part: str) -> tuple[str | None, str]:
    raw = Path(str(part)).name
    if raw.lower().endswith(".cast"):
        raw = Path(raw).stem
    match = _VW_PART.search(raw)
    if not match:
        return None, raw.lower()
    kind = match.group(2).lower()
    key = (raw[: match.start()] + (match.group(3) or "")).strip("_").lower()
    return kind, key


def lod0_view_world(name: str) -> tuple[str | None, str]:
    return normalize_vw_part(name)


def path_vw_identity(path: Path, root: Path | None = None) -> tuple[str | None, str]:
    try:
        rel = path.relative_to(root) if root is not None else Path(path)
    except ValueError:
        rel = Path(path)
    kind = None
    parts: list[str] = []
    for part in rel.parts:
        found, key = normalize_vw_part(part)
        if found:
            kind = found
        parts.append(key)
    return kind, "/".join(parts) if parts else Path(path).name.lower()


def prefer_world_lod0(paths: Iterable[Path], root: Path | None = None) -> list[Path]:
    groups: dict[str, dict[str, Path]] = {}
    leftover: list[Path] = []
    for path in paths:
        kind, key = path_vw_identity(path, root)
        if kind is None:
            leftover.append(path)
            continue
        groups.setdefault(key, {})[kind] = path
    chosen: list[Path] = []
    for pair in groups.values():
        chosen.append(pair["w"] if "w" in pair else next(iter(pair.values())))
    return sorted(leftover + chosen, key=lambda p: str(p).lower())


def collect_lod0_casts(folder: str | Path) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.cast")):
        if not path.is_file() or not is_lod0_cast(path.name):
            continue
        try:
            ident = str(path.resolve())
        except OSError:
            ident = str(path)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(path)
    return unique_skin_casts(prefer_world_lod0(out, root))


def suggest_prefixes_from_names(names: Iterable[str], token_count: int = PREFIX_TOKEN_COUNT) -> list[str]:
    counts: dict[str, int] = {}
    for raw in names:
        toks = tokenize(Path(str(raw)).stem)
        if len(toks) < token_count:
            continue
        pref = "_".join(toks[:token_count])
        counts[pref] = counts.get(pref, 0) + 1
    return [key for key, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def missing_slots(have: Iterable[str], expected: Iterable[str] = EXPECTED_SLOTS) -> list[str]:
    owned = set()
    for raw in have:
        slot = canonical_slot(raw) if raw else None
        owned.add(slot or str(raw).lower())
    return [slot for slot in expected if slot not in owned]


def format_missing_part(bodypart: str, slots: Iterable[str]) -> str:
    shorts = [SLOT_SHORT.get(s, s) for s in slots]
    if not shorts:
        return ""
    return f"{bodypart}: kein {', '.join(shorts)}"


def canonical_slot(raw: str) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if s.endswith("texture"):
        s = s[: -len("texture")]
    return SLOT_ALIASES.get(s) or SLOT_ALIASES.get(s + "texture")


def _split_after_prefix(file_toks: list[str], prefix_toks: list[str]) -> list[str] | None:
    if not file_toks or not prefix_toks:
        return None
    file_l = [t.lower() for t in file_toks]
    if file_l[0] != prefix_toks[0].lower():
        return None
    prefix_l = [t.lower() for t in prefix_toks if not is_variant_token(t)]
    if not prefix_l:
        prefix_l = [t.lower() for t in prefix_toks]
    idx = 0
    pi = 0
    while idx < len(file_l) and pi < len(prefix_l):
        if is_variant_token(file_toks[idx]):
            idx += 1
            continue
        if file_l[idx] == prefix_l[pi]:
            pi += 1
            idx += 1
            continue
        later = [t.lower() for t in file_toks[idx + 1 :] if not is_variant_token(t)]
        if prefix_l[pi] in later:
            idx += 1
            continue
        break
    return file_toks[idx:]


def _bodypart_from_parent(parent_name: str, prefix_toks: list[str]) -> str:
    if not parent_name:
        return ""
    toks = tokenize(parent_name)
    rest = _split_after_prefix(toks, prefix_toks) if prefix_toks else toks
    if rest is None:
        rest = toks
    rest = [t for t in rest if not is_variant_token(t)]
    if not rest:
        return toks[-1].lower() if toks else ""
    return "_".join(t.lower() for t in rest)


def is_aux_bodypart(name: str) -> bool:
    toks = tokenize(name)
    return bool(toks) and toks[-1].lower() in AUX_BODYPART_SUFFIXES


def prefixes_compatible(filename: str, prefix: str) -> bool:
    if not filename or not prefix:
        return True
    file_id = parse_skin_identity(filename)
    pref_id = parse_skin_identity(prefix)
    if file_id.legend and pref_id.legend and file_id.legend != pref_id.legend:
        return False
    if file_id.rarity == "base" and pref_id.rarity == "base" and file_id.legend == pref_id.legend:
        return True
    if file_id.rarity == "base" and pref_id.rarity and pref_id.rarity != "base":
        return False
    if pref_id.rarity == "base" and file_id.rarity and file_id.rarity not in {"", "base"}:
        return False
    if file_id.version and pref_id.version and file_id.version != pref_id.version:
        return False
    if file_id.skin and pref_id.skin and file_id.skin != pref_id.skin:
        if pref_id.skin in file_id.skin or file_id.skin in pref_id.skin:
            return True
        if file_id.legend == pref_id.legend and file_id.version and file_id.version == pref_id.version:
            return True
        return False
    return True


def parse_texture_name(
    filename: str,
    prefix: str | None = None,
    token_count: int = PREFIX_TOKEN_COUNT,
    parent_name: str = "",
) -> TextureRef | None:
    raw_name = Path(str(filename)).name
    toks = tokenize(raw_name)
    if not toks:
        return None

    if prefix:
        prefix_toks = tokenize(prefix)
    else:
        prefix_toks = toks[:token_count]
        prefix = "_".join(prefix_toks)

    slot_raw = toks[-1]
    slot = canonical_slot(slot_raw)
    if slot is None and len(toks) == 1:
        return None

    if len(toks) == 1 and slot:
        bodypart = _bodypart_from_parent(parent_name, prefix_toks)
        if not bodypart or bodypart in IGNORED_BODYPART_TOKENS or is_aux_bodypart(bodypart):
            return None
        return TextureRef(
            path=str(filename),
            filename=raw_name,
            prefix=prefix,
            bodypart=bodypart,
            slot_raw=slot_raw,
            slot=slot,
        )

    if len(toks) < 2:
        return None

    rest = _split_after_prefix(toks[:-1], prefix_toks)
    if rest is None:
        parent_key = (parent_name or "").lower()
        parent_var = file_variant("", parent_name)
        if (
            is_recolor_code(parent_var)
            or parent_var in LEVEL_CODES
            or parent_key in {"shared", "skins"}
            or Path(parent_name).name.lower() in LEVEL_CODES
        ):
            rest = [t for t in toks[:-1] if not is_variant_token(t)]
        else:
            return None
    elif prefix and not prefixes_compatible(raw_name, prefix):
        return None
    body_toks = [t for t in rest if not is_variant_token(t)]
    if not body_toks:
        bodypart = _bodypart_from_parent(parent_name, prefix_toks)
    else:
        bodypart = "_".join(t.lower() for t in body_toks)
    if not bodypart or bodypart in IGNORED_BODYPART_TOKENS or is_aux_bodypart(bodypart):
        return None
    if slot is None:
        slot = canonical_slot(slot_raw)

    return TextureRef(
        path=str(filename),
        filename=raw_name,
        prefix=prefix,
        bodypart=bodypart,
        slot_raw=slot_raw,
        slot=slot,
    )


def parse_object_texture_name(
    filename: str,
    prefix: str,
    parent_name: str = "",
) -> TextureRef | None:
    """Match prop/object maps by a shared leading token prefix, not an exact skin id.

    Model:  uh_snapback_statue_legend_alter_01_LOD0
    Texture: uh_snapback_statue_legend_alter_onemat_ao.png
    Shared:  uh_snapback_statue_legend_alter  → bodypart onemat, slot ao
    """
    raw_name = Path(str(filename)).name
    toks = tokenize(raw_name)
    if len(toks) < 2:
        return None
    slot_raw = toks[-1]
    slot = canonical_slot(slot_raw)
    if slot is None or slot in SKIP_SLOTS or is_ignored_slot(slot_raw):
        return None
    if not object_prefixes_match(prefix, raw_name):
        return None
    shared_n = len(shared_leading_tokens(prefix, raw_name))
    rest = [t.lower() for t in toks[shared_n:-1] if not is_variant_token(t)]
    bodypart = "_".join(rest) if rest else ""
    if not bodypart:
        bodypart = _bodypart_from_parent(parent_name, tokenize(prefix))
    if not bodypart or bodypart in IGNORED_BODYPART_TOKENS or is_aux_bodypart(bodypart):
        bodypart = "object"
    return TextureRef(
        path=str(filename),
        filename=raw_name,
        prefix=prefix,
        bodypart=bodypart,
        slot_raw=slot_raw,
        slot=slot,
    )


def _object_subfolder_ok(part: str, model_prefix: str) -> bool:
    low = (part or "").lower()
    if not low or low in SKIP_DIR_NAMES:
        return False
    if low in _GENERIC_OBJECT_SUBDIRS:
        return True
    if is_variant_token(low) or low in LEVEL_CODES:
        return True
    model = model_dir_name(model_prefix).lower()
    if low == model or low.startswith(model) or model.startswith(low):
        return True
    shared = shared_leading_tokens(model_prefix, part)
    need = min_object_prefix_len(model_prefix)
    if len(shared) < need:
        return False
    fa = _object_tokens(part)
    fb = _object_tokens(model_prefix)
    while fa and _NUMERIC_INDEX.match(fa[-1]):
        fa.pop()
    while fb and _NUMERIC_INDEX.match(fb[-1]):
        fb.pop()
    for x, y in zip(fa, fb):
        if x != y:
            return False
    return True


def _object_file_in_scope(path: Path, root: Path, prefix: str) -> bool:
    try:
        rel = path.parent.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        try:
            rel = path.parent.relative_to(root)
        except ValueError:
            return False
    if rel == Path("."):
        return True
    return all(_object_subfolder_ok(part, prefix) for part in rel.parts)


def scan_object_folder(folder: str | Path, prefix: str) -> MatchResult:
    """Scan only this folder and matching subfolders (no texture/art walk)."""
    result = MatchResult(source_name=str(folder), prefix=prefix)
    root = Path(folder)
    if not root.is_dir():
        return result
    collected: list[TextureRef] = []
    for path in iter_texture_files(root):
        if not _object_file_in_scope(path, root, prefix):
            continue
        parsed = parse_object_texture_name(
            str(path), prefix=prefix, parent_name=path.parent.name
        )
        if parsed is None:
            result.unmatched_files.append(path.name)
            continue
        collected.append(parsed)
    result.textures = dedupe_textures(collected)
    return result


def iter_texture_files(folder: str | Path) -> Iterator[Path]:
    root = Path(folder)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if any(part in SKIP_DIR_NAMES or is_aux_bodypart(part) for part in path.parts):
            continue
        yield path


def texture_score(path: Path, bodypart: str) -> tuple:
    parent = path.parent.name.lower()
    stem = path.stem.lower()
    blob = path_variant_blob(path).lower()
    bp = (bodypart or "").lower()
    score = 0
    if bp:
        if parent == bp or parent.endswith("_" + bp):
            score += 100
        elif bp in parent.split("_"):
            score += 50
        if f"_{bp}_" in f"_{stem}_":
            score += 20
    fv = file_variant(stem, blob)
    found_levels = levels_in_path(path)
    if fv in LEVEL_CODES:
        found_levels.add(fv)
    if fv in LEVEL_CODES:
        score += 40
    for lv in found_levels:
        if fv and lv == fv:
            score += 30
        elif fv and lv != fv:
            score -= 20
    ext = IMAGE_SUFFIX_RANK.get(path.suffix.lower(), -1)
    return (score, ext, -len(path.parts), str(path).lower())


def dedupe_textures(textures: list[TextureRef]) -> list[TextureRef]:
    best: dict[tuple[str, str], TextureRef] = {}
    best_score: dict[tuple[str, str], tuple] = {}
    for tex in textures:
        if not tex.slot:
            continue
        key = (tex.bodypart, tex.slot)
        score = texture_score(Path(tex.path), tex.bodypart)
        if key not in best or score > best_score[key]:
            best[key] = tex
            best_score[key] = score
    extras = [t for t in textures if not t.slot]
    return list(best.values()) + extras


def is_ignored_slot(raw: str) -> bool:
    if not raw:
        return False
    s = raw.strip().lower()
    if s.endswith("texture"):
        s = s[: -len("texture")]
    return s in SKIP_SLOTS


def _keep_variant(name: str, prefix: str, variant: str | None, parent_name: str = "") -> bool:
    toks = tokenize(name)
    if toks and is_ignored_slot(toks[-1]):
        return False
    fv = file_variant(name, parent_name)
    ident = parse_skin_identity(prefix)
    if ident.rarity == "base" and fv == "base":
        fv = ""
    if variant is not None:
        return fv == variant
    if is_recolor_code(fv):
        return False
    pv = file_variant(prefix)
    if ident.rarity == "base" and pv == "base":
        pv = ""
    if not pv and ident.level:
        pv = ident.level
    if fv in LEVEL_CODES:
        if ident.level or pv in LEVEL_CODES:
            return True
        return False
    if fv == "base":
        return fv == pv or ident.rarity == "base"
    return True


def scan_folder(
    folder: str | Path,
    prefix: str,
    token_count: int = PREFIX_TOKEN_COUNT,
    recolor_code: str | None = None,
    variant: str | None = None,
) -> MatchResult:
    base_prefix, embedded = split_recolor_prefix(prefix)
    parse_prefix = base_prefix or prefix
    want = variant if variant is not None else recolor_code
    if want is None and embedded:
        want = embedded
    result = MatchResult(source_name=str(folder), prefix=parse_prefix, recolor_code=want or "")
    root = Path(folder)
    if not root.is_dir():
        return result

    collected: list[TextureRef] = []
    for path in iter_texture_files(root):
        blob = path_variant_blob(path)
        if not _keep_variant(path.name, parse_prefix, want, blob):
            continue
        parsed = parse_texture_name(
            str(path),
            prefix=parse_prefix,
            token_count=token_count,
            parent_name=blob,
        )
        if parsed is None:
            result.unmatched_files.append(path.name)
            continue
        if parsed.slot in SKIP_SLOTS or is_ignored_slot(parsed.slot_raw):
            continue
        collected.append(
            TextureRef(
                path=str(path),
                filename=path.name,
                prefix=parsed.prefix,
                bodypart=parsed.bodypart,
                slot_raw=parsed.slot_raw,
                slot=parsed.slot,
            )
        )
    result.textures = dedupe_textures(collected)
    return result


def match_folder_from_names(
    source_name: str,
    filenames: Iterable[str],
    token_count: int = PREFIX_TOKEN_COUNT,
    recolor_code: str | None = None,
    variant: str | None = None,
) -> MatchResult:
    prefix = skin_prefix(source_name, token_count=token_count)
    want = variant if variant is not None else recolor_code
    result = MatchResult(source_name=source_name, prefix=prefix, recolor_code=want or "")
    collected: list[TextureRef] = []
    for name in filenames:
        path = Path(name)
        if not _keep_variant(path.name, prefix, want, path.parent.name):
            continue
        parsed = parse_texture_name(
            name,
            prefix=prefix,
            token_count=token_count,
            parent_name=path.parent.name,
        )
        if parsed is None:
            continue
        if parsed.slot in SKIP_SLOTS or is_ignored_slot(parsed.slot_raw):
            continue
        collected.append(parsed)
    result.textures = dedupe_textures(collected)
    return result


def overlay_match(base: MatchResult, overlay: MatchResult) -> MatchResult:
    merged = MatchResult(
        source_name=overlay.source_name or base.source_name,
        prefix=overlay.prefix or base.prefix,
        recolor_code=overlay.recolor_code or base.recolor_code,
    )
    by_key: dict[tuple[str, str], TextureRef] = {}
    for tex in base.textures:
        if tex.slot:
            by_key[(tex.bodypart, tex.slot)] = tex
    for tex in overlay.textures:
        if tex.slot:
            by_key[(tex.bodypart, tex.slot)] = tex
    merged.textures = list(by_key.values())
    return merged


def _path_in_folder(path_str: str, folder: str | Path) -> bool:
    root = Path(folder)
    if not root.is_dir():
        return False
    try:
        Path(path_str).resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        low = str(root).replace("\\", "/").lower()
        return low in str(path_str).replace("\\", "/").lower()


def _layered_from_entries(
    source_name: str,
    prefix: str,
    entries: Iterable[tuple[str, str]],
    token_count: int,
    recolor: str = "",
) -> MatchResult:
    target = detect_target_level(
        prefix, [name for name, _ in entries] + [parent for _, parent in entries]
    )
    ident = parse_skin_identity(prefix)
    primary_is_dir = Path(source_name).is_dir()
    buckets: dict[tuple[str, str], list[tuple]] = {}
    for name, parent in entries:
        fv = file_variant(name, parent)
        if ident.rarity == "base" and fv == "base":
            fv = ""
        if recolor:
            if is_recolor_code(fv) and fv != recolor:
                continue
        elif is_recolor_code(fv):
            continue
        prio = variant_priority(fv, target, recolor)
        if prio < 0:
            continue
        parsed = parse_texture_name(
            name, prefix=prefix, token_count=token_count, parent_name=parent
        )
        if parsed is None or not parsed.slot:
            continue
        if parsed.slot in SKIP_SLOTS or is_ignored_slot(parsed.slot_raw):
            continue
        key = (parsed.bodypart, parsed.slot)
        local = 1 if (not primary_is_dir or _path_in_folder(name, source_name)) else 0
        # Recolor overlays live in Legion materials/, not next to the CAST.
        # Priority must beat the local-folder bias or base maps always win.
        score = (prio, local) + texture_score(Path(parsed.path), parsed.bodypart)
        buckets.setdefault(key, []).append((score, parsed))
    chosen: dict[tuple[str, str], TextureRef] = {}
    for key, items in buckets.items():
        if recolor:
            pool = items
        else:
            local_items = [item for item in items if item[0][1] == 1]
            pool = local_items or items
        pool.sort(key=lambda item: item[0], reverse=True)
        chosen[key] = pool[0][1]
    result = MatchResult(
        source_name=source_name, prefix=prefix, recolor_code=recolor or target or ""
    )
    result.textures = list(chosen.values())
    return result


def stack_recolor_from_names(
    source_name: str,
    filenames: Iterable[str],
    token_count: int = PREFIX_TOKEN_COUNT,
) -> MatchResult:
    names = list(filenames)
    prefix = skin_prefix(source_name, token_count=token_count)
    entries = [(name, Path(name).parent.name) for name in names]
    rt = pick_recolor_code(Path(n).name for n in names)
    return _layered_from_entries(source_name, prefix, entries, token_count, recolor=rt)


def scan_recolor_stack(
    folder: str | Path,
    prefix: str,
    token_count: int = PREFIX_TOKEN_COUNT,
    apply_recolor: bool = False,
    recolor_code: str | None = None,
    target_level: str | None = None,
    source_name: str = "",
) -> MatchResult:
    _ = target_level, source_name
    base_prefix, embedded = split_recolor_prefix(prefix)
    parse_prefix = base_prefix or prefix
    if recolor_code is None and embedded:
        recolor_code = embedded
        apply_recolor = True
    roots = recolor_search_roots(folder, prefix)
    files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for path in iter_texture_files(root):
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    names = [p.name for p in files]
    parents = [path_variant_blob(p) for p in files]
    if apply_recolor:
        rt = recolor_code if recolor_code is not None else pick_recolor_code(names, parents)
    else:
        rt = ""
    entries = [(str(path), blob) for path, blob in zip(files, parents)]
    return _layered_from_entries(str(folder), parse_prefix, entries, token_count, recolor=rt)


def texture_dir_name_from_cast(cast_name: str) -> str:
    stem = Path(str(cast_name)).stem
    if len(stem) > 5:
        return stem[:-5]
    return stem


def rarity_search_dirs(ident: SkinIdentity) -> list[str]:
    mapped = RARITY_DIR.get(ident.rarity, "")
    dirs: list[str] = []
    if mapped:
        dirs.append(mapped)
    if ident.level or ident.rarity in {"mythic", "prestige"}:
        for extra in ("mythic", "prestige"):
            if extra not in dirs:
                dirs.append(extra)
    return dirs


def skin_folder_names(ident: SkinIdentity) -> list[str]:
    names: list[str] = []
    version, skin, level = ident.version, ident.skin, ident.level
    if version and skin:
        names.append(f"{version}_{skin}")
        if level:
            names.append(f"{version}_{skin}_{level}")
    if skin:
        names.append(skin)
        if level:
            names.append(f"{skin}_{level}")
    if version and level:
        names.append(f"{version}_{level}")
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def prestige_level_paths(branch: Path, ident: SkinIdentity) -> list[Path]:
    paths: list[Path] = []
    slugs = skin_folder_names(ident)
    if ident.level:
        for slug in slugs:
            paths.append(branch / slug / ident.level)
            paths.append(branch / ident.level / slug)
            paths.append(branch / f"{slug}_{ident.level}")
        paths.append(branch / ident.level)
    for slug in slugs:
        paths.append(branch / slug)
        paths.append(branch / slug / "skins")
        for lv in LEVEL_CODES:
            if ident.level and lv == ident.level:
                continue
            paths.append(branch / slug / lv)
            paths.append(branch / lv / slug)
            paths.append(branch / f"{slug}_{lv}")
    for lv in LEVEL_CODES:
        if ident.level and lv == ident.level:
            continue
        paths.append(branch / lv)
    return paths


def levels_in_path(path: Path | str) -> set[str]:
    raw = Path(path)
    blob = "/".join(raw.parts) + "_" + "_".join(raw.parts)
    blob = blob.replace("\\", "/").lower()
    return {m.group(1).lower() for m in _LEVEL_IN_PATH.finditer(blob)}


def folder_level_score(path: Path, ident: SkinIdentity) -> int:
    parts = [p.lower() for p in path.parts]
    blob = "_".join(parts)
    found = levels_in_path(path)
    score = 0
    if ident.level:
        if ident.level in found:
            score += 200
        elif found:
            score -= 150
    if ident.skin and any(ident.skin.lower() in p for p in parts):
        score += 40
    elif ident.skin and ident.skin.lower() in blob:
        score += 40
    if ident.version and (
        ident.version.lower() in parts or ident.version.lower() in blob
    ):
        score += 15
    rarity = RARITY_DIR.get(ident.rarity, "")
    if rarity and rarity in parts:
        score += 10
    elif ident.level and "mythic" in parts:
        score += 10
    return score


def _seq_index(parts: list[str], seq: tuple[str, ...]) -> int:
    n = len(seq)
    for i in range(0, len(parts) - n + 1):
        if tuple(parts[i : i + n]) == seq:
            return i
    return -1


def _child_dir(parent: Path, name: str) -> Path | None:
    if not name:
        return None
    exact = parent / name
    if exact.is_dir():
        return exact
    want = name.lower()
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name.lower() == want:
                return child
    except OSError:
        return None
    return None


def find_techart_legends_root(path: str | Path) -> Path | None:
    """`.../mdl/techart/mshop/characters/legends` next to a CAST or export root."""
    current = Path(path)
    if current.suffix:
        current = current.parent
    parts = list(current.parts)
    lower = [p.lower() for p in parts]
    idx = _seq_index(lower, TECHART_LEGENDS_PARTS)
    if idx >= 0:
        return Path(*parts[: idx + len(TECHART_LEGENDS_PARTS)])
    for parent in [current, *current.parents]:
        nested = parent.joinpath(*TECHART_LEGENDS_PARTS)
        if nested.is_dir():
            return nested
        if parent.name.lower() == "mdl":
            nested = parent.joinpath(*TECHART_LEGENDS_PARTS[1:])
            if nested.is_dir():
                return nested
    return None


def is_techart_legends_dir(path: Path) -> bool:
    lower = [p.lower() for p in Path(path).parts]
    return _seq_index(lower, TECHART_LEGENDS_PARTS) >= 0


def techart_legend_texture_candidates(cast_path: str | Path) -> list[Path]:
    """Primary legend PNG location: mdl/techart/mshop/characters/legends/{legend}/{model}/."""
    path = Path(cast_path)
    if not is_legend_character_path(path):
        return []
    root = find_techart_legends_root(path)
    if root is None:
        return []
    ident = parse_skin_identity(path.name)
    legend = ident.legend if is_canon_legend_slug(ident.legend) else ""
    if not legend:
        parts = [p.lower() for p in path.parts]
        if "legends" in parts:
            idx = parts.index("legends")
            if idx + 1 < len(parts) and is_canon_legend_slug(parts[idx + 1]):
                legend = parts[idx + 1]
    if not legend:
        return []
    from .anim import legend_folder_needles

    slugs = legend_folder_needles(legend) or [legend]
    models = model_dir_names(path.name)
    out: list[Path] = []
    seen: set[str] = set()

    def add(cand: Path | None) -> None:
        if cand is None:
            return
        key = str(cand).replace("\\", "/").lower()
        if key in seen:
            return
        seen.add(key)
        out.append(cand)

    for slug in slugs:
        legend_dir = _child_dir(root, slug)
        if legend_dir is None:
            continue
        for model in models:
            model_dir = _child_dir(legend_dir, model)
            add(model_dir)
            if model_dir is not None:
                add(model_dir / "skins")
            add(legend_dir / model)
        add(legend_dir)
    return out


def object_texture_folder_candidates(cast_path: str | Path) -> list[Path]:
    """CAST parent + subfolder named like the model without _LOD#."""
    path = Path(cast_path)
    parent = path.parent
    out: list[Path] = []
    seen: set[str] = set()
    for name in model_dir_names(path.name):
        for cand in (parent / name, parent / name.lower()):
            key = str(cand).replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(cand)
    out.append(parent)
    return out


def _legend_tex_root_from_parts(parts: tuple[str, ...] | list[str]) -> Path | None:
    lower = [p.lower() for p in parts]
    if "legends" not in lower:
        return None
    i = lower.index("legends")
    if i + 1 >= len(parts):
        return None
    if "mdl" in lower:
        mi = lower.index("mdl")
        root = Path(*parts[:mi]) if mi else None
        rest = list(parts[mi + 1 :])
        if rest and rest[0].lower() == "techart":
            rest = rest[1:]
        low_rest = [p.lower() for p in rest]
        if "legends" not in low_rest:
            return None
        li = low_rest.index("legends")
        legend_rel = rest[: li + 2]
        if root is None:
            return None
        return root / "texture" / "art" / Path(*legend_rel)
    i = lower.index("legends")
    return Path(*parts[: i + 2])


def parallel_texture_candidates(cast_path: str | Path) -> list[Path]:
    path = Path(cast_path)
    ident = parse_skin_identity(path.name)
    parts = path.parts
    lower = [p.lower() for p in parts]
    out: list[Path] = []
    if "mdl" in lower:
        i = lower.index("mdl")
        root = Path(*parts[:i]) if i else None
        rest = list(parts[i + 1 :])
        if rest and rest[0].lower() == "techart":
            rest = rest[1:]
        if rest and Path(rest[-1]).suffix:
            rest = rest[:-1]
        if root is not None:
            tex = root / "texture" / "art"
            if rest:
                tex = tex.joinpath(*rest)
            out.append(tex)
            legend_root = _legend_tex_root_from_parts(parts)
            if legend_root is not None:
                if ident.rarity == "base" or ident.rarity_label == "Original":
                    if ident.skin:
                        out.append(legend_root / "base" / "skins" / ident.skin)
                    out.append(legend_root / "base" / "skins")
                    out.append(legend_root / "base")
                else:
                    dirs = rarity_search_dirs(ident) or [""]
                    for rarity in dirs:
                        branch = legend_root / rarity if rarity else legend_root
                        out.extend(prestige_level_paths(branch, ident))
                        if rarity:
                            out.append(branch)
                out.append(legend_root)
    legend_root = _legend_tex_root_from_parts(parts)
    if legend_root is not None and legend_root not in out:
        out.append(legend_root)
    return out


def texture_folder_candidates(cast_path: str | Path) -> list[Path]:
    path = Path(cast_path)
    parent = path.parent
    folder_name = texture_dir_name_from_cast(path.name)
    ident = parse_skin_identity(path.name)
    local = [
        parent / folder_name,
        parent.parent / folder_name,
        parent / "Textures" / folder_name,
        parent / "textures" / folder_name,
        parent.parent / "Textures" / folder_name,
        parent.parent / "textures" / folder_name,
        parent / "Textures",
        parent / "textures",
        parent,
    ]
    if ident.level:
        local.insert(0, parent / ident.level)
        local.insert(0, parent / folder_name / ident.level)
        for slug in skin_folder_names(ident):
            local.insert(0, parent / slug / ident.level)
            local.insert(0, parent / f"{slug}_{ident.level}")
    ordered = (
        techart_legend_texture_candidates(path)
        + object_texture_folder_candidates(path)
        + local
        + parallel_texture_candidates(path)
    )
    out: list[Path] = []
    seen: set[str] = set()
    for cand in ordered:
        key = str(cand).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def _folder_has_maps(folder: Path, prefix: str, ident: SkinIdentity) -> bool:
    if prefix:
        hit = scan_folder(folder, prefix)
        if hit.textures:
            return True
        _base, code = split_recolor_prefix(prefix)
        if code:
            hit = scan_folder(folder, _base or prefix, recolor_code=code)
            if hit.textures:
                return True
        if ident.level:
            hit = scan_folder(folder, prefix, variant=ident.level)
            if hit.textures:
                return True
        obj = scan_object_folder(folder, prefix)
        if obj.textures:
            return True
        obj = scan_object_folder(folder, model_dir_name(prefix) or prefix)
        if obj.textures:
            return True
        return False
    return any(True for _ in iter_texture_files(folder))


def find_texture_folder(cast_path: str | Path, recolor_code: str = "") -> Path | None:
    path = Path(cast_path)
    prefix = skin_prefix(path.name)
    ident = parse_skin_identity(path.name)
    code = (recolor_code or split_recolor_prefix(prefix)[1] or "").lower()
    object_pref = model_dir_name(path.name) or prefix
    fallback = None
    ranked: list[tuple[int, int, Path]] = []
    seen: set[str] = set()

    techart = techart_legend_texture_candidates(path)
    if code:
        for cand in recolor_texture_folder_candidates(path, code):
            try:
                if not cand.is_dir():
                    continue
            except OSError:
                continue
            if _folder_has_maps(cand, with_recolor_prefix(prefix, code), ident):
                return cand
            if _folder_has_maps(cand, prefix, ident):
                return cand

    for cand in techart:
        try:
            if not cand.is_dir():
                continue
        except OSError:
            continue
        check = with_recolor_prefix(prefix, code) if code else prefix
        if _folder_has_maps(cand, check, ident) or (code and _folder_has_maps(cand, prefix, ident)):
            return cand

    for cand in texture_folder_candidates(path):
        try:
            key = str(cand.resolve())
        except OSError:
            key = str(cand)
        if key in seen or not cand.is_dir():
            continue
        seen.add(key)
        if ident.level:
            found_levels = levels_in_path(cand)
            if found_levels and ident.level not in found_levels:
                continue
        files = list(iter_texture_files(cand))
        if not files:
            continue
        if prefix or object_pref:
            check = with_recolor_prefix(prefix or object_pref, code) if code else (prefix or object_pref)
            if not _folder_has_maps(cand, check, ident) and not (
                code and _folder_has_maps(cand, prefix or object_pref, ident)
            ):
                if fallback is None:
                    fallback = cand
                continue
        score = folder_level_score(cand, ident)
        if is_techart_legends_dir(cand):
            score += 500
        if object_pref and cand.name.lower() == object_pref.lower():
            score += 80
        ranked.append((score, len(cand.parts), cand))
    if ranked:
        if ident.level:
            leveled = [item for item in ranked if ident.level in levels_in_path(item[2])]
            if leveled:
                ranked = leveled
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked[0][2]
    return fallback


def _materials_search_roots(start: str | Path) -> list[Path]:
    """Walk up from a CAST / texture folder to Legion/RSX ``materials`` trees.

    Recolor maps are not on the CAST. They live as overlay folders next to
    ``models/`` — typically ``exported_files/materials/<skin>_rc01_body/``.
    """
    path = Path(start)
    out: list[Path] = []
    seen: set[str] = set()

    def add(cand: Path) -> None:
        try:
            key = str(cand.resolve()) if cand.exists() else str(cand)
        except OSError:
            key = str(cand)
        if key in seen:
            return
        seen.add(key)
        out.append(cand)

    cur = path if path.suffix.lower() != ".cast" else path.parent
    for _ in range(6):
        add(cur / "materials")
        add(cur / "Materials")
        add(cur / "exported_files" / "materials")
        add(cur / "exported_files" / "Materials")
        add(cur / "textures")
        add(cur / "Textures")
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return out


def recolor_search_roots(folder: str | Path, prefix: str) -> list[Path]:
    root = Path(folder)
    ident = parse_skin_identity(prefix)
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            if not path.is_dir():
                return
            key = str(path.resolve())
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    add(root)
    dummy = root / f"{prefix}_w_LOD0.cast" if root.suffix.lower() != ".cast" else root
    for cand in parallel_texture_candidates(dummy):
        add(cand)
    base_prefix, code = split_recolor_prefix(prefix)
    if code:
        for cand in recolor_texture_folder_candidates(dummy, code):
            add(cand)
        for cand in recolor_texture_folder_candidates(root, code):
            add(cand)
    _add_recolor_sibling_dirs(root, base_prefix or prefix, code, add)
    for mat_root in _materials_search_roots(dummy):
        add(mat_root)
    for mat_root in _materials_search_roots(root):
        add(mat_root)
    legend_root = _legend_tex_root_from_parts(dummy.parts)
    if legend_root is None:
        legend_root = _legend_tex_root_from_parts(root.parts)
    if legend_root is not None:
        if ident.rarity == "base" or ident.rarity_label == "Original":
            skins = legend_root / "base" / "skins"
            if ident.skin:
                add(skins / ident.skin)
                add(skins / ident.skin / "shared")
                for code in RECOLOR_CODES:
                    add(skins / ident.skin / code)
            add(skins)
            add(legend_root / "base")
        else:
            dirs = rarity_search_dirs(ident) or [""]
            for rarity in dirs:
                branch = legend_root / rarity if rarity else legend_root
                for cand in prestige_level_paths(branch, ident):
                    add(cand)
                if rarity:
                    add(branch)
    return found


def _add_recolor_sibling_dirs(root: Path, base: str, code: str, add) -> None:
    parent = root.parent if root.name else root
    search = [root, parent, parent.parent]
    token = (code or "").lower()
    skin = (base or "").lower()
    tail = skin.split("_")[-1] if skin else ""
    seen: set[str] = set()
    for folder in search:
        try:
            if not folder.is_dir():
                continue
            key = str(folder.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            name = child.name.lower()
            if token:
                if token in name and (not tail or tail in name or skin in name):
                    add(child)
            elif skin and any(c in name for c in RECOLOR_CODES) and (tail in name or skin in name):
                add(child)


def recolor_texture_folder_candidates(cast_path: str | Path, recolor_code: str) -> list[Path]:
    """Sibling folders where RSX/Legion dumps recolor materials of a base CAST."""
    path = Path(cast_path)
    code = (recolor_code or "").lower()
    if not code:
        return []
    prefix = skin_prefix(path.name)
    base, _embedded = split_recolor_prefix(prefix)
    base = base or prefix
    ident = parse_skin_identity(base or path.name)
    names = []
    for raw in (
        with_recolor_prefix(base, code),
        with_recolor_prefix(path.stem, code),
        with_recolor_prefix(model_dir_name(path.name), code),
    ):
        if raw and raw not in names:
            names.append(raw)
    if ident.skin:
        names.append(f"{ident.skin}_{code}")
        names.append(with_recolor_prefix(ident.skin, code))
    out: list[Path] = []
    seen: set[str] = set()

    def add(cand: Path) -> None:
        try:
            key = str(cand.resolve()) if cand.exists() else str(cand)
        except OSError:
            key = str(cand)
        if key in seen:
            return
        seen.add(key)
        out.append(cand)

    bases = list(texture_folder_candidates(path))
    bases.extend(techart_legend_texture_candidates(path))
    bases.extend(_materials_search_roots(path))
    if path.suffix.lower() != ".cast" and path.is_dir():
        bases.append(path)
        bases.append(path.parent)
    for cand in bases:
        add(cand)
        parent = cand.parent
        for name in names:
            add(parent / name)
            add(cand / name)
            add(parent / f"{name}_body")
            add(parent / f"{cand.name}_{code}")
        try:
            if not parent.is_dir():
                continue
            kids = list(parent.iterdir())
        except OSError:
            continue
        tail = (ident.skin or base.split("_")[-1] if base else "").lower()
        for child in kids:
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            n = child.name.lower()
            if code in n and (not tail or tail in n or (base and base.lower() in n)):
                add(child)
    return out



def guess_bodypart(haystacks: Iterable[str], bodyparts: Iterable[str]) -> str | None:
    known = sorted({bp.lower() for bp in bodyparts if bp}, key=len, reverse=True)
    known_set = set(known)

    def suffix_hit(toks: list[str]) -> str | None:
        for bp in known:
            bp_toks = bp.split("_")
            n = len(bp_toks)
            if n <= len(toks) and toks[-n:] == bp_toks:
                return bp
        return None

    for raw in haystacks:
        if not raw:
            continue
        cleaned = strip_cast_lod_group(raw)
        toks = [t.lower() for t in tokenize(cleaned)]
        if toks:
            hit = suffix_hit(toks)
            if hit:
                return hit
        part = mesh_slot_prefix(raw)
        if part and part != "body":
            if part in known_set or part in {"kit", "glass", "gear", "hair", "head"}:
                return part
    return None


GLASS_FAMILY = frozenset(
    {"glass", "inner_glass", "outer_glass", "visor", "visor_glass"}
)
TRANSPARENT_FAMILY = frozenset({"transparent", "trans", "alpha"})


def is_glass_family(name: str) -> bool:
    n = (name or "").lower().strip("_")
    if not n:
        return False
    if n in GLASS_FAMILY:
        return True
    if n.startswith("glass") or n.endswith("_glass") or n.endswith("glass"):
        return True
    return False


def is_transparent_family(name: str) -> bool:
    n = (name or "").lower().strip("_")
    if not n:
        return False
    if n in TRANSPARENT_FAMILY:
        return True
    return n.endswith("_transparent") or n.endswith("_trans")


def is_hash_kit_mesh(name: str) -> bool:
    toks = tokenize(strip_blender_suffix(name or ""))
    if len(toks) < 3:
        return False
    if toks[0].lower() != "kit" or not toks[1].isdigit():
        return False
    return all(t.isdigit() for t in toks[2:])


def mesh_level(name: str) -> str:
    found = ""
    for tok in tokenize(strip_blender_suffix(name or "")):
        low = tok.lower()
        if low in LEVEL_CODES:
            found = low
    return found


def dir_prestige_level(name: str) -> str:
    low = Path(str(name)).name.lower()
    if low in LEVEL_CODES:
        return low
    found = ""
    for match in _LEVEL_CYCLE.finditer(low):
        found = match.group(0).lower()
    return found if found in LEVEL_CODES else ""


def identity_level(*names: str) -> str:
    for raw in names:
        if not raw:
            continue
        path = Path(str(raw))
        candidates = [path.name, path.stem]
        if len(path.parts) > 1:
            candidates.append(path.parent.name)
        for cand in candidates:
            ident = parse_skin_identity(cand)
            if ident.level in LEVEL_CODES:
                return ident.level
            lv = dir_prestige_level(cand)
            if lv in LEVEL_CODES:
                return lv
            named = mesh_level(cand)
            if named in LEVEL_CODES and dir_prestige_level(cand):
                return named
    return ""


def path_folder_level(path: Path | str | None = None, parent_name: str = "") -> str:
    """Exact directory names level01/02/03 only."""
    found = ""
    if path is not None:
        for part in Path(path).parts[:-1]:
            low = part.lower()
            if low in LEVEL_CODES:
                found = low
        if found:
            return found
    if parent_name:
        low = Path(str(parent_name)).name.lower()
        if low in LEVEL_CODES:
            return low
    return ""


def _texture_variant(tex: TextureRef) -> str:
    parent = ""
    try:
        parent = Path(tex.path).parent.name
    except Exception:
        pass
    return file_variant(tex.filename, parent)


def related_bodyparts(bodypart: str, known: Iterable[str]) -> list[str]:
    bp = (bodypart or "").lower()
    known_list = [k.lower() for k in known if k]
    if not bp:
        return []
    if is_glass_family(bp):
        related = [k for k in known_list if is_glass_family(k)]
        return related or [bp]
    if is_transparent_family(bp):
        related = [k for k in known_list if is_transparent_family(k)]
        return related or [bp]
    stem = bp.split("_")[-1]
    if stem in {"kit", "gear"}:
        related = [k for k in known_list if k == stem or k.endswith("_" + stem)]
        return related or [bp]
    return [bp]



def _prefer_for_bodypart(
    tex_list: list[TextureRef],
    bodypart: str,
    level: str = "",
    recolor_code: str = "",
    allow_same_folder_leftover: bool = False,
    mesh_level_tiebreak: str = "",
) -> list[TextureRef]:
    """Filter the already-layered scan to one bodypart. Do not re-rank prestige leftovers."""
    _ = level, recolor_code, allow_same_folder_leftover, mesh_level_tiebreak
    known: list[str] = []
    seen: set[str] = set()
    for tex in tex_list:
        if tex.bodypart and tex.bodypart not in seen:
            seen.add(tex.bodypart)
            known.append(tex.bodypart)
    bp = (bodypart or "").lower()
    family = set(related_bodyparts(bp, known))
    family.add(bp)
    candidates = [t for t in tex_list if t.bodypart and t.bodypart in family]
    by_slot: dict[str, TextureRef] = {}
    for tex in sorted(candidates, key=lambda t: (0 if t.bodypart == bp else 1, t.filename.lower())):
        if tex.slot and tex.slot not in by_slot:
            by_slot[tex.slot] = tex
    return list(by_slot.values())


def prefer_textures(
    textures: Iterable[TextureRef],
    bodypart: str,
    level: str = "",
    recolor_code: str = "",
    allow_same_folder_leftover: bool = False,
    mesh_level_tiebreak: str = "",
) -> list[TextureRef]:
    tex_list = list(textures)
    picked = _prefer_for_bodypart(tex_list, bodypart)
    if is_transparent_family(bodypart):
        has_trans = any(is_transparent_family(t.bodypart) for t in picked)
        if not has_trans:
            picked = _prefer_for_bodypart(tex_list, "body")
    return picked
