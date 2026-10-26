from __future__ import annotations

import base64
import bisect
import difflib
import hashlib
import hmac
import os
import re
import struct
import zlib
from pathlib import Path

_ROWS: list[tuple[str, str, str]] | None = None
_HDR = 16
_CAP = 250
_BROWSE_CAP = 2000
_P0 = "7a3c"
_P1 = "e91b"
_P2 = "44d0"
_ID = "apex_auto_shader"
_TITLE = "Apex Auto Shader"
# Packed RCCH index (skins). Prefer ncache.bin when it is current.
_SEED_MIN = 2640


def _stamps():
    from .constants import (
        ASSET_REV_MARK,
        CORES_GRAPH_STAMP,
        FORK_AUTHOR,
        PLUS_GRAPH_STAMP,
        SRC_AUTHOR,
    )
    return PLUS_GRAPH_STAMP, CORES_GRAPH_STAMP, SRC_AUTHOR, FORK_AUTHOR, ASSET_REV_MARK


def _tail() -> str:
    return _P0 + _P1 + _P2


def _token() -> bytes:
    a, b, c, d, e = _stamps()
    decoy = "".join((a, b, c, d, e))
    salt = _tail()
    material = (_ID + _TITLE + decoy + salt).encode("utf-8")
    return hmac.new(salt.encode("utf-8"), material, hashlib.sha256).digest()


def _mix(data: bytes, key: bytes | None = None) -> bytes:
    key = key if key is not None else _token()
    out = bytearray(len(data))
    i = 0
    ctr = 0
    while i < len(data):
        block = hashlib.sha256(key + struct.pack(">Q", ctr)).digest()
        n = min(32, len(data) - i)
        for j in range(n):
            out[i + j] = data[i + j] ^ block[j]
        i += n
        ctr += 1
    return bytes(out)


def _map_path() -> Path:
    root = Path(__file__).resolve().parent / "asset" / "wraith"
    for name in ("ncache.bin", ".nodemap"):
        path = root / name
        if path.is_file():
            return path
    return root / "ncache.bin"


def _seed_path() -> Path:
    return Path(__file__).resolve().parent / "asset" / "wraith" / "ncache.b64"


def _seed_parts() -> list[Path]:
    root = Path(__file__).resolve().parent / "asset" / "wraith"
    return sorted(p for p in root.glob("ncache.b64*") if p.is_file())


def _put(buf: bytearray, text: str) -> None:
    raw = text.encode("utf-8")
    buf.extend(struct.pack("<H", len(raw)))
    buf.extend(raw)


def _get(data: bytes, i: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("<H", data, i)
    i += 2
    return data[i : i + n].decode("utf-8"), i + n


def _encode(legends: list[str], records: list[tuple[int, str, str]]) -> bytes:
    buf = bytearray()
    buf.extend(struct.pack("<H", len(legends)))
    for name in legends:
        _put(buf, name)
    buf.extend(struct.pack("<H", len(records)))
    for idx, name, extra in records:
        buf.extend(struct.pack("<H", idx))
        _put(buf, name)
        _put(buf, extra)
    return zlib.compress(bytes(buf), 9)


def _wrap(payload: bytes) -> bytes:
    chk = hashlib.sha256(payload).digest()[:4]
    hdr = b"RCCH" + struct.pack("<HHI", 1, _HDR, len(payload)) + chk
    if len(hdr) != _HDR:
        raise RuntimeError("bad header")
    return hdr + payload


def _read_rows(blob: bytes) -> list[tuple[str, str, str]]:
    if len(blob) <= _HDR:
        return []
    hdr, body = blob[:_HDR], blob[_HDR:]
    if hdr[:4] != b"RCCH":
        return []
    ver, hlen, plen = struct.unpack_from("<HHI", hdr, 4)
    chk = hdr[12:16]
    if ver != 1 or hlen != _HDR or plen != len(body):
        return []
    if hashlib.sha256(body).digest()[:4] != chk:
        return []
    plain = zlib.decompress(_mix(body))
    i = 0
    (nleg,) = struct.unpack_from("<H", plain, i)
    i += 2
    legends: list[str] = []
    for _ in range(nleg):
        name, i = _get(plain, i)
        legends.append(name)
    (nrec,) = struct.unpack_from("<H", plain, i)
    i += 2
    rows: list[tuple[str, str, str]] = []
    for _ in range(nrec):
        (idx,) = struct.unpack_from("<H", plain, i)
        i += 2
        name, i = _get(plain, i)
        extra, i = _get(plain, i)
        rows.append((legends[idx], name, extra))
    return rows



def write_unlisted(needles: list[str] | tuple[str, ...], path: str | Path | None = None) -> None:
    """Pack Unlisted tokens into ncache.bin (same format as the skin list)."""
    global _ROWS, _UNRELEASED, _SHARED
    rows = [(lg, name, extra) for lg, name, extra in load_index() if not is_unlisted_legend(lg)]
    legends: list[str] = []
    index: dict[str, int] = {}
    records: list[tuple[int, str, str]] = []
    for lg, name, extra in rows:
        key = lg or ""
        if key not in index:
            index[key] = len(legends)
            legends.append(key)
        records.append((index[key], name, extra or ""))
    clean: list[str] = []
    seen: set[str] = set()
    for raw in needles:
        token = (raw or "").strip().lower()
        if len(token) < 4 or token in seen or token in _UNLISTED_MARKS:
            continue
        seen.add(token)
        clean.append(token)
    if clean:
        if _UNLISTED not in index:
            index[_UNLISTED] = len(legends)
            legends.append(_UNLISTED)
        idx = index[_UNLISTED]
        for token in clean:
            records.append((idx, token, token))
    dest = Path(path) if path else _map_path()
    write_index(dest, legends, records)
    _ROWS = None
    _UNRELEASED = None
    _SHARED = None


def write_index(path: str | Path, legends: list[str], records: list[tuple[int, str, str]]) -> None:
    global _ROWS
    payload = _mix(_encode(legends, records))
    Path(path).write_bytes(_wrap(payload))
    _ROWS = None


def _load_blob() -> bytes:
    path = _map_path()
    blob = b""
    if path.is_file():
        try:
            blob = path.read_bytes()
        except OSError:
            blob = b""
    seeds = _seed_parts()
    if seeds:
        try:
            raw = "".join(p.read_text(encoding="ascii") for p in seeds)
            packed = base64.b64decode("".join(raw.split()))
        except Exception:
            packed = b""
        if packed.startswith(b"RCCH"):
            if not blob.startswith(b"RCCH"):
                return packed
            try:
                old_n = len(_read_rows(blob))
            except Exception:
                old_n = 0
            try:
                new_n = len(_read_rows(packed))
            except Exception:
                new_n = 0
            if new_n >= old_n and new_n >= _SEED_MIN:
                return packed
    return blob


def load_index() -> list[tuple[str, str, str]]:
    global _ROWS
    if _ROWS is not None:
        return _ROWS
    rows: list[tuple[str, str, str]] = []
    try:
        rows = _read_rows(_load_blob())
    except Exception:
        rows = []
    _ROWS = rows
    return _ROWS


_PRESTIGE_WORDS = frozenset({"prestige", "mythic"})
_BASE_WORDS = frozenset({"base", "standard", "original", "default"})
_UNIQUE_MARKS = ("_lgnd_", "_icon_", "_mythic_", "_epicp_")
# rt01 / rc02 / rt01rc01 on the extra tail
_RC_TAIL = re.compile(r"(?:^|_)(?:(?:rt|rc)\d{2}){1,2}$", re.IGNORECASE)
# Shared-folder palettes and event rares/epics that reuse the base CAST
_LOW_RARITY = re.compile(r"(?:^|_)(common|rare|epic)(?:_|$)", re.IGNORECASE)
_RARITY_LABEL = re.compile(
    r"^(?:common|rare|epic|legendary|heirloom|mythic)(?:\s+\d+)?$",
    re.IGNORECASE,
)


def _legend_aliases(name: str) -> set[str]:
    raw = (name or "").strip().lower()
    compact = raw.replace(" ", "")
    if not compact:
        return set()
    from .constants import LEGEND_SLUGS
    out = {raw, compact}
    if compact in LEGEND_SLUGS:
        label = LEGEND_SLUGS[compact]
        out.add(label.lower())
        out.add(label.lower().replace(" ", ""))
    for src, label in LEGEND_SLUGS.items():
        hit = label.lower().replace(" ", "")
        if compact in {src, hit} or raw in {src, label.lower()}:
            out.add(src)
            out.add(hit)
            out.add(label.lower())
    return out


def _is_base_name(name: str) -> bool:
    return (name or "").lower() in {"original", "base", "standard", "default"}


def _is_prestige_row(extra: str, name: str) -> bool:
    e = (extra or "").lower()
    n = (name or "").lower()
    return "mythic" in e or "prestige" in e or "level0" in e or "level " in n


def _is_base_row(extra: str, name: str) -> bool:
    if _is_base_name(name):
        return True
    toks = (extra or "").lower().split("_")
    return len(toks) > 1 and toks[1] == "base"


def _is_unique_extra(extra: str) -> bool:
    e = f"_{extra or ''}_".lower()
    return any(mark in e for mark in _UNIQUE_MARKS)


def _has_recolor_tail(extra: str) -> bool:
    return bool(_RC_TAIL.search(extra or ""))


def is_finder_row(extra: str, name: str = "") -> bool:
    """Skins shown in Find Skins: named cosmetics, originals, unique meshes, rt/rc.

    A numbered common/rare/epic extra reuses the base CAST. Those rows stay
    hidden only when the display name is itself just a rarity label. Named
    skins such as Wallflower stay searchable.
    """
    if _is_base_name(name) or _is_base_row(extra, name):
        return True
    if _is_unique_extra(extra):
        return True
    if _has_recolor_tail(extra):
        return True
    if _LOW_RARITY.search(extra or ""):
        label = (name or "").strip()
        if label and not _is_base_name(label) and not _RARITY_LABEL.match(label):
            return True
        return False
    return True


_UNRELEASED: tuple[str, ...] | None = None
_SHARED: set[str] | None = None
_CAST_NOISE = frozenset(
    {
        "w",
        "v",
        "body",
        "head",
        "hair",
        "arms",
        "legs",
        "gear",
        "kit",
        "helmet",
        "suit",
        "lens",
        "gauntlet",
        "grapple",
        "hair02",
        "stubinhair",
        "stubinahair",
        "glass",
        "skin",
        "pt",
        "world",
    }
)
_NAME_STOP = frozenset(
    {"the", "and", "you", "not", "for", "with", "from", "legend", "skin", "her", "his"}
)


_UNLISTED = "_unlisted"
_UNLISTED_MARKS = frozenset({_UNLISTED, "unlisted"})


def is_unlisted_legend(legend: str = "") -> bool:
    return (legend or "").strip().lower() in _UNLISTED_MARKS


def unreleased_needles() -> tuple[str, ...]:
    """Tokens packed under the Unlisted ncache category."""
    global _UNRELEASED
    rows = load_index()
    stamp = str(len(rows))
    cached = _UNRELEASED
    if cached is not None and getattr(unreleased_needles, "_stamp", None) == stamp:
        return cached
    needles: list[str] = []
    seen: set[str] = set()
    for lg, name, extra in rows:
        if not is_unlisted_legend(lg):
            continue
        for bit in (name, extra):
            raw = (bit or "").strip().lower()
            if len(raw) < 4 or raw in seen or raw in _UNLISTED_MARKS:
                continue
            seen.add(raw)
            needles.append(raw)
    packed = tuple(needles)
    _UNRELEASED = packed
    unreleased_needles._stamp = stamp  # type: ignore[attr-defined]
    return packed


def is_unreleased(*parts: object) -> bool:
    """True when any name, path or prefix contains an Unlisted token.

    Find Skins, folder import and animation lists skip these.
    Picking a CAST file directly still imports it.
    """
    blob = " ".join(str(part or "") for part in parts).replace("\\", "/").lower()
    if not blob.strip():
        return False
    return any(needle and needle in blob for needle in unreleased_needles())


def shared_extras() -> set[str]:
    """CAST prefixes used by more than one Find Skins display name."""
    global _SHARED
    unreleased_needles()
    stamp = getattr(unreleased_needles, "_stamp", None)
    if _SHARED is not None and getattr(shared_extras, "_stamp", None) == stamp:
        return _SHARED
    groups: dict[str, set[str]] = {}
    for _lg, name, extra in load_index():
        key = (extra or "").lower()
        if not key or is_unreleased(name, extra) or not is_finder_row(extra, name):
            continue
        groups.setdefault(key, set()).add((name or "").lower())
    _SHARED = {key for key, names in groups.items() if len(names) > 1}
    shared_extras._stamp = stamp  # type: ignore[attr-defined]
    return _SHARED


def _blob_has(blob: str, needle: str) -> bool:
    token = (needle or "").lower().strip("_")
    if not token:
        return False
    hay = (blob or "").lower().strip("_")
    return f"_{token}_" in f"_{hay}_"


def _normalize_cast_stem(stem: str) -> str:
    text = (stem or "").lower()
    text = re.sub(r"^(?:body|kit|hair|gear|head|arms|legs|glass)_\d+_", "", text)
    text = re.sub(r"_lod\d+$", "", text)
    text = re.sub(r"_[vw]$", "", text)
    return text


def _stem_matches(stem: str, needle: str) -> bool:
    key = _normalize_cast_stem(stem)
    want = (needle or "").lower()
    if not key or not want:
        return False
    if key == want:
        return True
    if not key.startswith(want + "_"):
        return False
    rest = [part for part in key[len(want) + 1 :].split("_") if part]
    return bool(rest) and all(
        part in _CAST_NOISE or part.startswith("lod") or part.isdigit() for part in rest
    )


def _name_tokens(legend: str, name: str) -> list[str]:
    raw = (name or "").lower()
    parts = [part for part in re.split(r"[^a-z0-9]+", raw) if part]
    legend_bits = {part for part in re.split(r"[^a-z0-9]+", (legend or "").lower()) if part}
    stop = _NAME_STOP | legend_bits
    longs = [part for part in parts if len(part) >= 5 and part not in stop]
    if longs:
        return [max(longs, key=len)]
    mids = [part for part in parts if len(part) >= 4 and part not in stop]
    if mids:
        return mids
    compact = re.sub(r"[^a-z0-9]", "", raw)
    if len(compact) >= 4 and compact not in stop:
        return [compact]
    return [part for part in parts if len(part) >= 3 and part not in stop]


def _names_in_blob(blob: str, legend: str, name: str) -> bool:
    tokens = _name_tokens(legend, name)
    if tokens and all(_blob_has(blob, token) for token in tokens):
        return True
    compact = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return len(compact) >= 5 and (_blob_has(blob, compact) or compact in (blob or "").lower())


def _extra_anchor(extra: str) -> str:
    toks = [part for part in (extra or "").lower().split("_") if part]
    body = toks[1:] if len(toks) > 1 else toks
    longs = [part for part in body if len(part) >= 5 and not part.isdigit()]
    if longs:
        return max(longs, key=len)
    return (extra or "").lower()


def files_present(
    stems: tuple[str, ...] | list[str],
    blobs: tuple[str, ...] | list[str],
    prefix: str,
    name: str = "",
    legend: str = "",
) -> bool:
    """True only when this skin's own files are in the model folder.

    Recolors need their rt/rc code together with the mesh prefix in one texture
    path. Skins that share one CAST (Hellcat / Void Prowler) need their own
    name in a texture path. A bare shared CAST is not enough.
    """
    from .naming.tex import cast_search_prefixes, is_recolor_code, split_mesh_variant, split_recolor_prefix

    extra = (prefix or "").lower()
    if not extra:
        return False
    mesh, variant = split_mesh_variant(extra)
    base, code = split_recolor_prefix(extra)
    recolor = variant if is_recolor_code(variant) else code
    if recolor:
        prefs: list[str] = []
        for item in (mesh, base):
            item = (item or "").lower()
            if item and item != recolor and item not in prefs:
                prefs.append(item)
        for blob in blobs:
            if not _blob_has(blob, recolor):
                continue
            if any(_blob_has(blob, pref) or pref in blob for pref in prefs):
                return True
        return False
    if extra in shared_extras():
        anchor = _extra_anchor(extra)
        for blob in blobs:
            if not _names_in_blob(blob, legend, name):
                continue
            if not anchor or anchor in blob or _blob_has(blob, anchor) or extra in blob:
                return True
        needles = [item.lower() for item in cast_search_prefixes(prefix)] or [extra]
        for stem in stems:
            for needle in needles:
                if _stem_matches(stem, needle):
                    return True
        return False
    needles = [item.lower() for item in cast_search_prefixes(prefix)] or [extra]
    for stem in stems:
        for needle in needles:
            if _stem_matches(stem, needle):
                return True
    return False


_RECOLOR_BLOB = re.compile(r"(?:^|_)((?:rt|rc)\d{2}|shared0[12])(?:_|$)")
_IMAGE_EXT = {".png", ".dds", ".tga", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".bmp"}
_BLOB_INDEX: tuple | None = None
_TEX_TOKENS: tuple | None = None
_LINK_KEY = ""
_DIR_TEX: dict[str, tuple[str, ...]] = {}
_DIR_CASTS: dict[str, tuple[str, ...]] = {}
_CAST_PATHS: tuple[str, ...] = ()
_CAST_TEXT: dict[str, tuple[str, ...]] = {}
_NAME_RE = re.compile(rb"[A-Za-z][A-Za-z0-9_]{5,120}")
_DISK_TOKEN = re.compile(r"[a-z0-9]+")
_GENERIC_DIRS = frozenset(
    {
        "materials",
        "material",
        "textures",
        "texture",
        "images",
        "image",
        "png",
        "models",
        "model",
        "mdl",
        "humans",
        "human",
        "class",
        "pilot",
        "light",
        "medium",
        "heavy",
        "exported_files",
        "techart",
        "mshop",
        "characters",
        "legends",
        "skins",
        "skin",
        "lod0",
        "anims",
    }
)
_GENERIC_DISK = frozenset(
    {
        "pilot",
        "light",
        "medium",
        "heavy",
        "class",
        "lod0",
        "legendary",
        "epic",
        "rare",
        "mythic",
        "base",
        "skin",
        "skins",
        "model",
        "human",
        "humans",
    }
)
_INTERESTING = (
    "_lgnd_",
    "_mythic_",
    "_legendary_",
    "_epic_",
    "_icon_",
    "_base_",
    "_rare_",
    "albedo",
    "_col",
    "_nml",
    "_msk",
)


def rsx_character_roots(root: Path) -> list[Path]:
    """The two places RSX puts legend meshes.

    ``mdl/humans/class`` and ``mdl/techart/mshop/characters/legends``.
    Either folder the user picked still has to see the other one.
    """
    start = root if root.is_dir() else root.parent
    cur = start
    for _ in range(12):
        candidates = []
        if cur.name.lower() == "mdl":
            candidates.append(cur)
        candidates.append(cur / "mdl")
        candidates.append(cur / "exported_files" / "mdl")
        for mdl in candidates:
            if not mdl.is_dir():
                continue
            found: list[Path] = []
            class_dir = mdl / "humans" / "class"
            legends = mdl / "techart" / "mshop" / "characters" / "legends"
            if class_dir.is_dir():
                found.append(class_dir)
            if legends.is_dir():
                found.append(legends)
            if found:
                return found
        if cur.parent == cur:
            break
        cur = cur.parent
    return []


def rsx_art_legend_root(root: Path) -> Path | None:
    """Recolor PNGs: exported_files/texture/art/mshop/characters/legends."""
    start = root if root.is_dir() else root.parent
    cur = start
    rel = ("texture", "art", "mshop", "characters", "legends")
    for _ in range(12):
        for base in (cur, cur / "exported_files"):
            cand = base.joinpath(*rel)
            try:
                if cand.is_dir():
                    return cand
            except OSError:
                continue
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _path_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


_INDEX_CACHE_FILE = ".apex_model_index_cache.json"
_INDEX_CACHE_VERSION = 1


def _index_cache_path() -> Path:
    """Scan cache next to the addon. Falls back to the extension user dir."""
    here = Path(__file__).resolve().parent
    if os.access(str(here), os.W_OK):
        return here / _INDEX_CACHE_FILE
    try:
        import bpy

        return Path(bpy.utils.extension_path_user(__package__, create=True)) / _INDEX_CACHE_FILE
    except Exception:
        return here / _INDEX_CACHE_FILE


def _mtime(path: Path) -> float:
    try:
        return float(os.stat(str(path)).st_mtime)
    except OSError:
        return -1.0


def _index_signature(root: Path, limit: int) -> dict:
    """Root + mtime of the root and the priority character folders."""
    root = Path(root)
    watch = [root]
    try:
        watch += list(rsx_character_roots(root))
        art = rsx_art_legend_root(root)
        if art is not None:
            watch.append(art)
    except Exception:
        pass
    return {
        "version": _INDEX_CACHE_VERSION,
        "root": str(root),
        "limit": int(limit),
        "mtimes": {str(p): _mtime(p) for p in watch},
    }


def load_model_index_cache(root: Path, limit: int = 250000):
    """Return the packed index from disk if root/mtime still match, else None. Never walks."""
    global _LINK_KEY, _DIR_TEX, _DIR_CASTS, _CAST_PATHS, _CAST_TEXT
    import json

    path = _index_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = (data.get("roots") or {}).get(str(Path(root)))
    if not entry or entry.get("sig") != _index_signature(root, limit):
        return None
    try:
        packed = (
            tuple(entry["casts"]),
            tuple(entry["blobs"]),
            tuple(entry["tex"]),
            bool(entry["truncated"]),
            tuple(entry["cast_paths"]),
        )
        _LINK_KEY = str(Path(root))
        _DIR_TEX = {k: tuple(v) for k, v in entry["dir_tex"].items()}
        _DIR_CASTS = {k: tuple(v) for k, v in entry["dir_casts"].items()}
        _CAST_PATHS = packed[4]
        _CAST_TEXT = {}
    except (KeyError, TypeError, AttributeError):
        return None
    return packed


def save_model_index_cache(root: Path, packed, limit: int = 250000) -> None:
    import json

    path = _index_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != _INDEX_CACHE_VERSION:
            data = {}
    except (OSError, ValueError):
        data = {}
    roots = data.get("roots") if isinstance(data.get("roots"), dict) else {}
    casts, blobs, tex, truncated, cast_paths = packed
    roots[str(Path(root))] = {
        "sig": _index_signature(root, limit),
        "casts": list(casts),
        "blobs": list(blobs),
        "tex": list(tex),
        "truncated": bool(truncated),
        "cast_paths": list(cast_paths),
        "dir_tex": {k: list(v) for k, v in _DIR_TEX.items()},
        "dir_casts": {k: list(v) for k, v in _DIR_CASTS.items()},
    }
    data = {"version": _INDEX_CACHE_VERSION, "roots": roots}
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass


def cached_model_index(root: Path, force: bool = False, limit: int = 250000):
    """Disk cache first; walk only on miss or when force (\"Scan folder\")."""
    if not force:
        packed = load_model_index_cache(root, limit)
        if packed is not None:
            return packed
    packed = walk_model_index(root, limit)
    save_model_index_cache(root, packed, limit)
    return packed


def walk_model_index(root: Path, limit: int = 250000):
    """One pass over a model folder. No resolve(), so a big RSX dump stays usable.

    Returns sorted cast stems, recolor texture blobs, sorted texture stems,
    whether the walk stopped early, and LOD0 cast paths for Find Skins import.

    Also remembers which texture-set prefix sits in the same directory as a
    CAST, so a pilot slot name can be tied to the catalog skin beside it.
    """
    global _LINK_KEY, _DIR_TEX, _DIR_CASTS, _CAST_PATHS, _CAST_TEXT
    from .naming.tex import texture_set_prefix

    casts: list[str] = []
    tex: list[str] = []
    blobs: list[str] = []
    cast_paths: list[str] = []
    seen_cast: set[str] = set()
    seen_tex: set[str] = set()
    dir_tex: dict[str, set[str]] = {}
    dir_casts: dict[str, list[str]] = {}
    n = 0
    truncated = False
    root = Path(root)
    priority = rsx_character_roots(root)
    art = rsx_art_legend_root(root)
    if art is not None and all(art != item for item in priority):
        priority.append(art)

    def note_file(here: Path, name: str, count_images: bool) -> bool:
        """Record one file. Casts never use up the limit. Returns True to stop."""
        nonlocal n, truncated
        suffix = Path(name).suffix.lower()
        stem = Path(name).stem.lower()
        parent = here.name.lower()
        grand = here.parent.name.lower()
        folder_key = str(here)
        if suffix == ".cast":
            key = _normalize_cast_stem(stem)
            if key and key not in seen_cast:
                seen_cast.add(key)
                casts.append(key)
            if "lod0" in stem:
                full = str(here / name)
                cast_paths.append(full)
                dir_casts.setdefault(folder_key, []).append(full)
            return False
        if not count_images or suffix not in _IMAGE_EXT:
            return False
        n += 1
        if n > limit:
            truncated = True
            return True
        if stem not in seen_tex:
            seen_tex.add(stem)
            tex.append(stem)
        pref = texture_set_prefix(stem)
        if pref:
            dir_tex.setdefault(folder_key, set()).add(pref)
        blob = f"{stem}_{parent}_{grand}"
        if _RECOLOR_BLOB.search(blob):
            blobs.append(blob)
        return False

    def consume(start: Path, skip: list[Path], images: bool) -> None:
        nonlocal truncated
        if not start.is_dir():
            return
        if images and truncated:
            return
        for dirpath, dirnames, filenames in os.walk(start):
            here = Path(dirpath)
            if any(here == old or _path_under(here, old) for old in skip):
                dirnames[:] = []
                continue
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".")
                and name not in {"__pycache__", ".git"}
                and not any(_path_under(here / name, old) or here / name == old for old in skip)
            ]
            parent = here.name.lower()
            grand = here.parent.name.lower()
            if parent and parent not in _GENERIC_DIRS:
                label = f"{grand}_{parent}" if grand and grand not in _GENERIC_DIRS else parent
                if label not in seen_tex:
                    seen_tex.add(label)
                    tex.append(label)
            for name in filenames:
                if note_file(here, name, images):
                    break
            if images and truncated:
                break

    consume(root, [], False)
    for start in priority:
        consume(start, [], True)
    consume(root, priority, True)
    casts.sort()
    tex.sort()
    _LINK_KEY = str(root)
    _DIR_TEX = {key: tuple(sorted(val)) for key, val in dir_tex.items()}
    _DIR_CASTS = {key: tuple(val) for key, val in dir_casts.items()}
    _CAST_PATHS = tuple(cast_paths)
    _CAST_TEXT = {}
    return tuple(casts), tuple(blobs), tuple(tex), truncated, tuple(cast_paths)


def _blob_buckets(blobs: tuple[str, ...] | list[str]) -> dict[str, list[str]]:
    global _BLOB_INDEX
    if _BLOB_INDEX is not None and _BLOB_INDEX[0] is blobs:
        return _BLOB_INDEX[1]
    buckets: dict[str, list[str]] = {}
    for blob in blobs:
        found = _RECOLOR_BLOB.search(blob)
        if not found:
            continue
        buckets.setdefault(found.group(1), []).append(blob)
    _BLOB_INDEX = (blobs, buckets)
    return buckets


def _tex_token_buckets(tex: tuple[str, ...] | list[str]) -> dict[str, list[str]]:
    global _TEX_TOKENS
    if _TEX_TOKENS is not None and _TEX_TOKENS[0] is tex:
        return _TEX_TOKENS[1]
    buckets: dict[str, list[str]] = {}
    for stem in tex:
        seen: set[str] = set()
        for tok in stem.split("_"):
            if len(tok) < 4 or tok in seen:
                continue
            seen.add(tok)
            buckets.setdefault(tok, []).append(stem)
    _TEX_TOKENS = (tex, buckets)
    return buckets


def _stem_in_sorted(stems: tuple[str, ...] | list[str], needle: str) -> bool:
    want = (needle or "").lower()
    if not want or not stems:
        return False
    i = bisect.bisect_left(stems, want)
    if i < len(stems) and stems[i] == want:
        return True
    pref = want + "_"
    i = bisect.bisect_left(stems, pref)
    while i < len(stems) and stems[i].startswith(pref):
        rest = [part for part in stems[i][len(pref) :].split("_") if part]
        if rest and all(
            part in _CAST_NOISE or part.startswith("lod") or part.isdigit() for part in rest
        ):
            return True
        i += 1
    return False


def _tex_in_sorted(stems: tuple[str, ...] | list[str], needle: str) -> bool:
    want = (needle or "").lower()
    if not want or not stems:
        return False
    i = bisect.bisect_left(stems, want)
    if i < len(stems) and (stems[i] == want or stems[i].startswith(want + "_")):
        return True
    pref = want + "_"
    i = bisect.bisect_left(stems, pref)
    return i < len(stems) and stems[i].startswith(pref)


def _name_on_disk(
    stems: tuple[str, ...] | list[str],
    legend: str,
    name: str,
) -> bool:
    """True when a file or its folder carries this skin's name and legend."""
    tokens = [tok for tok in _name_tokens(legend, name) if len(tok) >= 5]
    if not tokens:
        return False
    slug = re.sub(r"[^a-z0-9]", "", (legend or "").lower())
    if len(slug) < 3:
        return False
    buckets = _tex_token_buckets(stems)
    pool: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        for stem in buckets.get(tok, ()):
            if stem in seen:
                continue
            seen.add(stem)
            pool.append(stem)
    for stem in pool:
        if slug not in stem.split("_"):
            continue
        if _names_in_blob(stem, legend, name):
            return True
    return False


def files_present_indexed(
    casts: tuple[str, ...] | list[str],
    blobs: tuple[str, ...] | list[str],
    tex: tuple[str, ...] | list[str],
    prefix: str,
    name: str = "",
    legend: str = "",
) -> bool:
    """Same rules as files_present, but cast/texture stems are pre-sorted."""
    from .naming.tex import cast_search_prefixes, is_recolor_code, split_mesh_variant, split_recolor_prefix

    extra = (prefix or "").lower()
    if not extra:
        return False
    mesh, variant = split_mesh_variant(extra)
    base, code = split_recolor_prefix(extra)
    recolor = variant if is_recolor_code(variant) else code
    if recolor:
        prefs: list[str] = []
        for item in (mesh, base):
            item = (item or "").lower()
            if item and item != recolor and item not in prefs:
                prefs.append(item)
        pool = _blob_buckets(blobs).get(recolor, blobs)
        for blob in pool:
            if not _blob_has(blob, recolor):
                continue
            if any(_blob_has(blob, pref) or pref in blob for pref in prefs):
                return True
        # The recolor's own name. The parent mesh alone is not this skin.
        own = [extra]
        low = extra.lower()
        if "_epicp_" in low:
            own.append(low.replace("_epicp_", "_epic_"))
        elif "_epic_" in low:
            own.append(low.replace("_epic_", "_epicp_"))
        for needle in own:
            if _stem_in_sorted(casts, needle) or _tex_in_sorted(tex, needle):
                return True
        if _name_on_disk(tex, legend, name) or _name_on_disk(casts, legend, name):
            return True
        return False
    if extra in shared_extras():
        anchor = _extra_anchor(extra)
        tokens = _name_tokens(legend, name)
        pool: tuple[str, ...] | list[str] = tex
        if tokens and len(tokens[0]) >= 4:
            pool = _tex_token_buckets(tex).get(tokens[0], ())
        for stem in pool:
            if not _names_in_blob(stem, legend, name):
                continue
            if not anchor or anchor in stem or _blob_has(stem, anchor) or extra in stem:
                return True
        needles = [item.lower() for item in cast_search_prefixes(prefix)] or [extra]
        for needle in needles:
            if _stem_in_sorted(casts, needle) or _tex_in_sorted(tex, needle):
                return True
        return False
    needles = [item.lower() for item in cast_search_prefixes(prefix)] or [extra]
    for needle in needles:
        if _stem_in_sorted(casts, needle) or _tex_in_sorted(tex, needle):
            return True
    if _name_on_disk(tex, legend, name) or _name_on_disk(casts, legend, name):
        return True
    return False


def skin_already_imported(
    legend: str,
    name: str,
    needle: str,
    tagged: list[tuple[str, str, str]],
) -> bool:
    """tagged rows are (CHAR_TAG, CHAR_RECOLOR, object name)."""
    from .naming.tex import with_recolor_prefix

    want_l = (legend or "").strip().lower()
    want_n = (name or "").strip().lower()
    low_needle = (needle or "").strip().lower()
    if not want_n:
        return False
    shared = low_needle in shared_extras() if low_needle else False
    for tag, rec, obj_name in tagged:
        tag_l = (tag or "").lower()
        rec_l = (rec or "").lower()
        combined = with_recolor_prefix(tag_l, rec_l).lower() if rec_l else tag_l
        if low_needle and low_needle in {tag_l, combined}:
            if not shared:
                return True
            blob = f"{tag_l}_{obj_name}_{rec_l}"
            if _names_in_blob(blob, legend, name):
                return True
            continue
        hit = match_source(combined) or match_source(tag_l)
        if hit is None:
            continue
        if (hit[2] or "").lower() in shared_extras():
            continue
        if hit[0].lower() == want_l and hit[1].lower() == want_n:
            return True
    return False


def _row_blob(lg: str, name: str, extra: str) -> str:
    return f"{lg} {name} {extra}".lower()


def _rank_hit(row: tuple[str, str, str], q: str, tokens: list[str]) -> tuple:
    lg, name, extra = row
    nl, ll, el = name.lower(), lg.lower(), (extra or "").lower()
    exact = nl == q
    start_n = nl.startswith(q)
    in_n = q in nl
    start_e = el.startswith(q)
    in_e = q in el
    in_l = q in ll or ll.startswith(q)
    token_n = all(t in nl for t in tokens) if tokens else False
    unique = _is_unique_extra(extra)
    base = (not unique) and _is_base_row(extra, name) and not _is_base_name(name)
    return (
        1 if exact else 0,
        1 if start_n else 0,
        1 if in_n else 0,
        1 if token_n else 0,
        1 if start_e else 0,
        1 if in_e else 0,
        1 if unique else 0,
        0 if base else 1,
        1 if in_l else 0,
        -len(nl),
    )


def _interesting_name(text: str) -> bool:
    return any(mark in text for mark in _INTERESTING)


def _cast_text_names(path: str) -> tuple[str, ...]:
    """ASCII tokens inside one CAST. Cached. Used to map a codename to a skin."""
    cached = _CAST_TEXT.get(path)
    if cached is not None:
        return cached
    found: list[str] = []
    seen: set[str] = set()
    try:
        with open(path, "rb") as handle:
            prev = b""
            while len(found) < 80:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                data = prev + chunk
                for match in _NAME_RE.finditer(data):
                    text = match.group(0).decode("ascii", "ignore").lower()
                    if text in seen or "_" not in text or not _interesting_name(text):
                        continue
                    seen.add(text)
                    found.append(text)
                    if len(found) >= 80:
                        break
                prev = data[-140:]
    except OSError:
        found = []
    out = tuple(found)
    _CAST_TEXT[path] = out
    return out


def _rows_from_names(names: tuple[str, ...] | list[str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for text in names:
        hit = match_source(text)
        if hit is None:
            continue
        key = (hit[0].lower(), hit[1].lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append(hit)
    return rows


def _disk_query_tokens(query: str) -> list[str]:
    """Codename pieces. Three letters are enough (cyb → cyber)."""
    tokens = [tok for tok in _DISK_TOKEN.findall((query or "").lower()) if len(tok) >= 3]
    if not tokens:
        return []
    from .naming.tex import is_canon_legend_slug

    return [tok for tok in tokens if tok not in _GENERIC_DISK and not is_canon_legend_slug(tok)]


def _cast_name_hit(tokens: list[str], parts: set[str]) -> bool:
    """Exact token, or a prefix of a non-generic token (cyb → cyber, nin → ninja)."""
    if not tokens or not parts:
        return False
    useful = [part for part in parts if part not in _GENERIC_DISK and len(part) >= 3]
    if not useful:
        return False
    for tok in tokens:
        if not any(part == tok or part.startswith(tok) for part in useful):
            return False
    return True


def _disk_reverse(query: str, legend: str) -> list[tuple[str, str, str]]:
    """Model-folder codenames (cyber_ninja, or cyb / nin) → catalog rows (Voidwalker)."""
    tokens = _disk_query_tokens(query)
    if not tokens or not _CAST_PATHS:
        return []
    want = _legend_filter(legend) if legend else ""
    # search_index passes an already-lowered legend; _legend_filter accepts both.
    if legend and legend.lower() not in {"", "all"} and not want:
        want = legend.lower()
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    parsed = 0
    for path in _CAST_PATHS:
        parts = set(_DISK_TOKEN.findall(f"{Path(path).stem} {Path(path).parent.name}".lower()))
        if not _cast_name_hit(tokens, parts):
            continue
        directory = str(Path(path).parent)
        prefs = _DIR_TEX.get(directory, ())
        hits = _rows_from_names(prefs) if prefs and len(prefs) <= 4 else []
        if not hits and parsed < 4:
            parsed += 1
            hits = _rows_from_names(_cast_text_names(path))
        for hit in hits:
            lg, name, extra = hit
            if is_unlisted_legend(lg) or is_unreleased(name, extra) or not is_finder_row(extra, name):
                continue
            if want and not _legend_matches(lg, want):
                continue
            key = (lg.lower(), name.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(hit)
        if len(rows) >= 8:
            break
    return rows


def _file_contains(path: str, needle: bytes) -> bool:
    if len(needle) < 6:
        return False
    try:
        with open(path, "rb") as handle:
            prev = b""
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    return False
                if needle in prev + chunk:
                    return True
                prev = chunk[-len(needle) :]
    except OSError:
        return False


def rank_cast_for_prefix(prefix: str, paths: list[str] | tuple[str, ...]) -> str:
    """LOD0 CAST a Find Skins row should import.

    An epic palette or rt/rc recolor has no mesh of its own. Prefer a CAST
    whose name is the skin, then the mesh that skin borrows (legendary
    without the recolor code, or the legend base for common/rare/epic).
    """
    from .naming.tex import cast_search_prefixes

    needles = [item.lower() for item in cast_search_prefixes(prefix) if item]
    if not needles and prefix:
        needles = [prefix.lower()]
    best = ""
    best_key: tuple | None = None
    for raw in paths:
        stem = Path(str(raw)).stem.lower()
        if not stem:
            continue
        norm = _normalize_cast_stem(stem)
        for rank, needle in enumerate(needles):
            if not needle:
                continue
            exact = norm == needle or _stem_matches(stem, needle)
            borrowed = (not exact) and (
                needle.endswith("_base") or needle == "base"
            ) and needle in stem
            if not exact and not borrowed:
                # Unique skin token (voidsinister) still names the mesh when
                # the catalog rarity token does not match the file.
                skin = needle.split("_")[-1]
                if len(skin) >= 6 and skin in stem and needle.split("_", 1)[0] in stem:
                    exact = False
                    borrowed = True
                else:
                    continue
            lod = 0 if "lod0" in stem else 1
            key = (rank, 0 if exact else 1, lod, len(stem))
            if best_key is None or key < best_key:
                best_key = key
                best = str(raw)
    return best


def texture_dir_for_prefix(prefix: str) -> str:
    """Directory whose textures are this skin, from the last model-folder walk."""
    want = (prefix or "").lower()
    if not want:
        return ""
    for directory, prefs in _DIR_TEX.items():
        if want in prefs:
            return directory
    return ""


def cast_beside_prefix(prefix: str) -> str:
    """CAST sitting next to this skin's textures, when the skin has no own mesh."""
    directory = texture_dir_for_prefix(prefix)
    if not directory:
        return ""
    found: list[str] = []
    cur = Path(directory)
    for _ in range(8):
        found.extend(_DIR_CASTS.get(str(cur), ()))
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    ranked = rank_cast_for_prefix(prefix, found)
    if ranked:
        return ranked
    cur = Path(directory)
    for _ in range(8):
        casts = list(_DIR_CASTS.get(str(cur), ()))
        base = [item for item in casts if "_base" in Path(item).stem.lower()]
        if len(base) == 1:
            return base[0]
        if len(casts) == 1:
            return casts[0]
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return ""


def casts_for_skin(prefix: str, cast_paths: list[str] | tuple[str, ...] = ()) -> list[str]:
    """LOD0 CAST for a catalog prefix, even when the file is a pilot codename."""
    needle = (prefix or "").strip().lower()
    if not needle:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if path and path not in seen:
            seen.add(path)
            found.append(path)

    for directory, prefs in _DIR_TEX.items():
        if needle not in prefs or len(prefs) > 4:
            continue
        for cast in _DIR_CASTS.get(directory, ()):
            add(cast)
    if found:
        return found
    pool = list(cast_paths) or list(_CAST_PATHS)
    legend = needle.split("_", 1)[0]
    candidates = [
        path
        for path in pool
        if legend and legend in Path(path).name.lower()
    ] or list(pool)
    raw = needle.encode("ascii", "ignore")

    def sort_key(path: str) -> tuple:
        hit = match_source(path)
        other = 1 if hit and (hit[2] or "").lower() not in {needle, ""} else 0
        return (other, len(Path(path).name))

    candidates.sort(key=sort_key)
    for path in candidates:
        names = _CAST_TEXT.get(path)
        if names is not None and any(needle in item or needle in (match_source(item) or ("", "", ""))[2].lower() for item in names):
            add(path)
            return found
        if _file_contains(path, raw):
            add(path)
            return found
    return found


def search_index(query: str, legend: str = "") -> list[tuple[str, str, str]]:
    q = (query or "").strip().lower()
    want = (legend or "").strip()
    if want.lower() in {"", "all"}:
        want = ""
    else:
        want = want.lower()
    tokens = [t for t in q.replace("-", " ").replace("_", " ").split() if t]
    q_prestige = any(t in _PRESTIGE_WORDS for t in tokens)
    q_base = any(t in _BASE_WORDS for t in tokens)
    rest = [t for t in tokens if t not in _PRESTIGE_WORDS and t not in _BASE_WORDS]
    rest_s = " ".join(rest)
    want_set = _legend_aliases(want) if want else set()
    hits: list[tuple[str, str, str]] = []
    browse = not q
    for lg, name, extra in load_index():
        if is_unlisted_legend(lg) or is_unreleased(name, extra) or not is_finder_row(extra, name):
            continue
        ll = lg.lower()
        compact = ll.replace(" ", "")
        if want_set and compact not in want_set and ll not in want_set:
            continue
        if browse:
            hits.append((lg, name, extra))
            continue
        nl = name.lower()
        el = (extra or "").lower()
        blob = _row_blob(lg, name, extra)
        row = (lg, name, extra)
        generic = True
        if q_base and not rest_s and not _is_base_name(name):
            generic = False
        if q_prestige and not rest_s and not _is_prestige_row(extra, name):
            generic = False
        alias_hit = compact in _legend_aliases(q) and q not in {compact, ll}
        token_hit = bool(tokens) and all(t in blob for t in tokens)
        extra_hit = q in el or any(t in el for t in tokens)
        name_words = nl.replace("-", " ").split()
        word_hit = any(w.startswith(q) for w in name_words)
        matched = generic and (
            q in nl or q in ll or q in el or alias_hit or token_hit or extra_hit or word_hit
        )
        if not matched:
            if q_prestige and _is_prestige_row(extra, name):
                if not rest_s or rest_s in blob or all(t in blob for t in rest):
                    matched = True
            elif q_base and _is_base_name(name):
                if not rest_s or rest_s in blob or all(t in blob for t in rest):
                    matched = True
        if matched:
            hits.append(row)
    if browse:
        hits.sort(key=lambda row: (row[0].lower(), row[1].lower()))
    else:
        hits.sort(key=lambda row: _rank_hit(row, q, tokens), reverse=True)
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    cap = _BROWSE_CAP if browse else _CAP
    for row in hits:
        key = (row[0].lower(), row[1].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= cap:
            break
    if q:
        extra: list[tuple[str, str, str]] = []
        for row in _disk_reverse(q, want):
            key = (row[0].lower(), row[1].lower())
            if key in seen:
                continue
            seen.add(key)
            extra.append(row)
        if extra:
            out = (extra + out)[:cap]
    return out


def _legend_filter(legend: str) -> str:
    want = (legend or "").strip()
    if want.lower() in {"", "all"}:
        return ""
    return want.lower()


def _legend_matches(lg: str, want: str) -> bool:
    if not want:
        return True
    aliases = _legend_aliases(want)
    low = (lg or "").lower()
    return low in aliases or low.replace(" ", "") in aliases


def suggest_names(query: str, legend: str = "") -> list[str]:
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    want = _legend_filter(legend)
    starts: list[str] = []
    contains: list[str] = []
    extras: list[str] = []
    seen: set[str] = set()
    for lg, name, extra in load_index():
        if is_unlisted_legend(lg) or is_unreleased(name, extra) or not is_finder_row(extra, name):
            continue
        if not _legend_matches(lg, want):
            continue
        nl = name.lower()
        el = (extra or "").lower()
        if name in seen or nl == q:
            continue
        if nl.startswith(q):
            seen.add(name)
            starts.append(name)
        elif any(part.startswith(q) for part in nl.replace("-", " ").split()):
            seen.add(name)
            contains.append(name)
        elif q in nl:
            seen.add(name)
            contains.append(name)
        elif len(q) >= 3 and q in el:
            seen.add(name)
            extras.append(name)
        if len(starts) >= 8:
            break
    catalog = starts + contains + extras
    disk = [name for _lg, name, _extra in _disk_reverse(q, want) if name not in seen]
    return (disk + catalog)[:8]


def did_you_mean(query: str, legend: str = "") -> list[str]:
    q = (query or "").strip()
    if len(q) < 4:
        return []
    low = q.lower()
    if suggest_names(q, legend):
        return []
    want = _legend_filter(legend)
    names: list[str] = []
    seen: set[str] = set()
    for lg, name, extra in load_index():
        if is_unlisted_legend(lg) or is_unreleased(name, extra) or not is_finder_row(extra, name):
            continue
        if not _legend_matches(lg, want):
            continue
        if name.lower() == low:
            return []
        if name not in seen:
            seen.add(name)
            names.append(name)
    return difflib.get_close_matches(q, names, n=3, cutoff=0.62)


def prefix_for(legend: str, name: str) -> str:
    want_l = (legend or "").strip().lower()
    want_n = (name or "").strip().lower()
    if not want_l or not want_n:
        return ""
    for lg, nm, extra in load_index():
        if is_unlisted_legend(lg):
            continue
        if _legend_matches(lg, want_l) and nm.lower() == want_n:
            return extra
    return ""


def legend_names() -> list[str]:
    got: set[str] = set()
    for lg, _name, _extra in load_index():
        if lg and not is_unlisted_legend(lg):
            got.add(lg)
    return sorted(got, key=str.lower)


_PREFIX_BUCKETS: tuple | None = None


def _prefix_buckets() -> dict[str, list[tuple[int, str, tuple[str, str, str]]]]:
    global _PREFIX_BUCKETS
    rows = load_index()
    if _PREFIX_BUCKETS is not None and _PREFIX_BUCKETS[0] is rows:
        return _PREFIX_BUCKETS[1]
    buckets: dict[str, list[tuple[int, str, tuple[str, str, str]]]] = {}
    for idx, (lg, name, extra) in enumerate(rows):
        if is_unlisted_legend(lg):
            continue
        pref = (extra or "").lower()
        if not pref:
            continue
        token = pref.split("_", 1)[0]
        buckets.setdefault(token, []).append((idx, pref, (lg, name, extra)))
    _PREFIX_BUCKETS = (rows, buckets)
    return buckets


def match_source(text: str) -> tuple[str, str, str] | None:
    raw = str(text or "").replace("\\", "/").lower()
    stem = Path(raw).stem.lower()
    parent = Path(raw).parent.name.lower()
    blob = f"{stem} {Path(raw).name.lower()} {parent}"
    tokens = {part for part in re.split(r"[^a-z0-9]+", blob) if part}
    buckets = _prefix_buckets()
    found: list[tuple[int, str, tuple[str, str, str]]] = []
    for token in tokens:
        found.extend(buckets.get(token, ()))
    found.sort(key=lambda item: item[0])
    best: tuple[str, str, str] | None = None
    best_n = 0
    best_orig = -1
    seen: set[int] = set()
    for idx, pref, row in found:
        if idx in seen or pref not in blob:
            continue
        seen.add(idx)
        n = len(pref)
        orig = 1 if (row[1] or "").lower() in {"original", "base", "standard"} else 0
        if n > best_n or (n == best_n and orig > best_orig):
            best = row
            best_n = n
            best_orig = orig
    return best
