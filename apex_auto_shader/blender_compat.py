from __future__ import annotations

from pathlib import Path

import bpy

from .log import log
from .naming import strip_blender_suffix


def ignore_rna(exc: BaseException, what: str) -> None:
    if isinstance(exc, (ReferenceError, KeyError, AttributeError, RuntimeError, TypeError)):
        log.debug("%s: %s", what, exc)
        return
    log.debug("%s: %s", what, exc)


def resolve_armature(obj: bpy.types.Object | None) -> bpy.types.Object | None:
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    if obj.type == "MESH":
        try:
            arm = obj.find_armature()
        except (ReferenceError, AttributeError) as exc:
            ignore_rna(exc, "find_armature")
            arm = None
        if arm is not None:
            return arm
    cursor = obj
    try:
        while cursor.parent is not None:
            cursor = cursor.parent
            if cursor.type == "ARMATURE":
                return cursor
    except (ReferenceError, AttributeError) as exc:
        ignore_rna(exc, "walk parent armature")
    return None


def deselect_objects(context=None) -> None:
    ctx = context or bpy.context
    selected = list(getattr(ctx, "selected_objects", []) or [])
    for obj in selected:
        try:
            obj.select_set(False)
        except (ReferenceError, RuntimeError) as exc:
            ignore_rna(exc, "deselect")
    try:
        ctx.view_layer.objects.active = None
    except (AttributeError, RuntimeError) as exc:
        ignore_rna(exc, "clear active")


def id_alive(id_data) -> bool:
    if id_data is None:
        return False
    try:
        id_data.name
        return True
    except ReferenceError:
        return False


def socket(node, name: str):
    try:
        return node.inputs[name]
    except (KeyError, TypeError, AttributeError):
        found = find_socket(node, name)
        if found is not None:
            return found
        raise RuntimeError(f'Socket "{name}" not found on {getattr(node, "name", node)}')


def find_socket(node, *names):
    for name in names:
        try:
            sock = node.inputs[name]
        except (KeyError, TypeError, AttributeError):
            continue
        if not getattr(sock, "is_linked", False):
            return sock
    for name in names:
        try:
            return node.inputs[name]
        except (KeyError, TypeError, AttributeError):
            continue
    return None


def link(tree, from_sock, to_sock) -> bool:
    if from_sock is None or to_sock is None:
        return False
    try:
        tree.links.new(from_sock, to_sock)
        return True
    except Exception as exc:
        log.debug("Link skipped: %s", exc)
        return False


def new_tex_image(nodes, img_path, location=(0.0, 0.0), noncolor: bool = False, packed_alpha: bool = False):
    node = nodes.new("ShaderNodeTexImage")
    node.location = location
    path = Path(img_path)
    image = None
    try:
        image = bpy.data.images.load(str(path), check_existing=True)
    except Exception as exc:
        log.warning("Could not load image %s: %s", path, exc)
    if image is not None:
        node.image = image
        if packed_alpha:
            try:
                image.alpha_mode = "CHANNEL_PACKED"
            except Exception:
                pass
        if noncolor and getattr(image, "colorspace_settings", None) is not None:
            for name in ("Non-Color", "Non-Colour Data", "Raw"):
                try:
                    image.colorspace_settings.name = name
                    break
                except Exception:
                    continue
    return node


def set_alpha_clip(mat: bpy.types.Material) -> None:
    for attr, value in (
        ("blend_method", "CLIP"),
        ("shadow_method", "CLIP"),
        ("surface_render_method", "DITHERED"),
        ("use_backface_culling", True),
        ("alpha_threshold", 0.5),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except Exception:
                pass


def set_alpha_blend(mat: bpy.types.Material) -> None:
    for attr, value in (
        ("blend_method", "BLEND"),
        ("shadow_method", "NONE"),
        ("surface_render_method", "BLENDED"),
        ("use_backface_culling", False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except Exception:
                pass


def set_alpha_hashed(mat: bpy.types.Material) -> None:
    for attr, value in (
        ("blend_method", "HASHED"),
        ("shadow_method", "HASHED"),
        ("surface_render_method", "DITHERED"),
        ("use_backface_culling", False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except Exception:
                pass
    if getattr(mat, "blend_method", "") not in {"HASHED", "BLEND", "CLIP"}:
        set_alpha_blend(mat)


def ensure_material_tree(mat: bpy.types.Material):
    mat.use_nodes = True
    tree = mat.node_tree
    if tree is None:
        mat.use_nodes = True
        tree = mat.node_tree
    return tree


def object_source_name(obj: bpy.types.Object | None) -> str:
    if obj is None:
        return ""
    return strip_blender_suffix(obj.name)


def material_meshes(obj: bpy.types.Object | None) -> list:
    if obj is None:
        return []
    if obj.type == "MESH":
        return [obj]
    meshes: list = []
    children = getattr(obj, "children_recursive", None)
    pool = list(children) if children is not None else list(getattr(obj, "children", []))
    for child in pool:
        if getattr(child, "type", "") == "MESH":
            meshes.append(child)
    if obj.type == "ARMATURE":
        for other in list(bpy.data.objects):
            if getattr(other, "type", "") != "MESH":
                continue
            try:
                if other.find_armature() != obj:
                    continue
                parent = other.parent
                while parent is not None and parent.type != "ARMATURE":
                    parent = parent.parent
                if parent is not None and parent != obj:
                    continue
                if other not in meshes:
                    meshes.append(other)
            except Exception:
                continue
    return meshes
