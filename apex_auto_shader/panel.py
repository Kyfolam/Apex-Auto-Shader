from __future__ import annotations

import os
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty

from . import anim, extras, pack, prop as propmod, utils
from .config import ADDON_VERSION_STR
from .naming import RARITY_ORDER, character_bucket, legend_display_name, parse_skin_identity
from .node_adder import (
    apex_shader_get,
    apex_shader_set,
    current_node_adder,
    on_apex_shader_update,
    sync_unset_scenes,
)
from .prefs import SHADER_ITEMS, anim_loop_default, cast_importer_available


def _fold_set(scene, attr: str) -> set[str]:
    raw = getattr(scene, attr, "") or ""
    return {part for part in raw.split("|") if part}


def char_group_collapsed(scene, key: str, default_collapsed: bool) -> bool:
    expanded = _fold_set(scene, "apex_char_expanded")
    collapsed = _fold_set(scene, "apex_char_collapsed")
    if key in expanded:
        return False
    if key in collapsed:
        return True
    return default_collapsed


def _report_shade(operator, reports, scene=None):
    from .constants import SLOT_SHORT
    from .extras import store_status

    ok = sum(1 for r in reports if r.get("wired"))
    hidden = sum(1 for r in reports if r.get("hidden"))
    fail = sum(1 for r in reports if r.get("error"))
    parts = [f"Shaded {ok} mesh(es)"]
    if hidden:
        parts.append(f"{hidden} hidden")
    if fail:
        parts.append(f"{fail} skipped")
    missing_bits = []
    for r in reports or []:
        miss = r.get("missing") or []
        if not miss:
            continue
        bp = r.get("bodypart") or r.get("mesh") or "?"
        shorts = [SLOT_SHORT.get(s, s) for s in miss]
        missing_bits.append(f"{bp} {', '.join(shorts)}")
    if missing_bits:
        parts.append("Missing: " + "; ".join(missing_bits[:6]))
    for r in reports or []:
        if r.get("error"):
            operator.report({"WARNING"}, f"Skipped {r.get('mesh', '?')}: {r['error']}")
    msg = ", ".join(parts)
    operator.report({"INFO"}, msg)
    if scene is not None:
        store_status(scene, reports)


def _update_anim_dir(self, context):
    from .prefs import anim_folder_pref

    global _ANIM_LOCK_HOLD
    raw = getattr(self, "apex_anim_dir", "") or ""
    locked = anim_folder_pref()
    if locked is not None:
        locked_text = str(locked)
        try:
            same = Path(bpy.path.abspath(raw)).resolve() == locked.resolve()
        except Exception:
            same = str(raw) == locked_text
        if not same:
            if _ANIM_LOCK_HOLD:
                return
            _ANIM_LOCK_HOLD = True
            try:
                self.apex_anim_dir = locked_text
            finally:
                _ANIM_LOCK_HOLD = False
            raw = locked_text
    if not raw:
        self.apex_anim_items.clear()
        return
    folder = Path(bpy.path.abspath(raw))
    if folder.is_dir():
        anim.fill_animation_list(self, folder)


_INDEX_CACHE: tuple | None = None
_FIND_HOLD = False
_ANIM_LOCK_HOLD = False
_PRESENT_KEY = ""
_PRESENT_MEMO: dict[tuple[str, str, str], bool] = {}


def _model_root(scene) -> Path | None:
    from .log import existing_dir
    from .prefs import model_folder_pref

    locked = model_folder_pref()
    if locked is not None:
        return locked
    return existing_dir(getattr(scene, "apex_model_dir", "") or "")


def _broad_dir(path: Path) -> bool:
    """Home, Downloads and drive roots are not model folders. Do not walk them."""
    try:
        if path.parent == path or len(path.parts) <= 1:
            return True
    except Exception:
        return True
    home = Path.home()
    broad = {home, home / "Downloads", home / "Desktop", home / "Documents"}
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return resolved in broad or path in broad


_SCAN_ALLOWED = False  # set by "Scan folder" / first open of Find Skins


def _model_index(scene, scan: bool | None = None, force: bool = False):
    """Folder index for presence checks.

    Lazy: memory cache, then disk cache. A folder walk only happens when a scan
    is allowed ("Scan folder" or first open of Find Skins). Returns None when
    no index is available yet and scanning is not allowed.
    """
    global _INDEX_CACHE, _PRESENT_KEY, _PRESENT_MEMO
    root = _model_root(scene)
    key = str(root) if root is not None else ""
    if not force and _INDEX_CACHE is not None and _INDEX_CACHE[0] == key:
        return _INDEX_CACHE[1:]
    if key != _PRESENT_KEY or force:
        _PRESENT_KEY = key
        _PRESENT_MEMO = {}
    if root is None or _broad_dir(root):
        packed = ((), (), (), False, ())
        _INDEX_CACHE = (key, *packed)
        return packed
    allowed = _SCAN_ALLOWED if scan is None else bool(scan)
    try:
        if force:
            packed = pack.cached_model_index(root, force=True)
        else:
            packed = pack.load_model_index_cache(root)
            if packed is None:
                if not allowed:
                    return None
                packed = pack.cached_model_index(root)
    except OSError:
        packed = ((), (), (), False, ())
    _INDEX_CACHE = (key, *packed)
    return packed


def _prefix_present(prefix: str, name: str = "", legend: str = "", scene=None) -> bool:
    scene = scene if scene is not None else getattr(bpy.context, "scene", None)
    if scene is None or _model_root(scene) is None:
        return False
    memo_key = ((prefix or "").lower(), (name or "").lower(), (legend or "").lower())
    cached = _PRESENT_MEMO.get(memo_key)
    if cached is not None:
        return cached
    index = _model_index(scene)
    if index is None:
        return False
    casts, blobs, tex, _truncated, _paths = index
    hit = pack.files_present_indexed(casts, blobs, tex, prefix, name, legend)
    _PRESENT_MEMO[memo_key] = hit
    return hit


def _refresh_find(self, context):
    global _FIND_HOLD
    if _FIND_HOLD:
        return
    from .prefs import model_folder_pref

    locked = model_folder_pref()
    if locked is not None and str(getattr(self, "apex_model_dir", "") or "") != str(locked):
        _FIND_HOLD = True
        try:
            self.apex_model_dir = str(locked)
        finally:
            _FIND_HOLD = False
    _update_find(self, context)


def _row_detail(prefix: str) -> str:
    from .naming import is_recolor_code, parse_skin_identity, split_mesh_variant

    extra = (prefix or "").lower()
    ident = parse_skin_identity(prefix)
    _mesh, variant = split_mesh_variant(prefix)
    rarity = ident.rarity_label if ident.rarity_label != "Other" else ""
    blob = f"_{extra}_"
    if not rarity:
        if "_mythic_" in blob or "prestige" in extra:
            rarity = "Prestige"
        elif "_icon_" in blob:
            rarity = "Iconic"
        elif "_lgnd_" in blob or "_legendary_" in blob:
            rarity = "Legendary"
        elif extra.endswith("_base") or ident.skin in {"", "base"}:
            rarity = "Original"
    if variant and is_recolor_code(variant):
        return f"{rarity} Recolor".strip() if rarity else "Recolor"
    return rarity or "—"


def _rarity_rank(detail: str) -> int:
    word = ((detail or "").split() or [""])[0].lower()
    order = {name.lower(): index for index, name in enumerate(RARITY_ORDER)}
    return order.get(word, len(order))


def _order_find_rows(rows, sort_key: str, desc: bool):
    """Name is A-Z. Rarity follows the rarity order. The legend selector filters."""
    if sort_key == "rarity":
        rows.sort(
            key=lambda item: (_rarity_rank(item[3]), item[1].lower(), item[0].lower()),
            reverse=desc,
        )
        return rows
    rows.sort(key=lambda item: (item[1].lower(), item[0].lower()), reverse=desc)
    return rows


def _emit_find_header(items, title: str, key: str) -> None:
    hdr = items.add()
    hdr.name = title
    hdr.legend = key
    hdr.detail = ""
    hdr.present = False
    hdr.header = True
    hdr.favorite = False
    hdr.pick = False


def _emit_find_skin(items, row, favorite: bool, picked: bool = False) -> None:
    lg, name, _prefix, label, present = row
    item = items.add()
    item.name = name
    item.legend = lg
    item.detail = label
    item.present = bool(present)
    item.header = False
    item.favorite = favorite
    item.pick = picked


def _find_selection(scene):
    """Highlighted row and ticked skins, so a rebuild can put them back."""
    items = getattr(scene, "apex_find_items", None)
    picks = set()
    selected = None
    if not items:
        return selected, picks
    idx = int(getattr(scene, "apex_find_index", 0) or 0)
    section = ""
    if 0 <= idx < len(items):
        for pos in range(idx, -1, -1):
            if items[pos].header:
                section = items[pos].legend or ""
                break
        current = items[idx]
        if not current.header:
            selected = (section, (current.legend or "").lower(), (current.name or "").lower())
    for item in items:
        if item.header or not item.pick:
            continue
        picks.add(((item.legend or "").lower(), (item.name or "").lower()))
    return selected, picks


def _update_find(self, context):
    from .prefs import favorite_key, favorite_set

    selected, picks = _find_selection(self)
    items = self.apex_find_items
    items.clear()
    root = _model_root(self)
    if root is None:
        self.apex_find_index = 0
        try:
            self["apex_find_truncated"] = False
        except Exception:
            pass
        return
    index = _model_index(self)
    scanned = index is not None
    truncated = bool(index[3]) if scanned else False
    try:
        self["apex_find_truncated"] = bool(truncated)
        self["apex_find_unscanned"] = not scanned
    except Exception:
        pass
    query = (getattr(self, "apex_find_query", "") or "").strip()
    legend = getattr(self, "apex_find_legend", "") or ""
    try:
        hits = pack.search_index(query, legend=legend)
    except Exception:
        hits = []
    rows: list[tuple[str, str, str, str, bool]] = []
    for row in hits:
        lg, name = row[0], row[1]
        prefix = row[2] if len(row) > 2 else pack.prefix_for(lg, name)
        present = _prefix_present(prefix, name, lg, self) if scanned else True
        rows.append((lg, name, prefix, _row_detail(prefix), present))
    # Not scanned yet: show the built-in skin list unfiltered.
    only_present = scanned and bool(getattr(self, "apex_find_only_present", True))
    if only_present:
        rows = [row for row in rows if row[4]]
    sort_key = str(getattr(self, "apex_find_sort", "name") or "name")
    if sort_key not in {"name", "rarity"}:
        sort_key = "name"
    desc = bool(getattr(self, "apex_find_sort_desc", False))
    favs = favorite_set()
    fav_rows = [row for row in rows if favorite_key(row[0], row[1]) in favs]
    fav_rows = _order_find_rows(list(fav_rows), sort_key, desc)
    rows = _order_find_rows(rows, sort_key, desc)
    collapsed = _fold_set(self, "apex_find_collapsed")
    first_skin = -1
    chosen = -1

    def emit_skin(row, section: str) -> None:
        nonlocal first_skin, chosen
        key = ((row[0] or "").lower(), (row[1] or "").lower())
        _emit_find_skin(items, row, favorite_key(row[0], row[1]) in favs, key in picks)
        index = len(items) - 1
        if first_skin < 0:
            first_skin = index
        if selected == (section, key[0], key[1]):
            chosen = index

    if fav_rows:
        _emit_find_header(items, "Favorites", "__favorites__")
        if "__favorites__" not in collapsed:
            for row in fav_rows:
                emit_skin(row, "__favorites__")
    if rows:
        _emit_find_header(items, "All Skins", "__all__")
        if "__all__" not in collapsed:
            for row in rows:
                emit_skin(row, "__all__")
    self.apex_find_index = chosen if chosen >= 0 else max(first_skin, 0)


_LEGEND_ENUM: list[tuple[str, str, str]] = [("ALL", "All", "All legends")]


def _legend_enum(self, context):
    items = [("ALL", "All", "All legends")]
    try:
        for name in pack.legend_names():
            items.append((name, name, name))
    except Exception:
        pass
    _LEGEND_ENUM.clear()
    _LEGEND_ENUM.extend(items)
    return _LEGEND_ENUM


def _unique_dir(path: Path | None, seen: set[str], out: list[Path]) -> None:
    if path is None:
        return
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path)
    if key in seen:
        return
    seen.add(key)
    out.append(path)


def _find_roots(scene) -> list[Path]:
    from .log import existing_dir

    roots: list[Path] = []
    seen: set[str] = set()
    for raw in (
        getattr(scene, "apex_model_dir", "") or "",
        getattr(scene, "apex_texture_dir", "") or "",
    ):
        _unique_dir(existing_dir(raw), seen, roots)
    cast_raw = getattr(scene, "apex_cast_path", "") or ""
    if cast_raw:
        try:
            current = Path(bpy.path.abspath(cast_raw))
        except Exception:
            current = Path(str(cast_raw))
        parent = current.parent if (current.suffix or current.is_file()) else current
        _unique_dir(existing_dir(parent), seen, roots)
    return roots


def _casts_in(root: Path) -> list[Path]:
    from .naming import collect_lod0_casts, prefer_world_lod0, unique_skin_casts

    key = str(root)
    if _INDEX_CACHE is not None and _INDEX_CACHE[0] == key:
        paths = [Path(item) for item in _INDEX_CACHE[5]]
        return unique_skin_casts(prefer_world_lod0(paths, root))
    return collect_lod0_casts(root)


def _score_cast(path: Path, needle: str) -> tuple[int, int, int, int, int] | None:
    stem = path.stem.lower()
    n = (needle or "").lower()
    if not n or not (stem.startswith(n) or n in stem):
        return None
    start = 1 if stem.startswith(n) else 0
    rest = stem[len(n) :] if start else stem
    tight = 1 if start and (rest == "" or rest.startswith("_")) else 0
    lod0 = 1 if "lod0" in stem else 0
    is_w = 1 if ("_w_lod" in stem or stem.endswith("_w") or "_w_" in stem) else 0
    return (start, tight, lod0, is_w, -(len(stem) - len(n)))


def _casts_under(root: Path, lod0_only: bool) -> list[Path]:
    """CAST files under root. The texture walk can stop before the mesh."""
    from .naming import is_lod0_cast

    found: list[Path] = []
    if root is None or not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in {"__pycache__", ".git"}
        ]
        for name in filenames:
            if not name.lower().endswith(".cast"):
                continue
            if lod0_only and not is_lod0_cast(name):
                continue
            found.append(Path(dirpath) / name)
    return found


def _pick_cast(scene, needle: str) -> Path | None:
    from .naming import cast_search_prefixes, prefer_world_lod0, unique_skin_casts

    if not needle:
        return None
    roots: list[Path] = []
    seen_roots: set[str] = set()
    model_root = _model_root(scene)
    for root in ([model_root] if model_root is not None else []) + _find_roots(scene):
        if root is None:
            continue
        key = str(root)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        roots.append(root)
    queries = cast_search_prefixes(needle) or [needle]
    pool: list[Path] = []
    seen_paths: set[str] = set()
    for root in roots:
        for path in _casts_in(root):
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            pool.append(path)
    ranked = pack.rank_cast_for_prefix(needle, [str(path) for path in pool])
    if ranked:
        return Path(ranked)
    beside = pack.cast_beside_prefix(needle)
    if beside:
        return Path(beside)
    truncated = False
    if model_root is not None and _INDEX_CACHE is not None and _INDEX_CACHE[0] == str(model_root):
        truncated = bool(_INDEX_CACHE[4])
    if model_root is not None and (truncated or not pool):
        walked = _casts_under(model_root, lod0_only=True)
        ranked = pack.rank_cast_for_prefix(needle, [str(path) for path in walked])
        if ranked:
            return Path(ranked)
    if model_root is not None:
        any_cast = _casts_under(model_root, lod0_only=False)
        ranked = pack.rank_cast_for_prefix(needle, [str(path) for path in any_cast])
        if ranked:
            return Path(ranked)
    matched: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for query in queries:
        for path in pool:
            if _score_cast(path, query) is None:
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            matched.append((query, path))
        if matched:
            break
    if not matched:
        names = [str(path) for path in pool]
        for item in pack.casts_for_skin(needle, names):
            matched.append((needle, Path(item)))
    if not matched:
        return None
    query = matched[0][0]
    paths = [item[1] for item in matched]
    ranked_paths = unique_skin_casts(prefer_world_lod0(paths, roots[0] if roots else None))
    ranked_paths.sort(key=lambda p: _score_cast(p, query) or (0, 0, 0, 0, -9999), reverse=True)
    return ranked_paths[0]


class APEX_OT_shade_panel(bpy.types.Operator):
    bl_idname = "apexaddon.shade_panel"
    bl_label = "Shade Selected"
    bl_description = "Auto-shade the character with the selected shader"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = anim.resolve_shade_objects(context)
        if not objs:
            self.report({"ERROR"}, "No armature or mesh in the scene")
            return {"CANCELLED"}
        folder = extras.folder_for(objs[0], context.scene)
        try:
            reports = utils.shade_selected(objs, current_node_adder(context.scene), folder=folder)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _report_shade(self, reports, context.scene)
        return {"FINISHED"}


class APEX_OT_apply_shader(bpy.types.Operator):
    bl_idname = "apexaddon.apply_shader"
    bl_label = "Apply Shader"
    bl_description = "Shade the selection with the shader chosen in the dropdown"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return APEX_OT_shade_panel.execute(self, context)


class APEX_OT_pick_texture_folder(bpy.types.Operator):
    bl_idname = "apexaddon.pick_texture_folder"
    bl_label = "Choose Texture Folder"
    bl_description = "Pick the PNG folder and auto-shade the active model"
    bl_options = {"REGISTER", "UNDO"}
    directory: StringProperty(name="Directory", options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    target: StringProperty(name="Target", options={"HIDDEN"})

    def execute(self, context):
        context.scene.apex_texture_dir = self.directory
        obj = bpy.data.objects.get(self.target) if self.target else None
        if obj is None:
            obj = anim.resolve_character(context)
        folder = Path(bpy.path.abspath(self.directory))
        if obj is not None:
            arm = anim.resolve_armature(obj)
            extras.tag_character(arm or obj, folder=folder)
        if obj is None or obj.type not in {"ARMATURE", "MESH"}:
            return {"FINISHED"}
        try:
            reports = utils.shade_selected([obj], current_node_adder(context.scene), folder=folder)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        arm = anim.resolve_armature(obj)
        if arm is not None:
            anim.remember_character(arm)
        _report_shade(self, reports, context.scene)
        return {"FINISHED"}

    def invoke(self, context, event):
        objs = anim.resolve_shade_objects(context)
        self.target = objs[0].name if objs else ""
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class APEX_OT_recolor(bpy.types.Operator):
    bl_idname = "apexaddon.recolor"
    bl_label = "Recolor"
    bl_description = "Cycle rt/rc recolors on this unique skin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = anim.resolve_character(context)
        objs = [arm] if arm is not None else anim.resolve_shade_objects(context)
        if not objs:
            self.report({"ERROR"}, "Select the character armature")
            return {"CANCELLED"}
        folder = extras.folder_for(objs[0], context.scene)
        try:
            code, reports = utils.recolorSelected(
                objs, current_node_adder(context.scene), folder=folder
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _report_shade(self, reports, context.scene)
        self.report({"INFO"}, f"Recolor {code}")
        return {"FINISHED"}


class APEX_OT_clean_scene(bpy.types.Operator):
    bl_idname = "apexaddon.clean_scene"
    bl_label = "Remove unused items"
    bl_description = "Remove unused materials, images and meshes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = extras.purge_orphans()
        self.report({"INFO"}, f"Purged unused data ({n} local block(s))")
        return {"FINISHED"}


class APEX_OT_check_updates(bpy.types.Operator):
    bl_idname = "apexaddon.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Compare this fork with the upstream GitHub release"
    bl_options = {"REGISTER"}

    def execute(self, context):
        text = extras.check_for_updates()
        self.report({"INFO"}, text)
        return {"FINISHED"}



class APEX_OT_eevee_ready(bpy.types.Operator):
    bl_idname = "apexaddon.eevee_ready"
    bl_label = "Use Eevee"
    bl_description = "Switch to Eevee and apply recommended viewport/render settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        extras.apply_eevee_ready(context.scene)
        self.report({"INFO"}, "Applied Eevee-ready settings")
        return {"FINISHED"}


class APEX_OT_cycles_ready(bpy.types.Operator):
    bl_idname = "apexaddon.cycles_ready"
    bl_label = "Use Cycles"
    bl_description = "Switch the scene render engine to Cycles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            context.scene.render.engine = "CYCLES"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Switched to Cycles")
        return {"FINISHED"}


class _ApexSubpanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Apex Shader"
    bl_parent_id = "APEX_PT_main"
    bl_options = {"DEFAULT_CLOSED"}


class APEX_PT_main(bpy.types.Panel):
    bl_label = "Apex Auto Shader"
    bl_idname = "APEX_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Apex Shader"

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text=f"v{ADDON_VERSION_STR}")
        row.operator(APEX_OT_check_updates.bl_idname, text="Check for Updates", icon="FILE_REFRESH")
        if not cast_importer_available():
            box = layout.box()
            box.alert = True
            box.label(text="CAST importer missing", icon="ERROR")
            box.label(text="Install dtzxporter/cast, then restart Blender")
        layout.operator(anim.APEX_OT_import_cast.bl_idname, icon="IMPORT")
        layout.operator(APEX_OT_find_skins.bl_idname, icon="VIEWZOOM")
        engine = str(getattr(context.scene.render, "engine", "") or "")
        row = layout.row(align=True)
        row.label(text="Engine")
        row.operator(
            APEX_OT_eevee_ready.bl_idname,
            text="Eevee",
            depress=engine.startswith("BLENDER_EEVEE"),
        )
        row.operator(
            APEX_OT_cycles_ready.bl_idname,
            text="Cycles",
            depress=engine == "CYCLES",
        )
        if len(extras.tagged_armatures(context.scene)) > 1:
            layout.operator(anim.APEX_OT_showcase.bl_idname, icon="CAMERA_DATA")


class APEX_PT_textures(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Textures"
    bl_idname = "APEX_PT_textures"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "apex_shader", text="")
        layout.operator(APEX_OT_apply_shader.bl_idname, icon="NODE_MATERIAL")
        layout.operator(APEX_OT_recolor.bl_idname, icon="COLOR")
        if anim.character_has_level(context):
            label = anim.upgrade_button_label(context)
            icon = "TRIA_DOWN" if label == "Downgrade" else "TRIA_UP"
            layout.operator(anim.APEX_OT_upgrade.bl_idname, text=label, icon=icon)
        layout.operator(APEX_OT_clean_scene.bl_idname, icon="TRASH")


class APEX_OT_toggle_char_group(bpy.types.Operator):
    bl_idname = "apexaddon.toggle_char_group"
    bl_label = "Toggle Character Group"
    bl_description = "Collapse or expand this character group"
    bl_options = {"INTERNAL"}
    group: StringProperty(default="")
    kind: StringProperty(default="legend")
    default_collapsed: BoolProperty(default=False)

    def execute(self, context):
        scene = context.scene
        key = self.group
        if not key:
            return {"CANCELLED"}
        collapsed = _fold_set(scene, "apex_char_collapsed")
        expanded = _fold_set(scene, "apex_char_expanded")
        if char_group_collapsed(scene, key, self.default_collapsed):
            collapsed.discard(key)
            expanded.add(key)
        else:
            expanded.discard(key)
            collapsed.add(key)
        scene.apex_char_collapsed = "|".join(sorted(collapsed))
        scene.apex_char_expanded = "|".join(sorted(expanded))
        return {"FINISHED"}


class APEX_OT_toggle_bones(bpy.types.Operator):
    bl_idname = "apexaddon.toggle_bones"
    bl_label = "Character"
    bl_description = "Show or hide this whole character"
    bl_options = {"REGISTER", "UNDO"}
    target: StringProperty(default="")

    def execute(self, context):
        obj = bpy.data.objects.get(self.target)
        if obj is None:
            self.report({"ERROR"}, "Character not found")
            return {"CANCELLED"}
        hidden = utils.character_is_hidden(obj)
        utils.set_character_hidden(obj, not hidden)
        return {"FINISHED"}


def _fold_header(layout, key: str, text: str, closed: bool, kind: str, default_collapsed: bool, indent: bool = False):
    row = layout.row(align=True)
    if indent:
        row.separator()
    icon = "TRIA_RIGHT" if closed else "TRIA_DOWN"
    op = row.operator(
        APEX_OT_toggle_char_group.bl_idname,
        text="",
        icon=icon,
        emboss=False,
    )
    op.group = key
    op.kind = kind
    op.default_collapsed = default_collapsed
    op = row.operator(
        APEX_OT_toggle_char_group.bl_idname,
        text=text,
        emboss=False,
    )
    op.group = key
    op.kind = kind
    op.default_collapsed = default_collapsed
    return row


class APEX_PT_characters(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Characters"
    bl_idname = "APEX_PT_characters"
    bl_order = 40

    @classmethod
    def poll(cls, context):
        return bool(extras.tagged_armatures(context.scene))

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        grouped: dict[str, dict[str, list]] = {}
        for arm in extras.tagged_armatures(scene):
            from .naming import with_recolor_prefix

            tag = arm.get(extras.CHAR_TAG) or arm.get(extras.CHAR_CAST) or arm.name
            recolor = arm.get(extras.CHAR_RECOLOR) or ""
            source = with_recolor_prefix(str(tag), str(recolor)) if recolor else str(tag)
            ident = parse_skin_identity(source)
            legend, rarity, display = character_bucket(source)
            hit = pack.match_source(source) or pack.match_source(str(tag))
            if hit and legend != "Other" and legend_display_name(hit[0]).lower() == legend.lower():
                display = hit[1] or display
            elif hit and legend == "Other":
                legend, display = hit[0], hit[1]
                rarity = ident.rarity_label
            if recolor and hit and not str(recolor).lower() in source.lower():
                display = f"{display} {recolor}"
            grouped.setdefault(legend, {}).setdefault(rarity, []).append((display, arm))
        multi = len(grouped) > 1
        for legend in sorted(grouped, key=lambda n: n.lower()):
            legend_key = f"legend:{legend}"
            skins_n = sum(len(items) for items in grouped[legend].values())
            legend_closed = char_group_collapsed(scene, legend_key, multi)
            label = f"{legend} ({skins_n})" if multi else legend
            _fold_header(layout, legend_key, label, legend_closed, "legend", multi)
            if legend_closed:
                continue
            buckets = grouped[legend]
            for rarity in RARITY_ORDER:
                skins = buckets.get(rarity)
                if not skins:
                    continue
                rarity_key = f"{legend_key}:{rarity}"
                rarity_closed = char_group_collapsed(scene, rarity_key, True)
                _fold_header(
                    layout,
                    rarity_key,
                    f"{rarity} ({len(skins)})",
                    rarity_closed,
                    "rarity",
                    True,
                    indent=True,
                )
                if rarity_closed:
                    continue
                box = layout.box()
                for display, arm in sorted(skins, key=lambda item: item[0].lower()):
                    srow = box.row(align=True)
                    srow.label(text=display or arm.name, icon="ARMATURE_DATA")
                    bones = srow.operator(
                        APEX_OT_toggle_bones.bl_idname,
                        text="",
                        icon="HIDE_ON" if utils.character_is_hidden(arm) else "HIDE_OFF",
                    )
                    bones.target = arm.name
                    focus = srow.operator(
                        anim.APEX_OT_focus_character.bl_idname,
                        text="",
                        icon="RESTRICT_SELECT_OFF",
                    )
                    focus.target = arm.name


class APEX_PT_camera(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Camera"
    bl_idname = "APEX_PT_camera"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        split = layout.split(factor=0.67, align=True)
        split.operator(anim.APEX_OT_add_camera.bl_idname, icon="CAMERA_DATA")
        portrait = anim.render_is_portrait(context.scene)
        split.operator(
            anim.APEX_OT_toggle_frame.bl_idname,
            text="9:16" if portrait else "16:9",
        )
        locked = bool(getattr(context.scene, "apex_cam_lock", False))
        row = layout.row(align=True)
        row.operator(
            anim.APEX_OT_set_camera_pov.bl_idname,
            text="Unlock" if locked else "Lock Model",
            icon="LOCKED" if locked else "UNLOCKED",
        )
        pick = row.row(align=True)
        pick.ui_units_x = 7.0
        pick.prop(context.scene, "apex_cam_target", text="")
        row = layout.row(align=True)
        for key, label in (("front", "Front"), ("three_quarter", "3/4"), ("closeup", "Close-up")):
            op = row.operator(anim.APEX_OT_camera_preset.bl_idname, text=label)
            op.preset = key
        layout.prop(context.scene, "apex_light_boost")
        layout.prop(context.scene, "apex_light_kelvin")
        row = layout.row(align=True)
        row.prop(context.scene, "apex_cam_thirds", toggle=True)
        row.prop(context.scene, "apex_closeup_dof")


class APEX_PT_animation(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "APEX_PT_animation"
    bl_order = 20

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        from .prefs import anim_folder_pref

        locked = anim_folder_pref()
        folder_row = layout.row()
        folder_row.enabled = locked is None
        folder_row.prop(scene, "apex_anim_dir", text="")
        layout.operator(anim.APEX_OT_pick_anim_folder.bl_idname, icon="FILE_FOLDER")
        row = layout.row(align=True)
        row.prop(scene, "apex_anim_loop", text="Loop")
        search = row.row(align=True)
        search.alignment = "RIGHT"
        if bool(getattr(scene, "apex_anim_search", False)):
            search.prop(scene, "apex_anim_query", text="", icon="VIEWZOOM")
        search.operator(
            anim.APEX_OT_anim_search.bl_idname,
            text="",
            icon="X" if bool(getattr(scene, "apex_anim_search", False)) else "VIEWZOOM",
        )
        if not scene.apex_anim_items:
            return
        layout.template_list(
            "APEX_UL_anims",
            "apex_anims_compact",
            scene,
            "apex_anim_items",
            scene,
            "apex_anim_index",
            rows=8,
            maxrows=8,
        )
        row = layout.row(align=True)
        playing = bool(getattr(context.screen, "is_animation_playing", False))
        if playing:
            row.operator(anim.APEX_OT_anim_play.bl_idname, text="Pause", icon="PAUSE")
        else:
            row.operator(anim.APEX_OT_anim_play.bl_idname, text="Play", icon="PLAY")
        row.operator(anim.APEX_OT_anim_stop.bl_idname, text="Reset", icon="MESH_PLANE")
        layout.operator(anim.APEX_OT_anim_delete.bl_idname, icon="TRASH")


class APEX_PT_prop(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Prop"
    bl_idname = "APEX_PT_prop"
    bl_order = 30

    def draw(self, context):
        from . import prop as propmod
        from .prefs import prop_folder_pref

        layout = self.layout
        scene = context.scene
        folder_row = layout.row()
        folder_row.prop(scene, "apex_prop_dir", text="")
        layout.operator(propmod.APEX_OT_pick_prop_folder.bl_idname, icon="FILE_FOLDER")
        layout.prop(scene, "apex_prop_query", text="", icon="VIEWZOOM")
        raw = str(getattr(scene, "apex_prop_dir", "") or "")
        pref = prop_folder_pref()
        if not raw and pref is not None:
            propmod.queue_prop_sync()
        elif raw and not propmod.prop_list_ready(scene, raw):
            propmod.queue_prop_sync()
        if not scene.apex_prop_items:
            layout.label(text="No props in this folder")
            return
        layout.template_list(
            "APEX_UL_props",
            "apex_props_compact",
            scene,
            "apex_prop_items",
            scene,
            "apex_prop_index",
            rows=6,
            maxrows=6,
        )



class APEX_OT_find_mark(bpy.types.Operator):
    bl_idname = "apexaddon.find_mark"
    bl_label = "Status"
    bl_options = {"INTERNAL"}
    present: BoolProperty(default=False)

    @classmethod
    def description(cls, context, properties):
        return "Found" if getattr(properties, "present", False) else "Not Found"

    def execute(self, context):
        return {"CANCELLED"}


class APEX_OT_find_pick(bpy.types.Operator):
    bl_idname = "apexaddon.find_pick"
    bl_label = "Select skin"
    bl_description = "Tick or untick this skin"
    bl_options = {"INTERNAL"}
    index: IntProperty(default=-1)

    def execute(self, context):
        items = context.scene.apex_find_items
        if self.index < 0 or self.index >= len(items):
            return {"CANCELLED"}
        item = items[self.index]
        if getattr(item, "header", False):
            return {"CANCELLED"}
        item.pick = not bool(item.pick)
        context.scene.apex_find_index = self.index
        return {"FINISHED"}


class APEX_OT_find_suggest(bpy.types.Operator):
    bl_idname = "apexaddon.find_suggest"
    bl_label = "Suggestion"
    bl_description = "Fill search with this name"
    bl_options = {"INTERNAL"}
    text: StringProperty(default="")

    def execute(self, context):
        context.scene.apex_find_query = self.text
        return {"FINISHED"}


class APEX_PG_find_item(bpy.types.PropertyGroup):
    name: StringProperty(name="Skin")
    legend: StringProperty(name="Legend")
    present: BoolProperty(name="Present", default=False)
    detail: StringProperty(name="Detail", default="")
    pick: BoolProperty(name="Pick", default=False)
    header: BoolProperty(name="Header", default=False)
    favorite: BoolProperty(name="Favorite", default=False)


class APEX_OT_find_favorite(bpy.types.Operator):
    bl_idname = "apexaddon.find_favorite"
    bl_label = "Favorite"
    bl_description = "Pin this skin in the Favorites section"
    bl_options = {"INTERNAL"}
    legend: StringProperty(default="")
    skin: StringProperty(default="")

    def execute(self, context):
        from .prefs import toggle_favorite

        toggle_favorite(self.legend, self.skin)
        _update_find(context.scene, context)
        return {"FINISHED"}


class APEX_OT_find_sort(bpy.types.Operator):
    bl_idname = "apexaddon.find_sort"
    bl_label = "Sort"
    bl_description = "Sort the skin list. Click again to reverse"
    bl_options = {"INTERNAL"}
    key: StringProperty(default="name")

    def execute(self, context):
        scene = context.scene
        if str(getattr(scene, "apex_find_sort", "name") or "name") == self.key:
            scene.apex_find_sort_desc = not bool(scene.apex_find_sort_desc)
        else:
            scene.apex_find_sort = self.key
            scene.apex_find_sort_desc = False
        _update_find(scene, context)
        return {"FINISHED"}


class APEX_UL_find(bpy.types.UIList):
    bl_idname = "APEX_UL_find"

    def draw_filter(self, context, layout):
        pass

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if getattr(item, "header", False):
            closed = (item.legend or "").lower() in _fold_set(context.scene, "apex_find_collapsed")
            op = row.operator(
                APEX_OT_find_toggle_legend.bl_idname,
                text=item.name or item.legend or "",
                icon="TRIA_RIGHT" if closed else "TRIA_DOWN",
                emboss=False,
            )
            op.legend = item.legend or item.name or ""
            return
        mark = row.row(align=True)
        mark.alignment = "LEFT"
        mark.ui_units_x = 1.2
        op = mark.operator(
            APEX_OT_find_mark.bl_idname,
            text="",
            icon="CHECKMARK" if item.present else "CANCEL",
            emboss=False,
        )
        op.present = bool(item.present)
        pick = row.row(align=True)
        pick.ui_units_x = 1.2
        pick.prop(item, "pick", text="")
        star = row.row(align=True)
        star.ui_units_x = 1.2
        op = star.operator(
            APEX_OT_find_favorite.bl_idname,
            text="",
            icon="SOLO_ON" if item.favorite else "SOLO_OFF",
            emboss=False,
        )
        op.legend = item.legend or ""
        op.skin = item.name or ""
        name = row.row(align=True)
        name.ui_units_x = 9.0
        op = name.operator(
            APEX_OT_find_pick.bl_idname,
            text=item.name or "",
            emboss=False,
            depress=bool(item.pick),
        )
        op.index = index
        detail = row.row(align=True)
        detail.ui_units_x = 5.0
        op = detail.operator(
            APEX_OT_find_pick.bl_idname,
            text=item.detail or "—",
            emboss=False,
        )
        op.index = index
        legend = row.row(align=True)
        legend.ui_units_x = 4.0
        op = legend.operator(
            APEX_OT_find_pick.bl_idname,
            text=item.legend or "",
            emboss=False,
        )
        op.index = index


class APEX_OT_find_import_all(bpy.types.Operator):
    bl_idname = "apexaddon.find_import_all"
    bl_label = "Import all"
    bl_description = "Import every skin currently listed for the selected legend"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        legend = str(getattr(scene, "apex_find_legend", "") or "")
        items = getattr(scene, "apex_find_items", None)
        if not legend or legend.upper() == "ALL" or not items:
            return False
        return any(not getattr(it, "header", False) for it in items)

    def execute(self, context):
        scene = context.scene
        legend = str(getattr(scene, "apex_find_legend", "") or "")
        if not legend or legend.upper() == "ALL":
            self.report({"ERROR"}, "Select a legend first")
            return {"CANCELLED"}
        rows = [it for it in scene.apex_find_items if not getattr(it, "header", False)]
        if not rows:
            self.report({"ERROR"}, "No skins to import")
            return {"CANCELLED"}
        for item in rows:
            item.pick = True
        return APEX_OT_find_load.execute(self, context)


class APEX_OT_find_load(bpy.types.Operator):
    bl_idname = "apexaddon.find_load"
    bl_label = "Load selected"
    bl_description = "Import the highlighted skin, or every ticked row"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        items = getattr(scene, "apex_find_items", None)
        return bool(items) and len(items) > 0

    def execute(self, context):
        from .extras import CHAR_RECOLOR, CHAR_TAG, tag_character
        from .naming import cast_search_prefixes, find_texture_folder, is_recolor_code, split_mesh_variant
        from .node_adder import current_node_adder
        from .prefs import auto_load_anims, auto_shade
        from .utils import hide_rig

        scene = context.scene
        items = scene.apex_find_items
        idx = int(getattr(scene, "apex_find_index", 0) or 0)
        if not items:
            self.report({"ERROR"}, "Select a skin")
            return {"CANCELLED"}
        picked = [it for it in items if getattr(it, "pick", False) and not getattr(it, "header", False)]
        if not picked:
            if idx < 0 or idx >= len(items):
                self.report({"ERROR"}, "Select a skin")
                return {"CANCELLED"}
            chosen = items[idx]
            if getattr(chosen, "header", False):
                self.report({"ERROR"}, "Select a skin under the legend header")
                return {"CANCELLED"}
            picked = [chosen]
        seen_skins = set()
        unique = []
        for item in picked:
            key = ((item.legend or "").lower(), (item.name or "").lower())
            if key in seen_skins:
                continue
            seen_skins.add(key)
            unique.append(item)
        picked = unique

        first = None
        loaded = 0
        shaded = 0
        x = anim.next_import_x(context)
        for item in picked:
            needle = pack.prefix_for(item.legend, item.name)
            path = _pick_cast(scene, needle)
            if path is None:
                self.report({"WARNING"}, f"{item.name}: no CAST in the model folder")
                continue
            _mesh, variant = split_mesh_variant(needle)
            recolor = variant if is_recolor_code(variant) else ""
            tex_dir = pack.texture_dir_for_prefix(needle)
            if not tex_dir:
                for alias in cast_search_prefixes(needle):
                    tex_dir = pack.texture_dir_for_prefix(alias)
                    if tex_dir:
                        break
            try:
                arm, folder = anim.import_cast_model(context, str(path))
            except Exception as exc:
                self.report({"WARNING"}, f"{item.name}: {exc}")
                continue
            if arm is None:
                self.report({"WARNING"}, f"{item.name}: imported, but no armature")
                continue
            if tex_dir and not recolor:
                folder = Path(tex_dir)
            elif recolor:
                tagged = find_texture_folder(path, recolor_code=recolor)
                if tagged is not None:
                    folder = tagged
                elif tex_dir:
                    folder = Path(tex_dir)
            tag_character(arm, folder=folder, cast_path=path, recolor=recolor or None)
            if needle:
                arm[CHAR_TAG] = needle
            if recolor:
                arm[CHAR_RECOLOR] = recolor
            elif CHAR_RECOLOR in arm:
                try:
                    del arm[CHAR_RECOLOR]
                except Exception:
                    pass
            if auto_shade():
                try:
                    reports = utils.shade_selected(
                        [arm],
                        current_node_adder(scene),
                        folder=folder,
                        prefix=needle,
                        finish=False,
                    )
                    shaded += sum(1 for r in reports if r.get("wired"))
                except Exception as exc:
                    self.report({"WARNING"}, f"{item.name}: shade skipped: {exc}")
            anim.apply_model_size(arm)
            hide_rig(arm)
            anim.place_imported_character(arm, x)
            x = round(x + anim.IMPORT_GAP, 4)
            if first is None:
                first = arm
            loaded += 1
            item.pick = False

        if first is None:
            self.report({"ERROR"}, "Nothing imported")
            return {"CANCELLED"}
        try:
            anim.view_front_and_frame(context, first)
        except Exception:
            pass
        try:
            anim.set_material_viewport(context)
        except Exception:
            pass
        anim.deselect_all(context)
        if auto_load_anims() and first is not None:
            try:
                anim.autoload_legend_animations(context, first.get(CHAR_TAG) or "")
            except Exception:
                pass
        self.report({"INFO"}, f"Imported {loaded} skin(s), shaded {shaded} mesh(es)")
        return {"FINISHED"}


def _selected_find_items(scene) -> list:
    items = getattr(scene, "apex_find_items", None)
    if not items:
        return []
    picked = [it for it in items if getattr(it, "pick", False) and not getattr(it, "header", False)]
    if picked:
        return picked
    idx = int(getattr(scene, "apex_find_index", 0) or 0)
    if idx < 0 or idx >= len(items):
        return []
    chosen = items[idx]
    if getattr(chosen, "header", False):
        return []
    return [chosen]


def _duplicate_import_names(context) -> list[str]:
    from .extras import CHAR_RECOLOR, CHAR_TAG, tagged_armatures

    scene = context.scene
    picked = _selected_find_items(scene)
    if not picked:
        return []
    tagged = [
        (
            str(arm.get(CHAR_TAG, "") or ""),
            str(arm.get(CHAR_RECOLOR, "") or ""),
            str(getattr(arm, "name", "") or ""),
        )
        for arm in tagged_armatures(scene)
    ]
    if not tagged:
        return []
    names: list[str] = []
    for item in picked:
        needle = pack.prefix_for(item.legend, item.name)
        if pack.skin_already_imported(item.legend, item.name, needle, tagged):
            names.append(item.name)
    return names


class APEX_OT_find_toggle_legend(bpy.types.Operator):
    bl_idname = "apexaddon.find_toggle_legend"
    bl_label = "Toggle Legend"
    bl_description = "Collapse or expand this legend"
    bl_options = {"INTERNAL"}
    legend: StringProperty(default="")

    def execute(self, context):
        scene = context.scene
        key = (self.legend or "").strip().lower()
        if not key:
            return {"CANCELLED"}
        folded = _fold_set(scene, "apex_find_collapsed")
        if key in folded:
            folded.discard(key)
        else:
            folded.add(key)
        scene.apex_find_collapsed = "|".join(sorted(folded))
        _update_find(scene, context)
        return {"FINISHED"}


class APEX_OT_find_confirm(bpy.types.Operator):
    bl_idname = "apexaddon.find_confirm"
    bl_label = "Already imported"
    bl_description = "Import this skin again"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        msg = getattr(context.scene, "apex_find_dupe_msg", "") or "Skin already imported. Import again?"
        self.layout.label(text=msg)

    def execute(self, context):
        return APEX_OT_find_load.execute(self, context)


class APEX_OT_find_scan(bpy.types.Operator):
    bl_idname = "apexaddon.find_scan"
    bl_label = "Scan folder"
    bl_description = "Scan the model folder now and rebuild the on-disk cache"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        global _SCAN_ALLOWED
        _SCAN_ALLOWED = True
        _model_index(context.scene, force=True)
        _update_find(context.scene, context)
        return {"FINISHED"}


def _suggest_model_dir(scene) -> None:
    """Find Skins opens on the Model folder, or on the RSX export folder."""
    global _FIND_HOLD
    from .log import existing_dir
    from .prefs import model_folder_pref, pref

    def _set(text: str) -> None:
        global _FIND_HOLD
        if str(getattr(scene, "apex_model_dir", "") or "") == text:
            return
        _FIND_HOLD = True
        try:
            scene.apex_model_dir = text
        finally:
            _FIND_HOLD = False

    locked = model_folder_pref()
    if locked is not None:
        _set(str(locked))
        return
    raw = str(pref("rsx_export_dir", "") or "").strip()
    folder = existing_dir(raw) if raw else None
    if folder is None or _broad_dir(folder):
        return
    _set(str(folder))


class APEX_OT_find_skins(bpy.types.Operator):
    bl_idname = "apexaddon.find_skins"
    bl_label = "Find Skins"
    bl_description = "Search skins by name and import a match from the model folder"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        global _SCAN_ALLOWED
        _suggest_model_dir(context.scene)
        # First open of the search: allow the folder scan (disk cache first).
        _SCAN_ALLOWED = True
        _refresh_find(context.scene, context)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def draw(self, context):
        from .prefs import model_folder_pref, pref

        scene = context.scene
        layout = self.layout
        folder_row = layout.row()
        folder_row.enabled = model_folder_pref() is None
        folder_row.prop(scene, "apex_model_dir", text="Model folder")

        if model_folder_pref() is None and not str(pref("rsx_export_dir", "") or "").strip():
            layout.label(text="Set RSX export folder in Add-on Preferences")
        elif model_folder_pref() is None and _model_root(scene) is None:
            layout.label(text="RSX export folder was not found")
        elif bool(scene.get("apex_find_truncated")):
            layout.label(text="Folder is very large — list may be incomplete")
        elif bool(scene.get("apex_find_unscanned")):
            layout.label(text="Folder not scanned yet — press Scan folder")
        row = layout.row(align=True)
        row.prop(scene, "apex_find_only_present", text="Skins found")
        row.operator(APEX_OT_find_scan.bl_idname, text="Scan folder", icon="FILE_REFRESH")
        legend = str(getattr(scene, "apex_find_legend", "") or "")
        if legend and legend.upper() != "ALL":
            row.operator(APEX_OT_find_import_all.bl_idname, text="Import all", icon="IMPORT")
        layout.prop(scene, "apex_find_query", text="", icon="VIEWZOOM")
        sugs = pack.suggest_names(scene.apex_find_query, scene.apex_find_legend)
        if sugs:
            bar = layout.box()
            row = bar.row(align=True)
            for i, sug in enumerate(sugs):
                if i == 4:
                    row = bar.row(align=True)
                op = row.operator(APEX_OT_find_suggest.bl_idname, text=sug)
                op.text = sug
        elif scene.apex_find_query:
            close = pack.did_you_mean(scene.apex_find_query, scene.apex_find_legend)
            if close:
                bar = layout.box()
                row = bar.row(align=True)
                row.label(text="Did you mean:")
                for sug in close:
                    op = row.operator(APEX_OT_find_suggest.bl_idname, text=sug)
                    op.text = sug
        layout.prop(scene, "apex_find_legend", text="Legend")
        if _model_root(scene) is None:
            layout.label(text="Set a model folder to list skins")
            return
        if not len(scene.apex_find_items):
            if scene.apex_find_query or (scene.apex_find_legend and scene.apex_find_legend.upper() != "ALL"):
                layout.label(text="No matches — pick a suggestion or clear the search")
            else:
                layout.label(text="No skins from this folder" if scene.apex_find_only_present else "No skins for that folder")
            return
        bar = layout.row(align=True)
        current = str(getattr(scene, "apex_find_sort", "name") or "name")
        desc = bool(getattr(scene, "apex_find_sort_desc", False))
        for key, label in (("name", "Name"), ("rarity", "Rarity")):
            icon = "NONE"
            if current == key:
                icon = "TRIA_UP" if desc else "TRIA_DOWN"
            op = bar.operator(APEX_OT_find_sort.bl_idname, text=label, icon=icon)
            op.key = key
        layout.template_list(
            "APEX_UL_find",
            "",
            scene,
            "apex_find_items",
            scene,
            "apex_find_index",
            rows=12,
        )

    def execute(self, context):
        dupes = _duplicate_import_names(context)
        if dupes:
            context.scene.apex_find_dupe_msg = f"Skin {', '.join(dupes)} already imported. Import again?"

            def _open():
                try:
                    bpy.ops.apexaddon.find_confirm("INVOKE_DEFAULT")
                except Exception:
                    return None
                return None

            bpy.app.timers.register(_open, first_interval=0.05)
            return {"FINISHED"}
        return APEX_OT_find_load.execute(self, context)


panel_classes = (
    APEX_OT_shade_panel,
    APEX_OT_apply_shader,
    APEX_OT_pick_texture_folder,
    APEX_OT_recolor,
    APEX_OT_clean_scene,
    APEX_OT_check_updates,
    APEX_OT_eevee_ready,
    APEX_OT_cycles_ready,
    APEX_OT_toggle_char_group,
    APEX_OT_toggle_bones,
    APEX_OT_find_mark,
    APEX_OT_find_pick,
    APEX_OT_find_suggest,
    APEX_OT_find_favorite,
    APEX_OT_find_sort,
    APEX_PG_find_item,
    APEX_UL_find,
    APEX_OT_find_load,
    APEX_OT_find_import_all,
    APEX_OT_find_toggle_legend,
    APEX_OT_find_confirm,
    APEX_OT_find_scan,
    APEX_OT_find_skins,
    APEX_PT_main,
    APEX_PT_textures,
    APEX_PT_characters,
    APEX_PT_camera,
    APEX_PT_animation,
    APEX_PT_prop,
    *propmod.prop_classes,
)


def _update_light_boost(self, _context):
    try:
        from .anim.studio import apply_light_boost

        apply_light_boost(self)
    except Exception:
        pass


def _update_light_kelvin(self, _context):
    try:
        from .anim.studio import apply_light_kelvin

        apply_light_kelvin(self)
    except Exception:
        pass


def _update_thirds(self, _context):
    try:
        from .anim.studio import apply_composition_guides

        apply_composition_guides(self)
    except Exception:
        pass


def _update_closeup_dof(self, context):
    try:
        from .anim.studio import sync_closeup_dof

        sync_closeup_dof(context)
    except Exception:
        pass


def _update_portrait(self, _context):
    try:
        from .anim.studio import apply_frame_orientation
        apply_frame_orientation(self)
    except Exception:
        pass


def _cam_target_items(_self, context):
    items = [("ACTIVE", "Selected object", "Lock whatever is selected")]
    groups = {}
    loose = []
    scene = getattr(context, "scene", None)
    objects = list(getattr(scene, "objects", []) or [])
    for obj in objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        if (obj.name or "").startswith("Apex "):
            continue
        parent = getattr(obj, "parent", None)
        if parent is not None and getattr(parent, "type", "") == "ARMATURE":
            groups.setdefault(parent.name, []).append(obj.name)
        else:
            loose.append(obj.name)
    for arm_name in sorted(groups):
        items.append(None)
        for mesh_name in sorted(groups[arm_name]):
            items.append((mesh_name, f"{arm_name} / {mesh_name}", mesh_name))
    if loose:
        items.append(None)
        for mesh_name in sorted(loose):
            items.append((mesh_name, mesh_name, mesh_name))
    return items


def _update_cam_target(self, _context):
    if not bool(getattr(self, "apex_cam_lock", False)):
        return
    try:
        from .anim.studio import aim_locked_camera
        aim_locked_camera(self)
    except Exception:
        pass


def _update_cam_lock(self, _context):
    try:
        from .anim.studio import sync_cam_lock_handlers

        sync_cam_lock_handlers()
    except Exception:
        pass


def _refresh_anim_legends():
    """Rebuild the animation list so folder names like Jump are not legends."""
    try:
        from .anim.clips import fill_animation_list
        from .prefs import anim_folder_pref

        locked = anim_folder_pref()
        for scene in list(bpy.data.scenes):
            folder = str(locked) if locked is not None else str(getattr(scene, "apex_anim_dir", "") or "")
            if folder:
                fill_animation_list(scene, folder)
    except Exception:
        pass
    return None


def register_props():
    bpy.types.Scene.apex_shader = EnumProperty(
        name="Shader",
        description="Shader used by Apply Shader, import, and Find Skin",
        items=SHADER_ITEMS,
        default="plus_se",
        get=apex_shader_get,
        set=apex_shader_set,
        update=on_apex_shader_update,
    )
    bpy.types.Scene.apex_shader_user_set = BoolProperty(
        name="Shader Chosen",
        description="Set when the shader dropdown or menu is changed",
        default=False,
        options={"HIDDEN"},
    )
    bpy.types.Scene.apex_anim_loop = BoolProperty(
        name="Loop",
        description="Loop the current clip. Off = play once",
        default=anim_loop_default(),
    )
    bpy.types.Scene.apex_anim_search = BoolProperty(
        name="Search",
        description="Show the pose search field",
        default=False,
    )
    bpy.types.Scene.apex_anim_query = StringProperty(
        name="Search",
        description="Find a pose by name. Reversed text matches too",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )
    bpy.types.Scene.apex_cam_preset = StringProperty(name="Camera preset", default="front")
    bpy.types.Scene.apex_light_boost = bpy.props.FloatProperty(
        name="Light boost",
        description="Multiply Apex studio light energy. 0% keeps the camera rig values.",
        default=0.0,
        min=0.0,
        max=200.0,
        soft_min=0.0,
        soft_max=100.0,
        step=100,
        precision=0,
        subtype="PERCENTAGE",
        update=_update_light_boost,
    )
    bpy.types.Scene.apex_light_kelvin = bpy.props.FloatProperty(
        name="Light color",
        description="Studio light temperature. 6500K is daylight white, lower is warmer",
        default=6500.0,
        min=2700.0,
        max=9000.0,
        step=100,
        precision=0,
        update=_update_light_kelvin,
    )
    bpy.types.Scene.apex_cam_thirds = BoolProperty(
        name="Thirds",
        description="Rule-of-thirds guides on the studio camera",
        default=False,
        update=_update_thirds,
    )
    bpy.types.Scene.apex_closeup_dof = BoolProperty(
        name="Close-up DOF",
        description="Shallow depth of field on the close-up camera. Focuses the character's head",
        default=False,
        update=_update_closeup_dof,
    )
    bpy.types.Scene.apex_cam_portrait = BoolProperty(
        name="Portrait",
        description="On = portrait 1080x1920, off = landscape 1920x1080",
        default=False,
        update=_update_portrait,
    )
    bpy.types.Scene.apex_cam_lock = BoolProperty(name="Lock camera", default=False, update=_update_cam_lock)
    bpy.types.Scene.apex_cam_lock_name = StringProperty(name="Locked object", default="")
    bpy.types.Scene.apex_cam_target = EnumProperty(
        name="Lock target",
        description="Mesh the camera stays aimed at",
        items=_cam_target_items,
        update=_update_cam_target,
    )
    bpy.types.Scene.apex_texture_dir = StringProperty(
        name="Texture folder",
        description="Folder that contains every PNG for this skin",
        subtype="DIR_PATH",
        default="",
    )
    bpy.types.Scene.apex_anim_dir = StringProperty(
        name="Animation folder",
        description="Folder of CAST animation files",
        subtype="DIR_PATH",
        default="",
        update=_update_anim_dir,
    )
    bpy.types.Scene.apex_anim_items = CollectionProperty(type=anim.APEX_PG_anim_item)
    bpy.types.Scene.apex_anim_index = IntProperty(name="Animation", default=0)
    bpy.types.Scene.apex_character = StringProperty(
        name="Character",
        description="Last used character armature",
        default="",
    )
    bpy.types.Scene.apex_cast_path = StringProperty(
        name="CAST path",
        description="Last imported CAST model",
        subtype="FILE_PATH",
        default="",
    )
    bpy.types.Scene.apex_cast_collection = StringProperty(
        name="CAST collection",
        default="",
    )
    bpy.types.Scene.apex_char_collapsed = StringProperty(default="")
    bpy.types.Scene.apex_char_expanded = StringProperty(default="")
    bpy.types.Scene.apex_last_status = StringProperty(
        name="Last shade status",
        description="Summary of the last shade / recolor run",
        default="",
    )
    bpy.types.Scene.apex_model_dir = StringProperty(
        name="Model folder",
        description="Folder of CAST models to search",
        subtype="DIR_PATH",
        default="",
        update=_refresh_find,
    )
    bpy.types.Scene.apex_find_query = StringProperty(
        name="Search",
        description="Find a skin by name. The list updates while typing",
        default="",
        options={"TEXTEDIT_UPDATE"},
        update=_update_find,
    )
    bpy.types.Scene.apex_find_only_present = BoolProperty(
        name="Skins found",
        description="Show only skins that were found in the model folder. Turn off to list every skin",
        default=True,
        update=_update_find,
    )
    bpy.types.Scene.apex_find_legend = EnumProperty(
        name="Legend",
        description="Limit results to one legend",
        items=_legend_enum,
        update=_update_find,
    )
    bpy.types.Scene.apex_find_items = CollectionProperty(type=APEX_PG_find_item)
    bpy.types.Scene.apex_find_index = IntProperty(name="Skin", default=0)
    bpy.types.Scene.apex_find_collapsed = StringProperty(default="")
    bpy.types.Scene.apex_find_sort = StringProperty(name="Sort", default="name")
    bpy.types.Scene.apex_find_sort_desc = BoolProperty(name="Sort descending", default=False)
    bpy.types.Scene.apex_find_dupe_msg = StringProperty(default="")
    propmod.register_scene_props()
    try:
        bpy.app.timers.register(_refresh_anim_legends, first_interval=0.8)
    except Exception:
        pass
    try:
        sync_unset_scenes()
    except Exception:
        pass


def unregister_props():
    for attr in (
        "apex_shader",
        "apex_shader_user_set",
        "apex_anim_loop",
        "apex_anim_search",
        "apex_anim_query",
        "apex_cam_preset",
        "apex_light_boost",
        "apex_light_kelvin",
        "apex_cam_thirds",
        "apex_closeup_dof",
        "apex_cam_portrait",
        "apex_cam_lock",
        "apex_cam_lock_name",
        "apex_cam_target",
        "apex_texture_dir",
        "apex_anim_dir",
        "apex_anim_items",
        "apex_anim_index",
        "apex_prop_dir",
        "apex_prop_items",
        "apex_prop_index",
        "apex_prop_query",
        "apex_prop_collapsed",
        "apex_character",
        "apex_cast_path",
        "apex_cast_collection",
        "apex_char_collapsed",
        "apex_char_expanded",
        "apex_last_status",
        "apex_model_dir",
        "apex_find_query",
        "apex_find_only_present",
        "apex_find_legend",
        "apex_find_items",
        "apex_find_index",
        "apex_find_collapsed",
        "apex_find_sort",
        "apex_find_sort_desc",
        "apex_find_dupe_msg",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
