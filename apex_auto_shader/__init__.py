bl_info = {
    "name": "Apex Auto Shader",
    "description": "Auto-shade Apex Legends CAST models (requires CAST importer)",
    "author": "Kyfolam (original: Kaiserouo)",
    "version": (2, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Apex Shader / Object Context Menu",
    "doc_url": "https://github.com/Kyfolam/Apex-Auto-Shader",
    "category": "Material",
}

import importlib
import os

import bpy

from . import (
    anim,
    blender_compat,
    config,
    constants,
    extras,
    log,
    menu,
    menu_apex,
    naming,
    node_adder,
    pack,
    panel,
    prefs,
    shade,
    utils,
)
from .anim import apply as anim_apply
from .anim import character as anim_character
from .anim import clips as anim_clips
from .anim import const as anim_const
from .anim import studio as anim_studio
from .naming import anim as naming_anim
from .naming import tex as naming_tex

_MODULES = (
    log,
    constants,
    naming_anim,
    naming_tex,
    naming,
    config,
    blender_compat,
    prefs,
    node_adder,
    shade.extras,
    shade.utils,
    extras,
    utils,
    anim_const,
    anim_character,
    anim_clips,
    anim_studio,
    anim_apply,
    anim,
    pack,
    panel,
    menu_apex,
    menu,
)

_RELOAD = (
    bool(getattr(bpy.app, "debug", False))
    or os.environ.get("APEX_AUTO_SHADER_RELOAD", "").strip().lower() in {"1", "true", "yes"}
)
if _RELOAD:
    for _mod in _MODULES:
        importlib.reload(_mod)


def register():
    menu.register()


def unregister():
    menu.unregister()


if __name__ == "__main__":
    register()
