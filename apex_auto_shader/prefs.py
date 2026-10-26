from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from .log import existing_dir, log

SHADER_ITEMS = (
    ("plus_se", "se Apex Shader Plus", "se_Apex Shader Plus (default)"),
    ("plus", "Apex Shader+", "ovlack Apex Shader+ (Plus 1)"),
    ("cores", "Cores Apex Shader", "CoReArtZz Cores shader"),
    ("cinematic", "Cinematic Shader", "Illustrated hard light, ink edge, cool rim"),
)
SHADER_KEYS = {item[0] for item in SHADER_ITEMS}

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


def favorite_key(legend: str, name: str) -> str:
    return f"{(legend or '').strip().lower()}|{(name or '').strip().lower()}"


def favorite_set() -> set[str]:
    raw = str(pref("favorite_skins", "") or "")
    return {line.strip().lower() for line in raw.splitlines() if "|" in line}


def toggle_favorite(legend: str, name: str) -> bool:
    """Return True when the skin is now a favorite."""
    key = favorite_key(legend, name)
    keys = favorite_set()
    enabled = key not in keys
    if enabled:
        keys.add(key)
    else:
        keys.discard(key)
    prefs = addon_prefs()
    if prefs is not None:
        prefs.favorite_skins = "\n".join(sorted(keys))
    return enabled


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
    key = str(pref("default_shader", "plus_se") or "plus_se")
    return key if key in SHADER_KEYS else "plus_se"


def _on_default_shader_update(self, context):
    """Scenes that were never picked in the UI follow this preference."""
    try:
        from .node_adder import sync_unset_scenes

        sync_unset_scenes()
    except Exception:
        pass


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


def path_is_under(path, root) -> bool:
    """True when path is root or a file/folder inside it."""
    try:
        child = Path(path).resolve()
        base = Path(root).resolve()
    except Exception:
        return False
    if child == base:
        return True
    try:
        child.relative_to(base)
        return True
    except ValueError:
        return False


def _folder_pref(name: str):
    """Return a set preference folder. Missing paths still lock the search."""
    raw = str(pref(name, "") or "").strip()
    if not raw:
        return None
    found = existing_dir(raw)
    if found is not None:
        return found
    from .log import safe_path

    return safe_path(raw)


def model_folder_pref():
    """Set folder = models load only from here. Empty = no lock."""
    return _folder_pref("model_dir")


def anim_folder_pref():
    """Set folder = animations load only from here. Empty = search as usual."""
    return _folder_pref("anim_dir")


def prop_folder_pref():
    """Set folder = the Prop panel lists guns only from here. Empty = no lock."""
    return _folder_pref("prop_dir")


def _on_prop_dir_update(self, context):
    """Preference is a starting folder. A path already chosen in the panel stays."""
    folder = prop_folder_pref()
    if folder is None:
        return
    scenes = []
    try:
        scenes = list(bpy.data.scenes)
    except Exception:
        scene = getattr(context, "scene", None)
        if scene is not None:
            scenes = [scene]
    for scene in scenes:
        try:
            if not str(getattr(scene, "apex_prop_dir", "") or ""):
                scene.apex_prop_dir = str(folder)
        except Exception:
            pass


def _tagged_arms(context):
    try:
        from .shade.extras import tagged_armatures
    except Exception:
        return []
    scene = getattr(context, "scene", None)
    try:
        return list(tagged_armatures(scene))
    except Exception:
        return []


def _on_model_scale_update(self, context):
    try:
        scale = max(0.001, min(1.0, float(getattr(self, "model_scale", 0.025))))
    except (TypeError, ValueError):
        return
    for arm in _tagged_arms(context):
        try:
            arm.scale = (scale, scale, scale)
        except Exception:
            pass


def _on_anim_loop_update(self, context):
    value = bool(getattr(self, "anim_loop", True))
    scenes = []
    try:
        scenes = list(bpy.data.scenes)
    except Exception:
        scene = getattr(context, "scene", None)
        if scene is not None:
            scenes = [scene]
    for scene in scenes:
        try:
            scene.apex_anim_loop = value
        except Exception:
            pass


def _on_hide_lods_update(self, context):
    hide = bool(getattr(self, "hide_higher_lods", True))
    try:
        from .shade.extras import hide_higher_lods, reveal_higher_lods
    except Exception:
        return
    for arm in _tagged_arms(context):
        try:
            if hide:
                hide_higher_lods(arm)
            else:
                reveal_higher_lods(arm)
        except Exception:
            pass


def _on_hide_rig_update(self, context):
    hide = bool(getattr(self, "post_shade_hide_rig", True))
    try:
        from .shade.utils import set_rig_hidden
    except Exception:
        return
    for arm in _tagged_arms(context):
        try:
            set_rig_hidden(arm, hide)
        except Exception:
            pass


def _on_model_dir_update(self, context):
    folder = model_folder_pref()
    if folder is None or context is None:
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        scene.apex_model_dir = str(folder)
    except Exception:
        pass


def _on_anim_dir_update(self, context):
    folder = anim_folder_pref()
    if folder is None or context is None:
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        if str(getattr(scene, "apex_anim_dir", "") or "") != str(folder):
            scene.apex_anim_dir = str(folder)
            return
    except Exception:
        return
    try:
        from .anim.clips import fill_animation_list

        fill_animation_list(scene, folder)
    except Exception:
        pass



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
    bl_description = "Disable Apex Auto Shader and remove the add-on"
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
        default="plus_se",
        update=_on_default_shader_update,
    )
    model_scale: FloatProperty(
        name="Model Scale",
        description="Applied to imported characters. Changing it rescales the current ones",
        default=0.025,
        min=0.001,
        max=1.0,
        step=0.1,
        precision=4,
        update=_on_model_scale_update,
    )
    auto_shade: BoolProperty(
        name="Auto-shade on import",
        description="Wire textures after Import CAST Model(s)",
        default=True,
    )
    auto_load_anims: BoolProperty(
        name="Auto-load legend animations",
        description="Fill the animation list when a legend is imported",
        default=True,
    )
    anim_loop: BoolProperty(
        name="Loop animations",
        description="Loop clips. Applies to open scenes immediately",
        default=True,
        update=_on_anim_loop_update,
    )

    hide_higher_lods: BoolProperty(
        name="Hide higher LODs",
        description="Hide LOD1+ meshes. Applies to the current character immediately",
        default=True,
        update=_on_hide_lods_update,
    )
    post_shade_orient: BoolProperty(
        name="Orient after shade",
        description="Apply model scale after shading (XYZ Euler stays 0°)",
        default=True,
    )
    post_shade_hide_rig: BoolProperty(
        name="Hide bones",
        description="Hide armature bones. Turn off to show them now, on the current model",
        default=True,
        update=_on_hide_rig_update,
    )
    post_shade_frame_view: BoolProperty(
        name="Frame view after shade",
        description="Frame the camera on the character after shading",
        default=True,
    )
    rsx_export_dir: StringProperty(
        name="RSX export folder",
        description=(
            "Folder RSX exports into. Find Skins starts here when Model folder is empty"
        ),
        subtype="DIR_PATH",
        default="",
    )
    model_dir: StringProperty(
        name="Model folder",
        description="Optional. If set, Import CAST and Find Skins load models only from this folder",
        subtype="DIR_PATH",
        default="",
        update=_on_model_dir_update,
    )
    anim_dir: StringProperty(
        name="Animation folder",
        description="Optional. If set, animations load only from this folder",
        subtype="DIR_PATH",
        default="",
        update=_on_anim_dir_update,
    )
    prop_dir: StringProperty(
        name="Prop folder",
        description="Optional. If set, the Prop panel lists guns only from this folder",
        subtype="DIR_PATH",
        default="",
        update=_on_prop_dir_update,
    )
    favorite_skins: StringProperty(
        name="Favorite skins",
        description="Find Skins favorites. One legend|name per line",
        default="",
        options={"HIDDEN"},
    )


    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text="Auto-shade Apex Legends Models")
        row = layout.row(align=True)
        row.operator("apexaddon.install_zip", text="Install ZIP", icon="IMPORT")
        row.operator(APEX_OT_uninstall.bl_idname, text="Uninstall", icon="TRASH")
        layout.prop(self, "default_shader")
        layout.prop(self, "rsx_export_dir")
        layout.prop(self, "model_dir")
        layout.prop(self, "anim_dir")
        layout.prop(self, "prop_dir")
        layout.prop(self, "model_scale")
        layout.prop(self, "auto_shade")
        layout.prop(self, "auto_load_anims")
        layout.prop(self, "anim_loop")
        layout.prop(self, "post_shade_hide_rig")
        box_post = layout.box()
        box_post.label(text="After shade")
        box_post.prop(self, "post_shade_orient")
        box_post.prop(self, "post_shade_frame_view")
