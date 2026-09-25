from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
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
    """Skins shown in Find Skins: originals, unique meshes, rt/rc families.

    Numbered Common/Rare/Epic and event palettes reuse the base CAST and live
    in shared camo folders. Those stay in ncache for match_source, but they
    are hidden from search until a real texture map exists.
    """
    if _is_base_name(name) or _is_base_row(extra, name):
        return True
    if _is_unique_extra(extra):
        return True
    if _has_recolor_tail(extra):
        return True
    if _LOW_RARITY.search(extra or ""):
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
        return False
    needles = [item.lower() for item in cast_search_prefixes(prefix)] or [extra]
    for stem in stems:
        for needle in needles:
            if _stem_matches(stem, needle):
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
    return (starts + contains + extras)[:8]


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


def match_source(text: str) -> tuple[str, str, str] | None:
    raw = str(text or "").replace("\\", "/").lower()
    stem = Path(raw).stem.lower()
    blob = f"{stem} {Path(raw).name.lower()}"
    best: tuple[str, str, str] | None = None
    best_n = 0
    best_orig = -1
    for lg, name, extra in load_index():
        if is_unlisted_legend(lg):
            continue
        pref = (extra or "").lower()
        if not pref or pref not in blob:
            continue
        n = len(pref)
        orig = 1 if (name or "").lower() in {"original", "base", "standard"} else 0
        if n > best_n or (n == best_n and orig > best_orig):
            best = (lg, name, extra)
            best_n = n
            best_orig = orig
    return best
