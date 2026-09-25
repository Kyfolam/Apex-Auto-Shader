"""Animation / import / studio camera — split for maintainability; public API unchanged."""
from __future__ import annotations

from pathlib import Path

import bpy
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

        paths = _gather_import_casts(self.directory, self.filepath, self.files)
        if not paths:
            folder = existing_dir(self.directory or self.filepath)
            if folder is None:
                self.report({"ERROR"}, "No folder or CAST file selected")
            else:
                self.report({"ERROR"}, f"No LOD0 .cast models in {folder}")
            return {"CANCELLED"}
        adder = current_node_adder(context.scene)
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
                        [arm], adder, folder=folder, finish=len(paths) == 1 and imported == 0
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


class APEX_UL_anims(bpy.types.UIList):
    bl_idname = "APEX_UL_anims"

    def draw_filter(self, context, layout):
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon="VIEWZOOM")

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
        op = row.operator(
            APEX_OT_apply_animation.bl_idname,
            text=item.name,
            emboss=False,
            icon="ARMATURE_DATA" if not item.victim_path else "COMMUNITY",
        )
        op.filepath = item.path
        op.victim_path = item.victim_path
        op.legend = item.legend

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        show = self.bitflag_filter_item
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
                hay = f"{item.name} {item.legend} {Path(item.path).stem}".lower()
                hit = query in hay
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


class APEX_OT_add_camera(bpy.types.Operator):
    bl_idname = "apexaddon.add_camera"
    bl_label = "Add Camera"
    bl_description = "Add a studio camera and lights at a starting pose (not locked — move it freely)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = resolve_character(context)
        cam = add_camera_rig(context, obj)
        self.report({"INFO"}, f"Added {cam.name} and studio lights")
        return {"FINISHED"}


class APEX_OT_set_camera_pov(bpy.types.Operator):
    bl_idname = "apexaddon.set_camera_pov"
    bl_label = "Set Camera POV"
    bl_description = "Lock the camera to jx_c_camera, aiming at jx_c_pov (portrait 1080×1920)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            apply_camera_pov(context, create=True)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        redraw_view3d(context)
        fov = detect_cast_camera_fov(resolve_character(context))
        if fov:
            self.report({"INFO"}, f"Camera POV locked, portrait (FOV {fov:.0f}° from CAST)")
        else:
            self.report({"INFO"}, "Camera POV locked to jx_c_camera → jx_c_pov (portrait)")
        return {"FINISHED"}


class APEX_OT_pick_anim_folder(bpy.types.Operator):
    bl_idname = "apexaddon.pick_anim_folder"
    bl_label = "Choose Animation Folder"
    bl_description = "Pick the folder and list every .cast animation"
    bl_options = {"REGISTER"}
    directory: StringProperty(name="Directory", options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def execute(self, context):
        context.scene.apex_anim_dir = self.directory
        folder = Path(bpy.path.abspath(self.directory))
        if not folder.is_dir():
            self.report({"ERROR"}, "Not a folder")
            return {"CANCELLED"}
        n = fill_animation_list(context.scene, folder)
        if not n:
            self.report({"ERROR"}, f"No .cast files in {folder}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Loaded {n} animation(s)")
        return {"FINISHED"}

    def invoke(self, context, event):
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
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
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

    def draw(self, context):
        layout = self.layout
        if has_custom_victim(context, resolve_character(context)):
            layout.prop(self, "keep_legend")
        layout.prop(self, "specific_victim")

    def invoke(self, context, event):
        if self.victim_path:
            return context.window_manager.invoke_props_dialog(self, width=320)
        return self.execute(context)

    def execute(self, context):
        if not self.filepath:
            return {"CANCELLED"}
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
        if self.victim_path:
            self.report({"INFO"}, "Playing finisher")
        else:
            self.report({"INFO"}, f"Playing {clip}")
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
        hide_rig(arm)
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
        hide_rig(obj)
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
    APEX_UL_anims,
    APEX_OT_add_camera,
    APEX_OT_set_camera_pov,
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
