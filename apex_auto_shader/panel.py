from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty

from . import anim, extras, pack, utils
from .config import ADDON_VERSION_STR
from .naming import RARITY_ORDER, legend_display_name, parse_skin_identity
from .node_adder import current_node_adder
from .prefs import SHADER_ITEMS, anim_loop_default, cast_importer_available, default_shader


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
    raw = getattr(self, "apex_anim_dir", "") or ""
    if not raw:
        self.apex_anim_items.clear()
        return
    folder = Path(bpy.path.abspath(raw))
    if folder.is_dir():
        anim.fill_animation_list(self, folder)


_STEM_CACHE: tuple[str, tuple[str, ...]] | None = None
_TEX_CACHE: tuple[str, tuple[str, ...]] | None = None


def _model_root(scene) -> Path | None:
    from .log import existing_dir

    return existing_dir(getattr(scene, "apex_model_dir", "") or "")


def _folder_stems(scene) -> tuple[str, ...]:
    global _STEM_CACHE
    root = _model_root(scene)
    key = str(root) if root is not None else ""
    if _STEM_CACHE is not None and _STEM_CACHE[0] == key:
        return _STEM_CACHE[1]
    stems: list[str] = []
    if root is not None:
        try:
            for path in _casts_in(root):
                stems.append(path.stem.lower())
        except Exception:
            pass
    packed = tuple(stems)
    _STEM_CACHE = (key, packed)
    return packed


def _folder_tex_blobs(scene) -> tuple[str, ...]:
    global _TEX_CACHE
    from .naming import IMAGE_SUFFIXES

    root = _model_root(scene)
    key = str(root) if root is not None else ""
    if _TEX_CACHE is not None and _TEX_CACHE[0] == key:
        return _TEX_CACHE[1]
    blobs: list[str] = []
    if root is not None:
        try:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                blobs.append("_".join([path.stem, *path.parts[-4:]]).lower())
        except OSError:
            pass
    packed = tuple(blobs)
    _TEX_CACHE = (key, packed)
    return packed


def _prefix_present(prefix: str, name: str = "", legend: str = "", scene=None) -> bool:
    scene = scene if scene is not None else getattr(bpy.context, "scene", None)
    if scene is None or _model_root(scene) is None:
        return False
    return pack.files_present(_folder_stems(scene), _folder_tex_blobs(scene), prefix, name, legend)


def _refresh_find(self, context):
    global _STEM_CACHE, _TEX_CACHE
    _STEM_CACHE = None
    _TEX_CACHE = None
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


def _update_find(self, context):
    items = self.apex_find_items
    items.clear()
    if _model_root(self) is None:
        self.apex_find_index = 0
        return
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
        present = _prefix_present(prefix, name, lg, self)
        rows.append((lg, name, prefix, _row_detail(prefix), present))
    browse = not query
    if browse:
        rows.sort(key=lambda item: (item[0].lower(), item[1].lower()))
    group = browse and len({row[0].lower() for row in rows}) > 1
    collapsed = _fold_set(self, "apex_find_collapsed")
    last = ""
    first_skin = -1
    for lg, name, prefix, label, present in rows:
        if group and lg.lower() != last:
            hdr = items.add()
            hdr.name = lg
            hdr.legend = lg
            hdr.detail = ""
            hdr.present = False
            hdr.header = True
            last = lg.lower()
        if group and lg.lower() in collapsed:
            continue
        item = items.add()
        item.name = name
        item.legend = lg
        item.detail = label
        item.present = bool(present)
        item.header = False
        if first_skin < 0:
            first_skin = len(items) - 1
    self.apex_find_index = max(first_skin, 0)


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
    from .extras import list_model_casts
    from .naming import collect_lod0_casts, prefer_world_lod0, unique_skin_casts

    found = list(collect_lod0_casts(root))
    found.extend(list_model_casts(root))
    return unique_skin_casts(prefer_world_lod0(found, root))


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


def _pick_cast(scene, needle: str) -> Path | None:
    from .naming import cast_search_prefixes, prefer_world_lod0, unique_skin_casts

    if not needle:
        return None
    roots = _find_roots(scene)
    queries = cast_search_prefixes(needle) or [needle]
    matched: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for query in queries:
        for root in roots:
            for path in _casts_in(root):
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
        return None
    query = matched[0][0]
    paths = [item[1] for item in matched]
    ranked = unique_skin_casts(prefer_world_lod0(paths, roots[0] if roots else None))
    ranked.sort(key=lambda p: _score_cast(p, query) or (0, 0, 0, 0, -9999), reverse=True)
    return ranked[0]


class APEX_OT_shade_panel(bpy.types.Operator):
    bl_idname = "apexaddon.shade_panel"
    bl_label = "Shade Selected"
    bl_description = "Auto-shade the character from the texture folder"
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
    bl_label = "Apply Eevee-ready settings"
    bl_description = "Switch to Eevee and apply recommended viewport/render settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        extras.apply_eevee_ready(context.scene)
        self.report({"INFO"}, "Applied Eevee-ready settings")
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
        if len(extras.tagged_armatures(context.scene)) > 1:
            layout.operator(anim.APEX_OT_showcase.bl_idname, icon="CAMERA_DATA")


class APEX_PT_textures(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Textures"
    bl_idname = "APEX_PT_textures"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "apex_texture_dir", text="")
        layout.operator(APEX_OT_pick_texture_folder.bl_idname, icon="FILE_FOLDER")
        layout.operator(APEX_OT_recolor.bl_idname, icon="COLOR")
        layout.operator(APEX_OT_eevee_ready.bl_idname, icon="SHADING_RENDERED")
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
            hit = pack.match_source(source) or pack.match_source(str(tag))
            if hit:
                legend, display = hit[0], hit[1]
            else:
                legend = legend_display_name(ident.legend) if ident.legend else "Other"
                display = ident.display
            if recolor and hit and not str(recolor).lower() in source.lower():
                display = f"{display} {recolor}"
            grouped.setdefault(legend, {}).setdefault(ident.rarity_label, []).append((display, arm))
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
                    focus = srow.operator(
                        anim.APEX_OT_focus_character.bl_idname,
                        text="",
                        icon="RESTRICT_SELECT_OFF",
                    )
                    focus.target = arm.name


class APEX_PT_camera(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Camera"
    bl_idname = "APEX_PT_camera"

    def draw(self, context):
        layout = self.layout
        layout.operator(anim.APEX_OT_add_camera.bl_idname, icon="CAMERA_DATA")
        layout.operator(anim.APEX_OT_set_camera_pov.bl_idname, icon="CON_TRACKTO")
        row = layout.row(align=True)
        for key, label in (("front", "Front"), ("three_quarter", "3/4"), ("closeup", "Close-up")):
            op = row.operator(anim.APEX_OT_camera_preset.bl_idname, text=label)
            op.preset = key


class APEX_PT_animation(_ApexSubpanel, bpy.types.Panel):
    bl_label = "Animation"
    bl_idname = "APEX_PT_animation"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "apex_anim_dir", text="")
        layout.operator(anim.APEX_OT_pick_anim_folder.bl_idname, icon="FILE_FOLDER")
        layout.prop(scene, "apex_anim_loop", text="Loop")
        if not scene.apex_anim_items:
            return
        layout.template_list(
            "APEX_UL_anims",
            "",
            scene,
            "apex_anim_items",
            scene,
            "apex_anim_index",
            rows=6,
        )
        row = layout.row(align=True)
        playing = bool(getattr(context.screen, "is_animation_playing", False))
        if playing:
            row.operator(anim.APEX_OT_anim_play.bl_idname, text="Pause", icon="PAUSE")
        else:
            row.operator(anim.APEX_OT_anim_play.bl_idname, text="Play", icon="PLAY")
        row.operator(anim.APEX_OT_anim_stop.bl_idname, text="Reset", icon="MESH_PLANE")
        layout.operator(anim.APEX_OT_anim_delete.bl_idname, icon="TRASH")



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
                text=item.legend or item.name or "",
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
        name = row.row(align=True)
        name.ui_units_x = 9.0
        name.label(text=item.name or "")
        detail = row.row(align=True)
        detail.ui_units_x = 5.0
        detail.label(text=item.detail or "—")
        legend = row.row(align=True)
        legend.ui_units_x = 4.0
        legend.label(text=item.legend or "")


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
        from .naming import find_texture_folder, split_mesh_variant
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
            _mesh, recolor = split_mesh_variant(needle)
            try:
                arm, folder = anim.import_cast_model(context, str(path))
            except Exception as exc:
                self.report({"WARNING"}, f"{item.name}: {exc}")
                continue
            if arm is None:
                self.report({"WARNING"}, f"{item.name}: imported, but no armature")
                continue
            if recolor:
                tagged = find_texture_folder(path, recolor_code=recolor)
                if tagged is not None:
                    folder = tagged
            tag_character(arm, folder=folder, cast_path=path, recolor=recolor)
            if needle:
                arm[CHAR_TAG] = needle
            if recolor:
                arm[CHAR_RECOLOR] = recolor
            if auto_shade():
                try:
                    reports = utils.shade_selected(
                        [arm], current_node_adder(scene), folder=folder, finish=False
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


class APEX_OT_find_skins(bpy.types.Operator):
    bl_idname = "apexaddon.find_skins"
    bl_label = "Find Skins"
    bl_description = "Search skins by name and import a match from the model folder"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        _refresh_find(context.scene, context)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        layout.prop(scene, "apex_model_dir", text="Model folder")
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
                layout.label(text="No skins for that folder")
            return
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
    APEX_OT_pick_texture_folder,
    APEX_OT_recolor,
    APEX_OT_clean_scene,
    APEX_OT_check_updates,
    APEX_OT_eevee_ready,
    APEX_OT_toggle_char_group,
    APEX_OT_find_mark,
    APEX_OT_find_suggest,
    APEX_PG_find_item,
    APEX_UL_find,
    APEX_OT_find_load,
    APEX_OT_find_toggle_legend,
    APEX_OT_find_confirm,
    APEX_OT_find_skins,
    APEX_PT_main,
    APEX_PT_textures,
    APEX_PT_characters,
    APEX_PT_camera,
    APEX_PT_animation,
)


def register_props():
    bpy.types.Scene.apex_shader = EnumProperty(
        name="Shader",
        items=SHADER_ITEMS,
        default=default_shader(),
    )
    bpy.types.Scene.apex_anim_loop = BoolProperty(
        name="Loop",
        description="Loop the current clip. Off = play once",
        default=anim_loop_default(),
    )
    bpy.types.Scene.apex_cam_preset = StringProperty(name="Camera preset", default="front")
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
        description="Find a skin by name",
        default="",
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
    bpy.types.Scene.apex_find_dupe_msg = StringProperty(default="")


def unregister_props():
    for attr in (
        "apex_shader",
        "apex_anim_loop",
        "apex_cam_preset",
        "apex_texture_dir",
        "apex_anim_dir",
        "apex_anim_items",
        "apex_anim_index",
        "apex_character",
        "apex_cast_path",
        "apex_cast_collection",
        "apex_char_collapsed",
        "apex_char_expanded",
        "apex_last_status",
        "apex_model_dir",
        "apex_find_query",
        "apex_find_legend",
        "apex_find_items",
        "apex_find_index",
        "apex_find_collapsed",
        "apex_find_dupe_msg",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
