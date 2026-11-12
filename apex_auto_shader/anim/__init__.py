"""Animation / import / studio camera — split for maintainability; public API unchanged."""
from __future__ import annotations

import re
from pathlib import Path

import bpy
from mathutils import Vector
from bpy.props import BoolProperty, CollectionProperty, StringProperty

from . import apply, character, clips, const, studio
from ..log import existing_dir, log
from ..prefs import auto_load_anims, auto_shade
from ..utils import hide_rig


def _reexport(*mods) -> None:
    """Star-import skips _names; the old single-file API exposed them."""
    g = globals()
    for mod in mods:
        for name, value in vars(mod).items():
            if name.startswith("__"):
                continue
            g[name] = value


_reexport(const, character, clips, apply, studio)

class APEX_OT_import_cast(bpy.types.Operator):
    bl_idname = "apexaddon.import_cast"
    bl_label = "Import CAST Model(s)"
    bl_description = "Import selected .cast files, or every LOD0 in the folder and its subfolders"
    bl_options = {"REGISTER", "UNDO"}
    filepath: StringProperty(name="File Path", subtype="FILE_PATH")
    directory: StringProperty(name="Directory", subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_glob: StringProperty(default="*.cast", options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def execute(self, context):
        from .. import utils
        from ..extras import tag_character
        from ..node_adder import current_node_adder
        from ..prefs import model_folder_pref

        paths = limit_to_model_folder(
            _gather_import_casts(self.directory, self.filepath, self.files)
        )
        if not paths:
            locked = model_folder_pref()
            if locked is not None:
                self.report({"ERROR"}, f"Models load only from the Model folder: {locked}")
            else:
                folder = existing_dir(self.directory or self.filepath)
                if folder is None:
                    self.report({"ERROR"}, "No folder or CAST file selected")
                else:
                    self.report({"ERROR"}, f"No LOD0 .cast models in {folder}")
            return {"CANCELLED"}
        last = None
        last_path = None
        first = None
        imported = 0
        shaded = 0
        x = next_import_x(context)
        for path in paths:
            try:
                arm, folder = import_cast_model(context, str(path))
            except Exception as exc:
                self.report({"WARNING"}, f"{path.name}: {exc}")
                continue
            if arm is None:
                continue
            tag_character(arm, folder=folder, cast_path=path)
            if auto_shade():
                try:
                    reports = utils.shade_selected(
                        [arm],
                        current_node_adder(context.scene),
                        folder=folder,
                        finish=len(paths) == 1 and imported == 0,
                    )
                    shaded += sum(1 for r in reports if r.get("wired"))
                except Exception as exc:
                    apply_model_size(arm)
                    hide_rig(arm)
                    self.report({"WARNING"}, f"Imported {arm.name}. Shade skipped: {exc}")
                    log.warning("Shade skipped for %s: %s", arm.name, exc)
                else:
                    if len(paths) > 1:
                        apply_model_size(arm)
                        hide_rig(arm)
            else:
                apply_model_size(arm)
                hide_rig(arm)
            place_imported_character(arm, x)
            x = round(x + IMPORT_GAP, 4)
            if first is None:
                first = arm
            last = arm
            last_path = path
            imported += 1
        if first is not None:
            try:
                view_front_and_frame(context, first)
            except Exception:
                pass
            hide_rig(first)
            deselect_all(context)
        if imported == 0:
            self.report({"ERROR"}, "Nothing imported")
            return {"CANCELLED"}
        set_material_viewport(context)
        anims = 0
        if auto_load_anims():
            try:
                anims = autoload_legend_animations(context, last_path if last is not None else paths[0])
            except Exception as exc:
                log.warning("Animation autoload failed: %s", exc)
                anims = 0
        extra = f", {anims} animation(s)" if anims else ""
        self.report({"INFO"}, f"Imported {imported} model(s), shaded {shaded} mesh(es){extra}")
        return {"FINISHED"}

    def invoke(self, context, event):
        from ..log import existing_dir
        from ..prefs import model_folder_pref, pref

        locked = model_folder_pref()
        raw = str(locked) if locked is not None else str(pref("rsx_export_dir", "") or "").strip()
        folder = existing_dir(raw) if raw else None
        if folder is not None:
            text = str(folder)
            if not text.endswith(("/", "\\")):
                text += "/"
            self.directory = text
            self.filepath = text
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class APEX_OT_upgrade(bpy.types.Operator):
    bl_idname = "apexaddon.upgrade"
    bl_label = "Upgrade"
    bl_description = "Replace this model with the next level CAST (01→02→03→01)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        incoming = character_level(context)
        try:
            arm, path, reports = upgrade_character(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ok = sum(1 for r in reports if r.get("wired"))
        verb = "Downgraded" if incoming == "level03" else "Upgraded"
        self.report({"INFO"}, f"{verb} to {path.stem}, shaded {ok} mesh(es)")
        return {"FINISHED"}


class APEX_PG_anim_item(bpy.types.PropertyGroup):
    name: StringProperty(name="Animation")
    path: StringProperty(name="Path", subtype="FILE_PATH")
    victim_path: StringProperty(name="Victim Path", subtype="FILE_PATH")
    group: StringProperty(name="Group", default="other")
    legend: StringProperty(name="Legend", default="")
    is_header: BoolProperty(name="Header", default=False)
    is_legend: BoolProperty(name="Legend Header", default=False)
    collapsed: BoolProperty(name="Collapsed", default=False)
    indent: bpy.props.IntProperty(name="Indent", default=0)


class APEX_OT_toggle_anim_group(bpy.types.Operator):
    bl_idname = "apexaddon.toggle_anim_group"
    bl_label = "Toggle Animation Group"
    bl_description = "Collapse or expand this animation group"
    bl_options = {"INTERNAL"}
    group: StringProperty(default="")

    def execute(self, context):
        key = self.group
        items = context.scene.apex_anim_items
        for i, item in enumerate(items):
            if item.is_header and item.group == key:
                item.collapsed = not item.collapsed
                context.scene.apex_anim_index = i
                break
        return {"FINISHED"}


def _plain_clip_label(item) -> str:
    from ..naming import clip_display_name

    parts = [part for part in (item.group or "").split(":") if part]
    kind = parts[1] if len(parts) >= 2 and parts[0] != "legend" else ""
    raw = Path(item.path).stem if item.path else (item.name or "")
    if kind in {"idle", "ingame", "select", "other"}:
        return clip_display_name(raw, item.legend or "", kind) or item.name or raw
    return item.name or raw


def _bases_that_keep_zero(labels) -> set[str]:
    """A trailing _0 stays only when the same name also has _1, _2, …"""
    found: dict[str, set[str]] = {}
    for label in labels:
        match = re.search(r"_(\d+)$", label or "")
        if not match:
            continue
        found.setdefault(label[: match.start()], set()).add(match.group(1))
    return {base for base, numbers in found.items() if numbers - {"0"}}


def _kept_zero_bases(data) -> dict[str, set[str]]:
    items = getattr(data, "apex_anim_items", None)
    grouped: dict[str, list[str]] = {}
    for item in items or []:
        if getattr(item, "is_header", False):
            continue
        grouped.setdefault(item.group or "", []).append(_plain_clip_label(item))
    return {group: _bases_that_keep_zero(labels) for group, labels in grouped.items()}


def _clip_row_label(item, kept: set[str] | None = None) -> str:
    """Clean legend and group words. Drop a lone trailing _0."""
    label = _plain_clip_label(item)
    if label.endswith("_0") and (kept is None or label[:-2] not in kept):
        label = label[:-2].rstrip("_ ")
    return label or item.name or ""


class APEX_OT_anim_search(bpy.types.Operator):
    bl_idname = "apexaddon.anim_search"
    bl_label = "Search Poses"
    bl_description = "Search the animation list. A reversed name matches too"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        scene = context.scene
        open_now = not bool(getattr(scene, "apex_anim_search", False))
        scene.apex_anim_search = open_now
        if not open_now:
            scene.apex_anim_query = ""
        return {"FINISHED"}


class APEX_UL_anims(bpy.types.UIList):
    bl_idname = "APEX_UL_anims"

    def draw_filter(self, context, layout):
        # Search lives on the Loop row. Keep this empty so the list has one field.
        return

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        indent = int(getattr(item, "indent", 0) or 0)
        if item.is_header or not item.path:
            tri = "TRIA_RIGHT" if item.collapsed else "TRIA_DOWN"
            row = layout.row(align=True)
            if indent:
                row.separator(factor=indent)
            op = row.operator(
                APEX_OT_toggle_anim_group.bl_idname,
                text=item.name,
                icon=tri,
                emboss=False,
            )
            op.group = item.group
            return
        row = layout.row(align=True)
        row.separator(factor=max(indent, 2))
        row.operator_context = "INVOKE_DEFAULT"
        kept = getattr(self, "_kept_zero", None)
        items = getattr(data, "apex_anim_items", None)
        last = ""
        try:
            last = items[-1].path if items else ""
        except Exception:
            last = ""
        key = (len(items or []), last)
        if getattr(self, "_kept_key", None) != key or kept is None:
            kept = _kept_zero_bases(data)
            self._kept_zero = kept
            self._kept_key = key
        op = row.operator(
            APEX_OT_apply_animation.bl_idname,
            text=_clip_row_label(item, kept.get(item.group or "", set())),
            emboss=False,
            icon="ARMATURE_DATA" if not item.victim_path else "COMMUNITY",
        )
        op.filepath = item.path
        op.victim_path = item.victim_path
        op.legend = item.legend
        op.index = index

    def filter_items(self, context, data, propname):
        from ..naming import anim_query_match

        items = getattr(data, propname)
        show = self.bitflag_filter_item
        scene = getattr(context, "scene", None)
        query = ""
        if scene is not None and bool(getattr(scene, "apex_anim_search", False)):
            query = (getattr(scene, "apex_anim_query", "") or "").strip().lower()
        if not query:
            query = (getattr(self, "filter_name", "") or "").strip().lower()
        flags = []
        collapsed = {item.group for item in items if item.is_header and item.collapsed}

        def ancestors(group: str) -> list[str]:
            parts = [p for p in (group or "").split(":") if p]
            return [":".join(parts[:i]) for i in range(1, len(parts))]

        if query:
            match_groups = set()
            match_legends = set()
            matched = []
            for item in items:
                if item.is_header:
                    matched.append(False)
                    continue
                hay_name = item.name or ""
                hay_path = Path(item.path).stem if item.path else ""
                hit = anim_query_match(query, hay_name, item.legend, hay_path, item.group)
                matched.append(hit)
                if hit:
                    match_groups.add(item.group)
                    match_groups.update(ancestors(item.group))
                    if item.legend:
                        match_legends.add(f"legend:{item.legend}")
            for item, hit in zip(items, matched):
                if item.is_legend and item.group in match_legends:
                    flags.append(show)
                elif item.is_header and item.group in match_groups:
                    flags.append(show)
                elif hit:
                    flags.append(show)
                else:
                    flags.append(0)
            return flags, []
        for item in items:
            if item.is_legend:
                flags.append(show)
                continue
            legend_key = f"legend:{item.legend}" if item.legend else ""
            if legend_key and legend_key in collapsed:
                flags.append(0)
                continue
            hidden = False
            for key in ancestors(item.group):
                if key in collapsed:
                    hidden = True
                    break
            if not item.is_header and item.group in collapsed:
                hidden = True
            flags.append(0 if hidden else show)
        return flags, []


class APEX_OT_toggle_frame(bpy.types.Operator):
    bl_idname = "apexaddon.toggle_frame"
    bl_label = "Aspect"
    bl_description = "Switch the render between 9:16 and 16:9"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .studio import apply_frame_orientation, render_is_portrait
        scene = context.scene
        # Flip the frame that is actually rendering, not a stale checkbox.
        # A fresh 16:9 camera becomes 9:16 on the first click.
        scene.apex_cam_portrait = not render_is_portrait(scene)
        apply_frame_orientation(scene)
        label = "9:16" if scene.apex_cam_portrait else "16:9"
        self.report({"INFO"}, label)
        return {"FINISHED"}


class APEX_OT_add_camera(bpy.types.Operator):
    bl_idname = "apexaddon.add_camera"
    bl_label = "Add Camera"
    bl_description = "Add studio camera and lights on the current 3D viewport look"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = resolve_character(context)
        cam = add_camera_rig(context, obj, snap_view=True)
        self.report({"INFO"}, f"Added {cam.name} on the current viewport")
        return {"FINISHED"}


class APEX_OT_set_camera_pov(bpy.types.Operator):
    bl_idname = "apexaddon.set_camera_pov"
    bl_label = "Lock Model"
    bl_description = "Lock the studio camera on the selected mesh. Click again to unlock"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .studio import focus_object, set_camera_lock
        scene = context.scene
        locked = bool(getattr(scene, "apex_cam_lock", False))
        if locked:
            set_camera_lock(context, False)
            self.report({"INFO"}, "Camera unlocked")
            return {"FINISHED"}
        obj = focus_object(context)
        if obj is None:
            self.report({"ERROR"}, "Select a mesh on the model, or pick one in the list")
            return {"CANCELLED"}
        set_camera_lock(context, True, obj)
        self.report({"INFO"}, f"Camera locked on {obj.name}")
        return {"FINISHED"}



class APEX_OT_nudge_camera(bpy.types.Operator):
    bl_idname = "apexaddon.nudge_camera"
    bl_label = "Nudge Studio Camera"
    bl_description = "Move or rotate the studio camera while looking through it"
    bl_options = {"REGISTER", "UNDO"}

    move: bpy.props.EnumProperty(
        items=(
            ("LEFT", "Left", ""),
            ("RIGHT", "Right", ""),
            ("UP", "Up", ""),
            ("DOWN", "Down", ""),
        ),
        default="UP",
    )
    rotate: bpy.props.BoolProperty(default=False)
    vertical: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        area = getattr(context, "area", None)
        space = getattr(area, "spaces", None)
        space = space.active if space is not None else None
        r3d = getattr(space, "region_3d", None)
        cam = getattr(getattr(context, "scene", None), "camera", None)
        return (
            r3d is not None
            and getattr(r3d, "view_perspective", "") == "CAMERA"
            and cam is not None
            and getattr(cam, "type", "") == "CAMERA"
        )

    def execute(self, context):
        cam = context.scene.camera
        step = 0.08
        if self.rotate:
            angle = 0.04
            cam.rotation_mode = "XYZ"
            if self.move == "LEFT":
                cam.rotation_euler.rotate_axis("Y", angle)
            elif self.move == "RIGHT":
                cam.rotation_euler.rotate_axis("Y", -angle)
            elif self.move == "UP":
                cam.rotation_euler.rotate_axis("X", angle)
            else:
                cam.rotation_euler.rotate_axis("X", -angle)
            return {"FINISHED"}
        if self.vertical:
            delta = Vector((0.0, step if self.move == "UP" else -step, 0.0))
        elif self.move == "LEFT":
            delta = Vector((-step, 0.0, 0.0))
        elif self.move == "RIGHT":
            delta = Vector((step, 0.0, 0.0))
        elif self.move == "UP":
            delta = Vector((0.0, 0.0, -step))
        else:
            delta = Vector((0.0, 0.0, step))
        cam.location += cam.matrix_world.to_3x3() @ delta
        return {"FINISHED"}


_camera_keymaps = []


def register_camera_keys():
    wm = bpy.context.window_manager
    kc = getattr(wm, "keyconfigs", None)
    addon = getattr(kc, "addon", None) if kc is not None else None
    if addon is None:
        return
    km = addon.keymaps.new(name="3D View", space_type="VIEW_3D")
    # Alt+arrows move (plain arrows are eaten while an animation plays).
    # Ctrl+Alt+arrows rotate. Shift+Alt+up/down pedestal.
    binds = (
        ("LEFT", False, False, True),
        ("RIGHT", False, False, True),
        ("UP", False, False, True),
        ("DOWN", False, False, True),
        ("LEFT", True, False, True),
        ("RIGHT", True, False, True),
        ("UP", True, False, True),
        ("DOWN", True, False, True),
        ("UP", False, True, True),
        ("DOWN", False, True, True),
    )
    key_type = {
        "LEFT": "LEFT_ARROW",
        "RIGHT": "RIGHT_ARROW",
        "UP": "UP_ARROW",
        "DOWN": "DOWN_ARROW",
    }
    for direction, ctrl, shift, alt in binds:
        kmi = km.keymap_items.new(
            APEX_OT_nudge_camera.bl_idname,
            key_type[direction],
            "PRESS",
            ctrl=ctrl,
            shift=shift,
            alt=alt,
        )
        kmi.properties.move = direction
        kmi.properties.rotate = ctrl
        kmi.properties.vertical = shift
        _camera_keymaps.append((km, kmi))


def unregister_camera_keys():
    for km, kmi in list(_camera_keymaps):
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _camera_keymaps.clear()

class APEX_OT_pick_anim_folder(bpy.types.Operator):
    bl_idname = "apexaddon.pick_anim_folder"
    bl_label = "Choose Animation Folder"
    bl_description = "Pick the folder and list every .cast animation, including subfolders"
    bl_options = {"REGISTER"}
    directory: StringProperty(name="Directory", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def execute(self, context):
        from .files import picked_anim_dirs
        from ..prefs import anim_folder_pref

        locked = anim_folder_pref()
        names = [getattr(entry, "name", "") or "" for entry in (self.files or [])]
        dirs = picked_anim_dirs(self.directory, names, bpy.path.abspath)
        if locked is not None:
            dirs = [Path(locked)]
        if not dirs:
            self.report({"ERROR"}, "Not a folder")
            return {"CANCELLED"}
        if len(dirs) == 1:
            context.scene.apex_anim_dir = str(dirs[0])
            n = fill_animation_list(context.scene, dirs[0])
            shown = dirs[0]
        else:
            parent = Path(bpy.path.abspath(self.directory)) if self.directory else dirs[0].parent
            context.scene.apex_anim_dir = str(parent)
            n = fill_animation_list(context.scene, sources=[(path, "") for path in dirs])
            shown = parent
        if not n:
            self.report({"ERROR"}, f"No .cast files in {shown}")
            return {"CANCELLED"}
        if locked is not None and self.directory and Path(bpy.path.abspath(self.directory)) != Path(locked):
            self.report({"INFO"}, f"Animations load only from {locked}")
        else:
            self.report({"INFO"}, f"Loaded {n} animation(s)")
        return {"FINISHED"}

    def invoke(self, context, event):
        from ..prefs import anim_folder_pref

        locked = anim_folder_pref()
        if locked is not None:
            text = str(locked)
            if not text.endswith(("/", "\\")):
                text += "/"
            self.directory = text
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


def _victim_legend_items(self, context):
    return (("wraith", "Wraith", ""),)


class APEX_OT_pick_victim_cast(bpy.types.Operator):
    bl_idname = "apexaddon.pick_victim_cast"
    bl_label = "Choose Victim CAST"
    bl_description = "Import a CAST as the finisher victim (model + textures only)"
    bl_options = {"REGISTER", "UNDO"}
    filepath: StringProperty(name="File Path", subtype="FILE_PATH")
    directory: StringProperty(name="Directory", subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_glob: StringProperty(default="*.cast", options={"HIDDEN"})
    attack_anim: StringProperty(name="Attack Anim", options={"HIDDEN"})
    victim_anim: StringProperty(name="Victim Anim", options={"HIDDEN"})

    def invoke(self, context, event):
        from ..prefs import model_folder_pref

        locked = model_folder_pref()
        if locked is not None:
            text = str(locked)
            if not text.endswith(("/", "\\")):
                text += "/"
            self.directory = text
            self.filepath = text
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from ..prefs import model_folder_pref, path_is_under

        path = None
        if self.files:
            root = Path(bpy.path.abspath(self.directory or self.filepath))
            for entry in self.files:
                name = getattr(entry, "name", "") or ""
                if name:
                    path = root / name
                    break
        if path is None and self.filepath:
            path = Path(bpy.path.abspath(self.filepath))
        if path is None or not path.is_file():
            self.report({"ERROR"}, "No .cast file selected")
            return {"CANCELLED"}
        locked = model_folder_pref()
        if locked is not None and not path_is_under(path, locked):
            self.report({"ERROR"}, f"Models load only from the Model folder: {locked}")
            return {"CANCELLED"}
        arm = resolve_character(context)
        if arm is None:
            self.report({"ERROR"}, "No character armature found")
            return {"CANCELLED"}
        try:
            notes = apply_finisher_full(
                context,
                self.attack_anim,
                self.victim_anim,
                arm,
                victim_cast=str(path),
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        redraw_view3d(context)
        if notes:
            self.report({"WARNING"}, notes[0])
        self.report({"INFO"}, f"Finisher victim {path.stem}")
        return {"FINISHED"}


def resolve_character_by_legend(context, legend: str) -> bpy.types.Object | None:
    from ..extras import armature_legend, tagged_armatures

    needle = (legend or "").lower().replace(" ", "")
    if not needle:
        return resolve_character(context)
    matches = [arm for arm in tagged_armatures(context.scene) if armature_legend(arm) == needle]
    if not matches:
        return resolve_character(context)
    active = resolve_character(context)
    if active in matches:
        return active
    return matches[0]


class APEX_OT_apply_animation(bpy.types.Operator):
    bl_idname = "apexaddon.apply_animation"
    bl_label = "Apply Animation"
    bl_description = "Import this CAST animation and play it"
    bl_options = {"REGISTER", "UNDO"}
    filepath: StringProperty(name="Filepath", subtype="FILE_PATH")
    victim_path: StringProperty(name="Victim Path", subtype="FILE_PATH")
    legend: StringProperty(name="Legend", default="")
    specific_victim: BoolProperty(
        name="Specific victim legend?",
        description="Pick a CAST model as the victim",
        default=False,
    )
    keep_legend: BoolProperty(
        name="Keep Legend?",
        description="Keep the already loaded victim legend",
        default=True,
    )
    index: bpy.props.IntProperty(name="Index", default=-1, options={"HIDDEN"})

    def _keep_row(self, context) -> None:
        items = getattr(context.scene, "apex_anim_items", None)
        if items is None:
            return
        if 0 <= self.index < len(items) and not items[self.index].is_header:
            context.scene.apex_anim_index = self.index
            return
        for i, item in enumerate(items):
            if item.is_header or not item.path:
                continue
            if item.path == self.filepath and (item.victim_path or "") == (self.victim_path or ""):
                context.scene.apex_anim_index = i
                return

    def draw(self, context):
        layout = self.layout
        if has_custom_victim(context, resolve_character(context)):
            layout.prop(self, "keep_legend")
        layout.prop(self, "specific_victim")

    def invoke(self, context, event):
        self._keep_row(context)
        if self.victim_path:
            return context.window_manager.invoke_props_dialog(self, width=320)
        return self.execute(context)

    def execute(self, context):
        if not self.filepath:
            return {"CANCELLED"}
        self._keep_row(context)
        arm = resolve_character_by_legend(context, self.legend)
        if arm is None:
            self.report({"ERROR"}, "No character armature found")
            return {"CANCELLED"}
        remember_character(arm)
        custom = has_custom_victim(context, arm)
        try:
            if self.victim_path and self.specific_victim:
                return bpy.ops.apexaddon.pick_victim_cast(
                    "INVOKE_DEFAULT",
                    attack_anim=self.filepath,
                    victim_anim=self.victim_path,
                )
            if self.victim_path:
                keep = bool(custom and self.keep_legend)
                notes = apply_finisher_full(
                    context,
                    self.filepath,
                    self.victim_path,
                    arm,
                    force_base=not keep and custom,
                )
                if notes:
                    self.report({"WARNING"}, notes[0])
            else:
                _purge_victim_characters(context)
                apply_cast_animation(context, self.filepath, arm)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        redraw_view3d(context)
        clip = Path(self.filepath).stem
        from .files import clip_should_autoplay

        plays = clip_should_autoplay(self.filepath)
        if self.victim_path:
            self.report(
                {"INFO"},
                "Playing finisher" if plays else "Finisher loaded (under 200KB, not playing)",
            )
        else:
            self.report(
                {"INFO"},
                f"Playing {clip}" if plays else f"Loaded {clip} (under 200KB, not playing)",
            )
        return {"FINISHED"}


class APEX_OT_anim_play(bpy.types.Operator):
    bl_idname = "apexaddon.anim_play"
    bl_label = "Play"
    bl_description = "Play or pause"
    bl_options = {"REGISTER"}

    def execute(self, context):
        playing = bool(context.screen.is_animation_playing)
        if playing:
            bpy.ops.screen.animation_play()
            restore_studio_camera(context)
        else:
            arm = resolve_character(context)
            bpy.ops.screen.animation_play()
            refresh_studio_camera(context)
        redraw_view3d(context)
        return {"FINISHED"}


class APEX_OT_anim_stop(bpy.types.Operator):
    bl_idname = "apexaddon.anim_stop"
    bl_label = "Reset"
    bl_description = "Stop playback, restore studio camera, return to the first frame"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        context.scene.frame_set(context.scene.frame_start)
        restore_studio_camera(context)
        restore_showcase_resolution(context.scene)
        redraw_view3d(context)
        return {"FINISHED"}


class APEX_OT_anim_delete(bpy.types.Operator):
    bl_idname = "apexaddon.anim_delete"
    bl_label = "Delete Animation"
    bl_description = "Remove the loaded animation and reset the pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = resolve_character(context)
        if arm is None:
            self.report({"ERROR"}, "No character armature found")
            return {"CANCELLED"}
        clear_animation(context, arm)
        view_front_and_frame(context, arm)
        deselect_all(context)
        self.report({"INFO"}, f"Cleared animation on {arm.name}")
        return {"FINISHED"}


class APEX_OT_camera_preset(bpy.types.Operator):
    bl_idname = "apexaddon.camera_preset"
    bl_label = "Camera Preset"
    bl_description = "Front / 3-4 / close-up starting pose (camera stays free to move)"
    bl_options = {"REGISTER", "UNDO"}
    preset: StringProperty(default="front")

    def execute(self, context):
        apply_camera_preset(context, self.preset)
        redraw_view3d(context)
        self.report({"INFO"}, f"Camera preset: {self.preset.replace('_', ' ')}")
        return {"FINISHED"}


class APEX_OT_focus_character(bpy.types.Operator):
    bl_idname = "apexaddon.focus_character"
    bl_label = "Focus Character"
    bl_description = "Make this character the active one and load its texture folder"
    bl_options = {"REGISTER"}
    target: StringProperty(default="")

    def execute(self, context):
        from ..extras import CHAR_TEX

        obj = bpy.data.objects.get(self.target)
        if obj is None:
            self.report({"ERROR"}, "Character not found")
            return {"CANCELLED"}
        remember_character(obj)
        tex = obj.get(CHAR_TEX, "")
        if tex:
            context.scene.apex_texture_dir = str(tex)
        make_armature_active(context, obj)
        view_front_and_frame(context, obj)
        return {"FINISHED"}


SHOWCASE_CAM = "Apex Showcase"
SHOWCASE_COLL = "Apex Showcase"


def _set_linear_fcurves(obj) -> None:
    ad = getattr(obj, "animation_data", None)
    if ad is None or ad.action is None:
        return
    curves = []
    action = ad.action
    raw = getattr(action, "fcurves", None)
    if raw:
        curves.extend(list(raw))
    try:
        slot = getattr(ad, "action_slot", None)
        for layer in getattr(action, "layers", []) or []:
            for strip in getattr(layer, "strips", []) or []:
                bag = None
                if hasattr(strip, "channelbag") and callable(strip.channelbag):
                    try:
                        bag = strip.channelbag(slot) if slot is not None else None
                    except Exception:
                        bag = None
                if bag is None:
                    bags = getattr(strip, "channelbags", None)
                    if bags:
                        bag = bags[0]
                if bag is not None:
                    curves.extend(list(getattr(bag, "fcurves", []) or []))
    except Exception:
        pass
    for fc in curves:
        try:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
        except Exception:
            continue


SHOWCASE_RES_X = "apex_showcase_prev_res_x"
SHOWCASE_RES_Y = "apex_showcase_prev_res_y"
SHOWCASE_RES_PCT = "apex_showcase_prev_res_pct"
SHOWCASE_SAVED = "apex_showcase_res_saved"


def _save_showcase_resolution(scene) -> None:
    if scene.get(SHOWCASE_SAVED):
        return
    scene[SHOWCASE_RES_X] = int(scene.render.resolution_x)
    scene[SHOWCASE_RES_Y] = int(scene.render.resolution_y)
    scene[SHOWCASE_RES_PCT] = int(getattr(scene.render, "resolution_percentage", 100) or 100)
    scene[SHOWCASE_SAVED] = True


def restore_showcase_resolution(scene) -> None:
    if scene is None or not scene.get(SHOWCASE_SAVED):
        return
    try:
        if SHOWCASE_RES_X in scene:
            scene.render.resolution_x = int(scene[SHOWCASE_RES_X])
        if SHOWCASE_RES_Y in scene:
            scene.render.resolution_y = int(scene[SHOWCASE_RES_Y])
        if SHOWCASE_RES_PCT in scene and hasattr(scene.render, "resolution_percentage"):
            scene.render.resolution_percentage = int(scene[SHOWCASE_RES_PCT])
    except Exception:
        pass
    for key in (SHOWCASE_RES_X, SHOWCASE_RES_Y, SHOWCASE_RES_PCT, SHOWCASE_SAVED):
        try:
            del scene[key]
        except Exception:
            pass


def start_showcase(context, apply_portrait=True):
    from ..extras import tagged_armatures

    arms = tagged_armatures(context.scene)
    if not arms:
        raise RuntimeError("Import at least one model first.")
    n = len(arms)
    end_x = (n - 1) * IMPORT_GAP
    scene = context.scene
    cam = bpy.data.objects.get(SHOWCASE_CAM)
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        data = bpy.data.cameras.new(SHOWCASE_CAM)
        cam = bpy.data.objects.new(SHOWCASE_CAM, data)
        col = bpy.data.collections.get(SHOWCASE_COLL)
        if col is None:
            col = bpy.data.collections.new(SHOWCASE_COLL)
            scene.collection.children.link(col)
        if cam.name not in col.objects:
            col.objects.link(cam)
    cam.data.type = "PERSP"
    cam.data.lens = 80.0
    cam.data.show_passepartout = True
    cam.data.passepartout_alpha = 1.0
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (0.0, 0.0, 0.0)
    cam.location = (0.0, 1.0, 5.0)
    # Always apply temporary portrait resolution; restored on modal end / ESC / Reset.
    _save_showcase_resolution(scene)
    scene.render.resolution_x = 1080
    scene.render.resolution_y = 1920
    fps = int(scene.render.fps) or 24
    frames = max(int(round(max(n - 1, 1) * 2 * fps)), fps)
    scene.frame_start = 1
    scene.frame_end = frames
    try:
        if cam.animation_data:
            cam.animation_data_clear()
    except Exception:
        pass
    cam.location = (0.0, 1.0, 5.0)
    cam.keyframe_insert(data_path="location", index=0, frame=1)
    cam.location = (end_x, 1.0, 5.0)
    cam.keyframe_insert(data_path="location", index=0, frame=frames)
    _set_linear_fcurves(cam)
    scene.camera = cam
    for window in context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space is not None and getattr(space, "region_3d", None) is not None:
                space.region_3d.view_perspective = "CAMERA"
    scene.frame_set(1)
    if not context.screen.is_animation_playing:
        bpy.ops.screen.animation_play()
    return cam, n, frames


class APEX_OT_showcase(bpy.types.Operator):
    bl_idname = "apexaddon.showcase"
    bl_label = "Start Showcase"
    bl_description = "Pan the camera along imported models (temporary 1080x1920, 80mm). Previous resolution is restored when the showcase ends."
    bl_options = {"REGISTER", "UNDO"}
    _timer = None
    _end_frame = 0
    _watching = False

    def execute(self, context):
        try:
            cam, n, frames = start_showcase(context, apply_portrait=True)
        except Exception as exc:
            restore_showcase_resolution(context.scene)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self._end_frame = frames
        self._watching = True
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, f"Showcase {n} model(s) on {cam.name} ({frames} frames)")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        playing = bool(getattr(context.screen, "is_animation_playing", False))
        done = False
        if event.type in {"ESC"}:
            try:
                if playing:
                    bpy.ops.screen.animation_cancel(restore_frame=False)
            except Exception:
                pass
            done = True
        elif event.type == "TIMER":
            frame = int(getattr(context.scene, "frame_current", 0) or 0)
            if not playing or frame >= self._end_frame:
                done = True
        if done:
            self._finish_modal(context)
            return {"FINISHED"}
        return {"PASS_THROUGH"}

    def _finish_modal(self, context):
        wm = context.window_manager
        if self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        restore_showcase_resolution(context.scene)

    def cancel(self, context):
        self._finish_modal(context)


anim_classes = (
    APEX_OT_import_cast,
    APEX_OT_upgrade,
    APEX_PG_anim_item,
    APEX_OT_toggle_anim_group,
    APEX_OT_anim_search,
    APEX_UL_anims,
    APEX_OT_add_camera,
    APEX_OT_toggle_frame,
    APEX_OT_set_camera_pov,
    APEX_OT_nudge_camera,
    APEX_OT_camera_preset,
    APEX_OT_focus_character,
    APEX_OT_pick_anim_folder,
    APEX_OT_pick_victim_cast,
    APEX_OT_apply_animation,
    APEX_OT_anim_play,
    APEX_OT_anim_stop,
    APEX_OT_anim_delete,
    APEX_OT_showcase,
)
