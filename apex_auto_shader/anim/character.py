from __future__ import annotations

from pathlib import Path

import bpy

from .const import CHAR_VICTIM, IMPORT_GAP, MODEL_EULER
from ..blender_compat import ignore_rna, resolve_armature
from ..log import existing_file
from ..naming import (
    LEVEL_CODES,
    collect_lod0_casts,
    cycled_level_name,
    file_variant,
    find_cycled_cast,
    find_texture_folder,
    prefer_world_lod0,
    strip_blender_suffix,
    unique_skin_casts,
)
from ..prefs import cast_importer_available, model_scale


def remember_character(arm: bpy.types.Object | None) -> None:
    if arm is None:
        return
    try:
        bpy.context.scene.apex_character = arm.name
    except (AttributeError, RuntimeError) as exc:
        ignore_rna(exc, "remember_character")


def resolve_character(context) -> bpy.types.Object | None:
    arm = resolve_armature(context.active_object)
    if arm is not None:
        remember_character(arm)
        return arm
    for obj in list(context.selected_objects):
        arm = resolve_armature(obj)
        if arm is not None:
            remember_character(arm)
            return arm
    name = getattr(context.scene, "apex_character", "") or ""
    if name and name in bpy.data.objects:
        arm = resolve_armature(bpy.data.objects[name])
        if arm is not None:
            return arm
        if bpy.data.objects[name].type == "ARMATURE":
            return bpy.data.objects[name]
    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and not obj.get(CHAR_VICTIM):
            return obj
    return None


def resolve_shade_objects(context) -> list:
    objs = [
        o
        for o in list(context.selected_objects)
        if o is not None and o.type in {"ARMATURE", "MESH"}
    ]
    active = context.active_object
    if not objs and active is not None and active.type in {"ARMATURE", "MESH"}:
        objs = [active]
    if not objs:
        char = resolve_character(context)
        if char is not None:
            objs = [char]
    return objs


def import_cast_model(context, filepath: str):
    if not cast_importer_available():
        raise RuntimeError(
            "CAST importer not found. Install dtzxporter/cast, then restart Blender."
        )
    path = existing_file(filepath)
    if path is None:
        raise RuntimeError(f"CAST file not found: {filepath}")
    before_objects = set(bpy.data.objects.keys())
    before_cols = set(bpy.data.collections.keys())
    bpy.ops.import_scene.cast("EXEC_DEFAULT", filepath=str(path))
    imported = [
        bpy.data.objects[name]
        for name in bpy.data.objects.keys()
        if name not in before_objects
    ]
    arm = None
    for obj in imported:
        if obj.type == "ARMATURE":
            arm = obj
            break
    if arm is None:
        arm = resolve_character(context)
    folder = find_texture_folder(path)
    new_cols = [name for name in bpy.data.collections.keys() if name not in before_cols]
    try:
        context.scene.apex_cast_path = str(path)
        context.scene.apex_cast_collection = "|".join(new_cols)
    except Exception:
        pass
    if folder is not None:
        try:
            context.scene.apex_texture_dir = str(folder)
        except Exception:
            pass
    from ..extras import tag_character

    if arm is not None:
        remember_character(arm)
        tag_character(arm, folder=folder, cast_path=path, collection="|".join(new_cols))
    return arm, folder


def _index_extras() -> set[str]:
    try:
        from .. import pack

        extras = set()
        for lg, name, extra in pack.load_index():
            key = (extra or "").lower()
            if not key:
                continue
            if pack.is_unlisted_legend(lg) or pack.is_unreleased(lg, name, extra):
                continue
            extras.add(key)
        return extras
    except Exception:
        return set()


def _cast_in_index(path: Path, extras: set[str]) -> bool:
    """True when this CAST maps to a skin already stored in the on-disk index."""
    if not extras:
        return True
    from .. import pack

    hit = pack.match_source(str(path))
    if hit is not None:
        return True
    stem = path.stem.lower()
    parent = path.parent.name.lower()
    for extra in extras:
        if extra and extra in stem:
            return True
        if extra and extra in parent:
            return True
    return False


def _gather_import_casts(directory: str, filepath: str, files) -> list[Path]:
    root = Path(bpy.path.abspath(directory or filepath or ""))
    selected: list[Path] = []
    if files:
        for entry in files:
            name = getattr(entry, "name", "") or ""
            if not name:
                continue
            if root.is_dir():
                selected.append(root / name)
            else:
                selected.append(Path(bpy.path.abspath(name)))
    casts: list[Path] = []
    dirs: list[Path] = []
    for path in selected:
        if path.is_dir():
            dirs.append(path)
        elif path.is_file() and path.suffix.lower() == ".cast":
            casts.append(path)
    if casts:
        # Direct file pick: keep leaked / unreleased extracts and still shade them.
        return unique_skin_casts(prefer_world_lod0(casts, root if root.is_dir() else None))
    scan = dirs or ([root] if root.is_dir() else [])
    if not scan and filepath:
        current = Path(bpy.path.abspath(filepath))
        scan = [current if current.is_dir() else current.parent]
    found: list[Path] = []
    seen: set[str] = set()
    extras = _index_extras()
    for folder in scan:
        for path in collect_lod0_casts(folder):
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if extras and not _cast_in_index(path, extras):
                continue
            try:
                from .. import pack as _pack

                if _pack.is_unreleased(path, path.stem, path.parent.name):
                    continue
                hit = _pack.match_source(str(path))
                if hit is not None and _pack.is_unreleased(*hit):
                    continue
            except Exception:
                pass
            found.append(path)
    return found


def next_import_x(context) -> float:
    xs = []
    scene = getattr(context, "scene", None)
    pool = list(getattr(scene, "objects", [])) if scene is not None else list(bpy.data.objects)
    for obj in pool:
        if getattr(obj, "type", "") != "ARMATURE":
            continue
        if obj.get(CHAR_VICTIM):
            continue
        try:
            xs.append(float(obj.location.x))
        except Exception:
            continue
    if not xs:
        return 0.0
    return round(max(xs) + IMPORT_GAP, 4)


def place_imported_character(arm, x: float) -> None:
    if arm is None:
        return
    loc = arm.location.copy()
    loc.x = x
    arm.location = loc


def character_level(context) -> str:
    sources: list[str] = []
    stored = getattr(context.scene, "apex_cast_path", "") or ""
    if stored:
        path = Path(bpy.path.abspath(stored))
        sources.extend([path.name, path.parent.name])
    arm = resolve_character(context)
    if arm is not None:
        sources.append(arm.name)
        tagged = arm.get("apex_cast_path") or ""
        if tagged:
            path = Path(str(tagged))
            sources.extend([path.name, path.parent.name])
    for src in sources:
        level = file_variant(src)
        if level in LEVEL_CODES:
            return level
    return ""


def character_has_level(context) -> bool:
    return bool(character_level(context))


def upgrade_button_label(context) -> str:
    return "Downgrade" if character_level(context) == "level03" else "Upgrade"


def _cast_search_dirs(context, current: Path | None) -> list[Path]:
    dirs: list[Path] = []
    if current is not None:
        dirs.extend([current.parent, current.parent.parent, current.parent.parent.parent])
    tex = getattr(context.scene, "apex_texture_dir", "") or ""
    if tex:
        folder = Path(bpy.path.abspath(tex))
        dirs.extend([folder, folder.parent, folder.parent.parent])
    seen = set()
    out = []
    for d in dirs:
        key = str(d)
        if key in seen or not d.is_dir():
            continue
        seen.add(key)
        out.append(d)
    return out


def current_cast_path(context, arm: bpy.types.Object | None) -> Path | None:
    stored = getattr(context.scene, "apex_cast_path", "") or ""
    if stored:
        path = Path(bpy.path.abspath(stored))
        if path.is_file():
            return path
    stem = strip_blender_suffix(arm.name) if arm is not None else ""
    if not stem:
        return None
    fname = stem if stem.lower().endswith(".cast") else f"{stem}.cast"
    for folder in _cast_search_dirs(context, Path(stored) if stored else None):
        hit = folder / fname
        if hit.is_file():
            return hit
    return None


def next_cast_path(context, arm: bpy.types.Object | None) -> Path | None:
    current = current_cast_path(context, arm)
    extra = _cast_search_dirs(context, current)
    if current is not None and current.is_file():
        hit = find_cycled_cast(current, extra)
        if hit is not None:
            return hit
    source = current.name if current is not None else (arm.name if arm is not None else "")
    nxt = cycled_level_name(source)
    if not nxt:
        parent = current.parent.name if current is not None else ""
        nxt = cycled_level_name(parent)
    if not nxt:
        return None
    if not nxt.lower().endswith(".cast"):
        nxt = f"{nxt}.cast"
    if current is not None:
        candidate = current.with_name(nxt)
        if candidate.is_file():
            return candidate
    for folder in extra:
        hit = folder / nxt
        if hit.is_file():
            return hit
        for path in folder.rglob(nxt):
            if path.is_file():
                return path
    return None


def _is_scene_collection(col) -> bool:
    if col is None:
        return True
    scene = getattr(bpy.context, "scene", None)
    if scene is not None and col == scene.collection:
        return True
    return col.name in {"Scene Collection", "Master Collection"}


def _purge_collection(col) -> None:
    if col is None or _is_scene_collection(col):
        return
    for child in list(col.children):
        _purge_collection(child)
    for obj in list(col.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.data.collections.remove(col)
    except Exception:
        pass


def _character_collections(arm: bpy.types.Object) -> list:
    found = []
    seen = set()
    names = {arm.name, strip_blender_suffix(arm.name)}
    stored = getattr(bpy.context.scene, "apex_cast_collection", "") or ""
    for part in stored.split("|"):
        if part:
            names.add(part)
    for col in list(bpy.data.collections):
        if col.name in names and not _is_scene_collection(col):
            found.append(col)
            seen.add(col.name)
    for col in list(arm.users_collection):
        if col.name in seen or _is_scene_collection(col):
            continue
        found.append(col)
        seen.add(col.name)
    return found


def delete_character(arm: bpy.types.Object) -> None:
    cols = _character_collections(arm)
    extra = []
    try:
        extra.append(arm)
        children = getattr(arm, "children_recursive", None)
        if children is not None:
            extra.extend(list(children))
        for obj in list(bpy.data.objects):
            try:
                if obj.find_armature() == arm:
                    extra.append(obj)
            except Exception:
                pass
    except ReferenceError:
        extra = []
    for col in cols:
        _purge_collection(col)
    seen = set()
    for obj in extra:
        try:
            name = obj.name
        except ReferenceError:
            continue
        if name in seen:
            continue
        seen.add(name)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.context.scene.apex_cast_collection = ""
    except Exception:
        pass


def upgrade_character(context):
    arm = resolve_character(context)
    nxt = next_cast_path(context, arm)
    if nxt is None:
        raise RuntimeError("No next-level CAST file found next to this model")
    if arm is not None:
        delete_character(arm)
    imported, folder = import_cast_model(context, str(nxt))
    if imported is None:
        raise RuntimeError(f"Imported {nxt.name}, but no armature was found")
    from ..node_adder import current_node_adder
    from .. import utils

    reports = utils.shade_selected([imported], current_node_adder(context.scene), folder=folder)
    from ..extras import purge_orphans, tag_character

    tag_character(imported, folder=folder, cast_path=nxt)
    purge_orphans()
    return imported, nxt, reports


def apply_model_size(obj: bpy.types.Object) -> bpy.types.Object:
    """Scale the armature and keep XYZ Euler at 0 degrees. Never touches mesh objects."""
    target = resolve_armature(obj) or obj
    scale = model_scale()
    target.scale = (scale, scale, scale)
    target.rotation_mode = "XYZ"
    target.rotation_euler = MODEL_EULER
    remember_character(target if target.type == "ARMATURE" else resolve_armature(target))
    return target
