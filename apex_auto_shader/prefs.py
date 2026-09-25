from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from .log import log

SHADER_ITEMS = (
    ("plus", "Apex Shader+", "ovlack Apex Shader+"),
    ("cores", "Cores Apex Shader", "CoReArtZz Cores shader"),
    ("object", "Object Shader", "Props / non-legend models — textures from the model folder"),
)

CAST_URL = "https://github.com/dtzxporter/cast"
OPTIC_URL = "https://github.com/Kyfolam/Optic-Enhancer"


def addon_prefs():
    try:
        addons = bpy.context.preferences.addons
    except Exception:
        return None
    pkg = __package__ or "apex_auto_shader"
    try:
        if pkg in addons:
            return addons[pkg].preferences
    except Exception:
        pass
    try:
        for key in addons.keys():
            if str(key).endswith("apex_auto_shader"):
                return addons[key].preferences
    except Exception:
        pass
    return None


def pref(name: str, default):
    prefs = addon_prefs()
    if prefs is None:
        return default
    try:
        return getattr(prefs, name, default)
    except Exception:
        return default


def model_scale() -> float:
    try:
        return max(0.001, min(1.0, float(pref("model_scale", 0.025))))
    except (TypeError, ValueError):
        return 0.025


def auto_shade() -> bool:
    return bool(pref("auto_shade", True))


def auto_load_anims() -> bool:
    return bool(pref("auto_load_anims", True))


def default_shader() -> str:
    key = str(pref("default_shader", "plus") or "plus")
    return key if key in {"plus", "cores", "object"} else "plus"


def anim_loop_default() -> bool:
    return bool(pref("anim_loop", True))


def hide_higher_lods_pref() -> bool:
    return bool(pref("hide_higher_lods", True))


def post_shade_orient() -> bool:
    return bool(pref("post_shade_orient", True))


def post_shade_hide_rig() -> bool:
    return bool(pref("post_shade_hide_rig", True))


def post_shade_frame_view() -> bool:
    return bool(pref("post_shade_frame_view", True))



def cast_importer_available() -> bool:
    try:
        return hasattr(bpy.ops.import_scene, "cast")
    except Exception:
        return False


def notify_missing_cast() -> None:
    if cast_importer_available():
        return
    log.warning("CAST importer not found. Install dtzxporter/cast (%s)", CAST_URL)
    try:
        wm = bpy.context.window_manager
        if wm is None:
            return

        def _draw(menu, _context):
            layout = menu.layout
            layout.label(text="CAST importer not found.")
            layout.label(text="Install dtzxporter/cast, then restart Blender.")

        wm.popup_menu(_draw, title="Apex Auto Shader", icon="ERROR")
    except Exception:
        pass



def optic_enhancer_available() -> bool:
    """True when Optic Enhancer addon/extension is enabled (soft check)."""
    try:
        addons = bpy.context.preferences.addons
    except Exception:
        return False
    needles = ("optic_enhancer", "optic-enhancer", "Optic_Enhancer")
    try:
        for key in addons.keys():
            s = str(key).replace("-", "_").lower()
            if s.endswith("optic_enhancer") or "optic_enhancer" in s:
                return True
    except Exception:
        pass
    return False


class APEX_OT_uninstall(bpy.types.Operator):
    bl_idname = "apexaddon.uninstall"
    bl_label = "Uninstall"
    bl_description = "Disable and remove Apex Auto Shader"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        pkg = __package__ or "apex_auto_shader"

        def _uninstall():
            try:
                bpy.ops.preferences.addon_disable(module=pkg)
            except Exception:
                pass
            try:
                bpy.ops.extensions.package_uninstall(
                    repo="user_default", pkg_id="apex_auto_shader"
                )
            except Exception:
                try:
                    bpy.ops.preferences.addon_remove(module=pkg)
                except Exception:
                    pass
            return None

        try:
            bpy.app.timers.register(_uninstall, first_interval=0.25)
        except Exception:
            _uninstall()
        self.report({"INFO"}, "Uninstalling Apex Auto Shader…")
        return {"FINISHED"}


class ApexAutoShaderPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    default_shader: EnumProperty(
        name="Default Shader",
        items=SHADER_ITEMS,
        default="plus",
    )
    model_scale: FloatProperty(
        name="Model Scale",
        description="Applied after CAST import / shade",
        default=0.025,
        min=0.001,
        max=1.0,
        step=0.1,
        precision=4,
    )
    auto_shade: BoolProperty(
        name="Auto-shade on import",
        description="Wire textures after Import CAST Model(s)",
        default=True,
    )
    auto_load_anims: BoolProperty(
        name="Auto-load legend animations",
        description="Fill the animation list from animseq when the legend is known",
        default=True,
    )
    anim_loop: BoolProperty(
        name="Loop animations",
        description="Default for the Loop toggle on new scenes",
        default=True,
    )

    hide_higher_lods: BoolProperty(
        name="Hide higher LODs",
        description="Hide LOD1+ meshes when shading (keep LOD0 only)",
        default=True,
    )
    post_shade_orient: BoolProperty(
        name="Orient after shade",
        description="Apply model scale after shading (XYZ Euler stays 0°)",
        default=True,
    )
    post_shade_hide_rig: BoolProperty(
        name="Hide rig after shade",
        description="Hide the armature after shading (meshes stay visible)",
        default=True,
    )
    post_shade_frame_view: BoolProperty(
        name="Frame view after shade",
        description="Frame the camera on the character after shading",
        default=True,
    )


    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text="Auto-shade Apex Legends Models")
        row.operator(APEX_OT_uninstall.bl_idname, text="Uninstall", icon="TRASH")
        layout.prop(self, "default_shader")
        layout.prop(self, "model_scale")
        layout.prop(self, "auto_shade")
        layout.prop(self, "auto_load_anims")
        layout.prop(self, "anim_loop")
        layout.prop(self, "hide_higher_lods")
        box_post = layout.box()
        box_post.label(text="After shade")
        box_post.prop(self, "post_shade_orient")
        box_post.prop(self, "post_shade_hide_rig")
        box_post.prop(self, "post_shade_frame_view")
        box = layout.box()
        if cast_importer_available():
            box.label(text="CAST importer: found", icon="CHECKMARK")
        else:
            box.label(text="CAST importer: missing", icon="ERROR")
            box.label(text="Install dtzxporter/cast")
        box_oe = layout.box()
        if optic_enhancer_available():
            box_oe.label(text="Optic Enhancer: found", icon="CHECKMARK")
        else:
            box_oe.label(text="Optic Enhancer: optional companion not found", icon="INFO")
            box_oe.label(text="Look expansion pack (creases, wear, glow, portrait)")
            box_oe.label(text=OPTIC_URL)
