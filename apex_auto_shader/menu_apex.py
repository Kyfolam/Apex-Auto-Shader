from __future__ import annotations

import bpy

from . import utils
from .naming import SLOT_LABELS
from .cinematic import CinematicNodeAdder
from .node_adder import (
    CoresNodeAdder,
    PlusNodeAdder,
    PlusSENodeAdder,
    current_node_adder,
    shader_key_for,
)


def makeRemoveTextureSelectedClass(texture_type: str):
    label = SLOT_LABELS.get(texture_type, texture_type)

    class ApexRemoveTextureSelectedOp(bpy.types.Operator):
        bl_idname = f"apexaddon.remove_texture_{texture_type}"
        bl_label = f"Remove {label}"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            n = utils.remove_texture_selected(context.selected_objects, texture_type)
            self.report({"INFO"}, f"Removed {n} {texture_type} node(s)")
            return {"FINISHED"}

    ApexRemoveTextureSelectedOp.bl_label = f"Remove {label}"
    return ApexRemoveTextureSelectedOp


removable_texture_ls = [
    "albedo",
    "ao",
    "cavity",
    "emissive",
    "gloss",
    "normal",
    "spec",
    "opacity",
    "scatter",
    "aniso",
    "ehl",
]

remove_texture_class_ls = [makeRemoveTextureSelectedClass(t) for t in removable_texture_ls]


class ApexRemoveTextureSubmenu(bpy.types.Menu):
    bl_idname = "OBJECT_MT_apex_remove_texture_submenu"
    bl_label = "Remove Texture From Selected"

    def draw(self, context):
        layout = self.layout
        for rm_cls in remove_texture_class_ls:
            layout.operator(rm_cls.bl_idname)


def makeChooseShaderOptionOperator(idname, display_name, node_adder_cls_arg, description):
    class ApexChooseShaderOptionOp(bpy.types.Operator):
        bl_idname = f"apexaddon.choose_shader_{idname.lower()}"
        bl_label = display_name
        bl_description = description
        bl_options = {"REGISTER"}
        node_adder_cls = node_adder_cls_arg

        def execute(self, context):
            context.scene.apex_shader = shader_key_for(self.node_adder_cls)
            return {"FINISHED"}

    return ApexChooseShaderOptionOp


available_shaders = [
    ("plus_se", "se Apex Shader Plus", PlusSENodeAdder, "se_Apex Shader Plus (default)"),
    ("plus", "Apex Shader+", PlusNodeAdder, "ovlack Apex Shader+ (Plus 1)"),
    ("cores", "Cores Apex Shader", CoresNodeAdder, "CoReArtZz Cores shader"),
    ("cinematic", "Cinematic Shader", CinematicNodeAdder, "Illustrated hard light, ink edge, cool rim"),
]

shader_op_ls = [
    makeChooseShaderOptionOperator(idname, display_name, cls, desc)
    for idname, display_name, cls, desc in available_shaders
]


class ApexChooseShaderSubmenu(bpy.types.Menu):
    bl_idname = "OBJECT_MT_apex_choose_shader_submenu"
    bl_label = "Choose Shader"
    bl_description = "Choose the shader you want to use"

    def draw(self, context):
        layout = self.layout
        current = current_node_adder()
        for shader_op_cls in shader_op_ls:
            if current == shader_op_cls.node_adder_cls:
                layout.operator(shader_op_cls.bl_idname, text=f"{shader_op_cls.bl_label} (selected)")
            else:
                layout.operator(shader_op_cls.bl_idname)


class ApexSubmenu(bpy.types.Menu):
    bl_idname = "OBJECT_MT_apex_shade_submenu"
    bl_label = "Apex Shader"

    def draw(self, context):
        layout = self.layout
        layout.operator("apexaddon.import_cast")
        layout.operator("apexaddon.apply_shader")
        layout.operator("apexaddon.recolor")
        layout.separator()
        layout.operator("apexaddon.clean_scene")
        layout.separator()
        layout.menu(ApexRemoveTextureSubmenu.bl_idname)
        layout.separator()
        layout.menu(ApexChooseShaderSubmenu.bl_idname)


apex_classes = (
    *remove_texture_class_ls,
    ApexRemoveTextureSubmenu,
    *shader_op_ls,
    ApexChooseShaderSubmenu,
    ApexSubmenu,
)


def apex_menu_func(self, context):
    self.layout.menu(ApexSubmenu.bl_idname)
