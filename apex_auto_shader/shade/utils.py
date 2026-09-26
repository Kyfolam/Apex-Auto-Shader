from __future__ import annotations

from pathlib import Path
from typing import Iterable

import bpy

from ..blender_compat import (
    ensure_material_tree,
    find_socket,
    link,
    material_meshes,
    object_source_name,
    resolve_armature,
    set_alpha_blend,
    set_alpha_clip,
    set_alpha_hashed,
)
from ..log import existing_dir, log
from ..naming import (
    LEVEL_CODES,
    TextureRef,
    cycle_recolor_code,
    eye_hash_kind,
    find_texture_folder,
    guess_bodypart,
    is_glass_family,
    is_hash_kit_mesh,
    is_legend_character_name,
    is_numeric_filler_mesh,
    is_recolor_code,
    is_transparent_family,
    last_name_token,
    list_folder_recolors,
    mesh_level,
    mesh_slot_prefix,
    missing_slots,
    is_eye_material,
    identity_level,
    model_dir_name,
    parse_skin_identity,
    overlay_match,
    prefer_textures,
    scan_folder,
    scan_object_folder,
    scan_recolor_stack,
    should_hide_base_hair,
    skin_prefix,
    split_mesh_variant,
    split_recolor_prefix,
    texture_dir_name_from_cast,
    texture_folder_candidates,
)
from ..node_adder import NodeAdder, is_object_shader


def _armature_recolor(obj) -> str:
    from .extras import CHAR_RECOLOR, CHAR_TAG

    arm = resolve_armature(obj) if obj is not None else None
    sources = []
    if arm is not None:
        sources.append(str(arm.get(CHAR_RECOLOR, "") or ""))
        sources.extend(
            [
                str(arm.get(CHAR_TAG, "") or ""),
                str(arm.get("apex_cast_path", "") or ""),
                arm.name,
            ]
        )
    if obj is not None:
        sources.append(getattr(obj, "name", "") or "")
    for src in sources:
        if not src:
            continue
        _mesh, code = split_mesh_variant(src)
        if code:
            return code
        _base, rc = split_recolor_prefix(src)
        if rc:
            return rc
        if is_recolor_code(src):
            return src.lower()
    return ""


def detect_prefix(obj: bpy.types.Object | None, scene=None) -> str:
    from .extras import CHAR_CAST, CHAR_TAG

    sources = []
    arm = resolve_armature(obj) if obj is not None else None
    if arm is not None:
        sources.extend([arm.get(CHAR_CAST, ""), arm.get(CHAR_TAG, ""), arm.name])
    if obj is not None:
        sources.append(object_source_name(obj))
    object_mode = is_object_shader(scene)
    for source in sources:
        if not source:
            continue
        raw = Path(str(source)).name
        if object_mode or not is_legend_character_name(raw):
            pref = model_dir_name(raw) or skin_prefix(raw)
        else:
            pref = skin_prefix(raw)
        if pref:
            return pref
    return ""


def _unique_slot_textures(textures: Iterable[TextureRef]) -> list[TextureRef]:
    by_slot: dict[str, TextureRef] = {}
    leftover: list[TextureRef] = []
    for tex in textures:
        if tex.slot:
            if tex.slot not in by_slot:
                by_slot[tex.slot] = tex
        else:
            leftover.append(tex)
    return list(by_slot.values()) + leftover


def _scan_shade_match(
    folder: Path,
    prefix: str,
    extra_names: list[str],
    select_level: str,
    object_mode: bool,
    recolor_code: str = "",
):
    if object_mode:
        match = scan_object_folder(folder, prefix)
        if match.textures:
            return match
        alt = model_dir_name(prefix)
        if alt and alt != prefix:
            match = scan_object_folder(folder, alt)
            if match.textures:
                return match
        return match
    _base, embedded = split_recolor_prefix(prefix)
    mesh, variant = split_mesh_variant(prefix)
    code = (recolor_code or embedded or "").lower()
    if not code and variant:
        code = variant
    parse_prefix = _base or prefix
    if variant and not is_recolor_code(variant):
        overlay = scan_recolor_stack(
            folder,
            prefix,
            apply_recolor=False,
            target_level=select_level,
            source_name=extra_names[0] if extra_names else "",
        )
        if not overlay.textures:
            overlay = scan_folder(folder, prefix)
        base = scan_recolor_stack(
            folder,
            mesh,
            apply_recolor=False,
            target_level=select_level,
            source_name=extra_names[0] if extra_names else "",
        )
        if not base.textures:
            base = scan_folder(folder, mesh)
        if overlay.textures and base.textures:
            match = overlay_match(base, overlay)
        elif overlay.textures:
            match = overlay
        else:
            match = base
    else:
        match = scan_recolor_stack(
            folder,
            parse_prefix,
            apply_recolor=bool(code),
            recolor_code=code or None,
            target_level=select_level,
            source_name=extra_names[0] if extra_names else "",
        )
    if not match.textures:
        match = scan_folder(folder, parse_prefix, recolor_code=code or None)
    if not match.textures:
        match = scan_object_folder(folder, prefix)
    if not match.textures:
        alt = model_dir_name(prefix)
        if alt and alt != prefix:
            match = scan_object_folder(folder, alt)
    return match


def detect_texture_folder(obj: bpy.types.Object | None, scene=None) -> Path | None:
    scene = scene or getattr(bpy.context, "scene", None)
    from .extras import CHAR_CAST, CHAR_RECOLOR, folder_for

    tagged = folder_for(obj, scene)
    prefix = detect_prefix(obj, scene)
    recolor = _armature_recolor(obj)
    if tagged is not None and not recolor:
        return tagged

    candidates: list[Path] = []
    if tagged is not None:
        candidates.append(tagged)
    casts: list[Path] = []
    if obj is not None:
        arm = resolve_armature(obj)
        stored = (arm.get(CHAR_CAST) if arm is not None else "") or ""
        if stored:
            casts.append(Path(stored))
    if scene is not None:
        scene_cast = getattr(scene, "apex_cast_path", "") or ""
        if scene_cast:
            casts.append(Path(bpy.path.abspath(scene_cast)))
    for cast in casts:
        hit = find_texture_folder(cast, recolor_code=recolor)
        if hit is not None:
            return hit
        candidates.extend(texture_folder_candidates(cast))

    if obj is not None:
        src = object_source_name(obj)
        folder_name = texture_dir_name_from_cast(src) if src else ""
        blend = Path(bpy.path.abspath("//")) if bpy.data.filepath else None
        roots = []
        if blend and blend.is_dir():
            roots.extend([blend, blend.parent])
        if folder_name:
            for root in roots:
                candidates.extend(
                    [
                        root / folder_name,
                        root / "Textures" / folder_name,
                        root / "textures" / folder_name,
                    ]
                )
        if src:
            dummy = Path(src + ".cast")
            if blend and blend.is_dir():
                candidates.extend(texture_folder_candidates(blend / dummy.name))

    for mesh in material_meshes(obj) if obj else []:
        mat = mesh.active_material
        if mat is None or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type != "TEX_IMAGE" or node.image is None:
                continue
            try:
                img_path = existing_dir(Path(bpy.path.abspath(node.image.filepath)).parent)
            except Exception:
                continue
            if img_path is not None:
                candidates.append(img_path)

    blend = Path(bpy.path.abspath("//")) if bpy.data.filepath else None
    if blend and blend.is_dir():
        candidates.extend(
            [
                blend,
                blend / "_images",
                blend / "textures",
                blend / "images",
            ]
        )

    seen = set()
    for folder in candidates:
        key = str(folder)
        if key in seen:
            continue
        seen.add(key)
        if not folder.is_dir():
            continue
        if prefix:
            hit = scan_folder(folder, prefix, recolor_code=recolor or None)
            if hit.textures:
                return folder
            hit = scan_folder(folder, prefix)
            if hit.textures:
                return folder
        else:
            if any(p.suffix.lower() == ".png" for p in folder.iterdir() if p.is_file()):
                return folder
    return candidates[0] if candidates else None


def mesh_match_names(mesh: bpy.types.Object) -> list[str]:
    names: list[str] = []
    if mesh.active_material:
        names.append(mesh.active_material.name)
    for slot in mesh.data.materials:
        if slot and slot.name not in names:
            names.append(slot.name)
    names.append(mesh.name)
    return names


def hide_object(obj: bpy.types.Object) -> None:
    try:
        obj.hide_set(True)
    except Exception:
        pass
    obj.hide_render = True


def hide_rig(obj: bpy.types.Object | None) -> None:
    if obj is None:
        return
    arm = obj if obj.type == "ARMATURE" else None
    if arm is None and obj.type == "MESH":
        arm = obj.find_armature()
        if arm is None:
            cursor = obj
            while cursor.parent is not None:
                cursor = cursor.parent
                if cursor.type == "ARMATURE":
                    arm = cursor
                    break
    if arm is not None:
        try:
            arm.hide_viewport = False
        except Exception:
            pass
        hide_object(arm)
        try:
            bpy.context.scene.apex_character = arm.name
        except Exception:
            pass


def mesh_has_eye_material(mesh: bpy.types.Object) -> bool:
    mats = [m for m in mesh.data.materials if m]
    active = mesh.active_material
    if active is not None and active not in mats:
        mats.append(active)
    if any(is_eye_material(m.name) for m in mats):
        return True
    if eye_hash_kind(mesh.name):
        return True
    return is_eye_material(mesh.name)


def hide_numeric_filler_if_needed(mesh: bpy.types.Object) -> bool:
    if not is_numeric_filler_mesh(mesh.name):
        return False
    hide_object(mesh)
    log.info("Hide %s (numeric id mesh)", mesh.name)
    return True


def _mesh_legend(mesh: bpy.types.Object) -> str:
    from .extras import CHAR_CAST, CHAR_TAG

    sources = []
    arm = resolve_armature(mesh)
    if arm is not None:
        sources.extend([arm.get(CHAR_CAST, ""), arm.get(CHAR_TAG, ""), arm.name])
    sources.extend([object_source_name(mesh), mesh.name])
    for source in sources:
        if not source:
            continue
        ident = parse_skin_identity(str(source))
        if ident.legend:
            return ident.legend
    return ""


def _eye_kind(mesh: bpy.types.Object) -> str:
    hashed = eye_hash_kind(mesh.name)
    if hashed:
        return hashed
    names = mesh_match_names(mesh)
    for name in names:
        hashed = eye_hash_kind(name)
        if hashed:
            return hashed
        token = last_name_token(name)
        if token == "eyeshadow":
            return "eyeshadow"
        if token == "eyecornea":
            return "eyecornea"
    return "eyecornea"


def _find_wraith_eye_image(*tokens: str) -> Path | None:
    from .. import config

    folder = config.WRAITH_EYE_DIR
    if not folder.is_dir():
        return None
    wanted = [t.lower() for t in tokens]
    ranked: list[tuple[int, Path]] = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".png", ".tga", ".jpg", ".jpeg"}:
            continue
        stem = path.stem.lower()
        if all(tok in stem for tok in wanted):
            ranked.append((len(stem), path))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1]


def _new_color_nodes(nodes, invert=True):
    try:
        sep = nodes.new("ShaderNodeSeparateColor")
    except Exception:
        sep = nodes.new("ShaderNodeSeparateRGB")
    try:
        comb = nodes.new("ShaderNodeCombineColor")
    except Exception:
        comb = nodes.new("ShaderNodeCombineRGB")
    inv = None
    if invert:
        try:
            inv = nodes.new("ShaderNodeInvertColor")
        except Exception:
            inv = nodes.new("ShaderNodeInvert")
    return sep, comb, inv


def _try_link(tree, src, dst) -> None:
    from ..blender_compat import link

    try:
        link(tree, src, dst)
    except (RuntimeError, KeyError, TypeError, AttributeError) as exc:
        from ..blender_compat import ignore_rna

        ignore_rna(exc, "link socket")


def _wire_plus_eye_normal(tree, nodes, group, nrm) -> None:
    from ..blender_compat import find_socket, link

    sep, comb, inv = _new_color_nodes(nodes)
    sep.location = (-480.0, -160.0)
    comb.location = (-120.0, -160.0)
    link(tree, nrm.outputs["Color"], sep.inputs[0])
    _try_link(tree, sep.outputs["Red"], comb.inputs["Red"])
    green_src = sep.outputs["Green"] if "Green" in sep.outputs else sep.outputs[1]
    blue_src = sep.outputs["Blue"] if "Blue" in sep.outputs else sep.outputs[2]
    if inv is not None:
        inv.location = (-300.0, -220.0)
        try:
            inv.inputs[0].default_value = 1.0
        except (KeyError, TypeError, AttributeError):
            pass
        color_in = inv.inputs["Color"] if "Color" in inv.inputs else inv.inputs[1]
        _try_link(tree, green_src, color_in)
        green_out = inv.outputs["Color"] if "Color" in inv.outputs else inv.outputs[0]
        green_dst = comb.inputs["Green"] if "Green" in comb.inputs else comb.inputs[1]
        _try_link(tree, green_out, green_dst)
    else:
        _try_link(tree, green_src, comb.inputs["Green"])
    _try_link(tree, blue_src, comb.inputs["Blue"] if "Blue" in comb.inputs else comb.inputs[2])
    nrm_in = find_socket(group, "Normal Map", "Normal")
    link(tree, comb.outputs["Color"] if "Color" in comb.outputs else comb.outputs[0], nrm_in)
    alpha_in = find_socket(
        group,
        "Alpha (Opacity Multiply)",
        "Alpha//OpacityMult",
        "Opacity Multiply",
        "Alpha",
    )
    if alpha_in is not None:
        try:
            alpha_in.default_value = 0.1
        except (TypeError, AttributeError):
            pass


def apply_alter_plus_eye(mesh: bpy.types.Object, mat: bpy.types.Material) -> bool:
    from ..blender_compat import find_socket, link, new_tex_image
    from ..node_adder import current_node_adder

    kind = _eye_kind(mesh)
    albedo = _find_wraith_eye_image(kind, "albedo") or _find_wraith_eye_image(kind, "col")
    if albedo is None:
        return False
    normal = None
    if kind == "eyecornea":
        normal = (
            _find_wraith_eye_image("eyecornea", "normal")
            or _find_wraith_eye_image("eyecornea", "nml")
        )
        if normal is None:
            return False
    tree = ensure_material_tree(mat)
    nodes = tree.nodes
    nodes.clear()
    group = nodes.new("ShaderNodeGroup")
    group.node_tree = current_node_adder().getShaderNodeGroup()
    group.location = (360.0, 0.0)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (620.0, 0.0)
    link(tree, group.outputs[0], output.inputs["Surface"])
    col = new_tex_image(nodes, albedo, (-420.0, 80.0), noncolor=False, packed_alpha=True)
    albedo_in = find_socket(group, "Albedo")
    link(tree, col.outputs["Color"], albedo_in)
    if kind == "eyeshadow":
        alpha_in = find_socket(
            group,
            "Alpha (Opacity Multiply)",
            "Alpha//OpacityMult",
            "Opacity Multiply",
            "Alpha",
        )
        link(tree, col.outputs["Alpha"], alpha_in)
        set_alpha_blend(mat)
    elif normal is not None:
        nrm = new_tex_image(nodes, normal, (-720.0, -160.0), noncolor=True)
        _wire_plus_eye_normal(tree, nodes, group, nrm)
    log.info("Plus eye (%s) on %s", kind, mesh.name)
    return True


def _apply_glass_eye(mat: bpy.types.Material) -> None:
    tree = ensure_material_tree(mat)
    nodes = tree.nodes
    links = tree.links
    nodes.clear()
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (-280.0, 80.0)
    glass = nodes.new("ShaderNodeBsdfGlass")
    glass.location = (-280.0, -80.0)
    try:
        glass.distribution = "BECKMANN"
    except Exception:
        pass
    try:
        glass.inputs["Roughness"].default_value = 0.0
    except Exception:
        pass
    try:
        glass.inputs["IOR"].default_value = 0.085
    except Exception:
        pass
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (40.0, 0.0)
    mix.inputs[0].default_value = 0.085
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (280.0, 0.0)
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(glass.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], output.inputs["Surface"])
    set_alpha_blend(mat)


def apply_eye_shader(mesh: bpy.types.Object) -> None:
    try:
        mesh.hide_set(False)
        mesh.hide_viewport = False
        mesh.hide_render = False
    except Exception:
        pass
    mats = [m for m in mesh.data.materials if m is not None]
    if mesh.active_material is not None and mesh.active_material not in mats:
        mats.append(mesh.active_material)
    if not mats:
        mat = bpy.data.materials.new(name=f"{mesh.name}_eye")
        mesh.data.materials.append(mat)
        mesh.active_material = mat
        mats = [mat]
    prefer_plus = _mesh_legend(mesh) == "alter" or bool(eye_hash_kind(mesh.name))
    for mat in mats:
        if prefer_plus:
            try:
                if apply_alter_plus_eye(mesh, mat):
                    continue
            except Exception as exc:
                log.warning("Plus eye shader skipped: %s", exc)
        _apply_glass_eye(mat)
        log.info("Eye shader on %s (%s)", mesh.name, mat.name)


def hide_duplicate_hair(root: bpy.types.Object) -> None:
    meshes = material_meshes(root)
    names = []
    for mesh in meshes:
        names.append(mesh.name)
        names.extend(m.name for m in mesh.data.materials if m)
    if not should_hide_base_hair(names):
        return
    for mesh in meshes:
        tokens = [last_name_token(mesh.name)]
        tokens.extend(last_name_token(m.name) for m in mesh.data.materials if m)
        if "hair" in tokens and "hair02" not in tokens:
            hide_object(mesh)
            log.info("Hide %s (hair replaced by hair02)", mesh.name)


def _cast_identity_names(obj) -> list[str]:
    """Armature/CAST filenames only — never mesh bodypart names (level03 leftover)."""
    from .extras import CHAR_CAST, CHAR_TAG

    names: list[str] = []
    arm = resolve_armature(obj) if obj is not None else None
    if arm is not None:
        names.extend(
            [
                str(arm.get(CHAR_CAST, "") or ""),
                str(arm.get(CHAR_TAG, "") or ""),
                arm.name,
            ]
        )
    return names


def _scan_target_level(prefix: str, *extra_names: str) -> str:
    found = identity_level(prefix, *extra_names)
    if found in LEVEL_CODES:
        return found
    try:
        from ..anim import character_level

        level = character_level(bpy.context)
        if level in LEVEL_CODES:
            return level
    except Exception:
        pass
    return ""


def _connect_albedo_alpha(mat, group, textures) -> None:
    albedo = next((t for t in textures if t.slot == "albedo"), None)
    if albedo is None or mat.node_tree is None:
        return
    want = Path(albedo.path).name.lower()
    img_node = None
    for node in mat.node_tree.nodes:
        if getattr(node, "type", "") != "TEX_IMAGE" or node.image is None:
            continue
        fp = (getattr(node.image, "filepath", "") or node.image.name or "").lower()
        if want in fp or Path(albedo.filename).name.lower() in fp:
            img_node = node
            break
    if img_node is None:
        return
    alpha_in = find_socket(
        group,
        "Alpha (Opacity Multiply)",
        "Alpha//OpacityMult",
        "Opacity Multiply",
        "Alpha",
    )
    if alpha_in is None or getattr(alpha_in, "is_linked", False):
        return
    link(mat.node_tree, img_node.outputs.get("Alpha"), alpha_in)


def shade_material(
    mat: bpy.types.Material,
    node_adder_cls: type[NodeAdder],
    textures: Iterable[TextureRef],
    bodypart: str | None = None,
    alpha_hashed: bool = False,
) -> int:
    tree = ensure_material_tree(mat)
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    cas_node_group = nodes.new(type="ShaderNodeGroup")
    cas_node_group.node_tree = node_adder_cls.getShaderNodeGroup()
    cas_node_group.location = (400.0, 0.0)
    output_node = nodes.new(type="ShaderNodeOutputMaterial")
    output_node.location = (700.0, 0.0)
    links.new(cas_node_group.outputs[0], output_node.inputs[0])

    wired = 0
    has_opacity = False
    for i, tex in enumerate(textures):
        ok = node_adder_cls.addImageTexture(
            Path(tex.path), mat, cas_node_group, (0.0, -70.0 * i)
        )
        flag = "O" if ok else "X"
        log.info("Add %s (%s) %s", tex.filename, tex.slot or tex.slot_raw, flag)
        if ok:
            wired += 1
            if tex.slot == "opacity":
                has_opacity = True
    if has_opacity:
        set_alpha_clip(mat)
    elif (
        alpha_hashed
        or is_glass_family(bodypart or "")
        or is_transparent_family(bodypart or "")
    ):
        set_alpha_hashed(mat)
        _connect_albedo_alpha(mat, cas_node_group, textures)
    return wired


def shade_mesh(
    mesh: bpy.types.Object,
    node_adder_cls: type[NodeAdder],
    folder: Path | None = None,
    prefix: str | None = None,
    match: object | None = None,
) -> dict:
    log.info("Shade mesh %s", mesh.name)
    from .extras import adder_for_bodypart, prefix_conflict_message, should_skip_lod

    if should_skip_lod(mesh):
        hide_object(mesh)
        log.info("Hide %s (LOD > 0)", mesh.name)
        return {
            "mesh": mesh.name,
            "bodypart": None,
            "wired": 0,
            "total": 0,
            "hidden": True,
        }
    if hide_numeric_filler_if_needed(mesh):
        return {
            "mesh": mesh.name,
            "bodypart": None,
            "wired": 0,
            "total": 0,
            "hidden": True,
        }
    if mesh_has_eye_material(mesh):
        apply_eye_shader(mesh)
        return {
            "mesh": mesh.name,
            "bodypart": "eye",
            "wired": 1,
            "total": 1,
            "hidden": False,
            "missing": [],
        }
    scene = bpy.context.scene
    prefix = prefix or detect_prefix(mesh, scene)
    folder = folder or detect_texture_folder(mesh, scene)
    if folder is None:
        expected = texture_dir_name_from_cast(object_source_name(mesh))
        hint = f" Expected a folder named '{expected}'." if expected else ""
        raise RuntimeError(
            f"No texture folder for '{mesh.name}'.{hint} "
            "Use Choose Texture Folder, or keep PNGs next to the CAST (filename without _LOD0)."
        )
    if not prefix:
        raise RuntimeError(
            f"Could not read a CAST prefix from '{mesh.name}'. "
            "Select the imported armature or a mesh named after the CAST file."
        )

    extra = _cast_identity_names(mesh)
    select_level = _scan_target_level(prefix, *extra)
    object_mode = is_object_shader(scene, node_adder_cls)
    recolor = _armature_recolor(mesh)
    if match is None or not getattr(match, "textures", None):
        match = _scan_shade_match(
            folder, prefix, extra, select_level, object_mode, recolor_code=recolor
        )
    if not match.textures:
        raise RuntimeError(prefix_conflict_message(folder, prefix))

    bodypart = guess_bodypart(mesh_match_names(mesh), match.bodyparts())
    named_level = mesh_level(mesh.name)

    def _pick(bp: str) -> list:
        if not bp:
            return []
        return prefer_textures(
            match.textures,
            bp,
            select_level,
            recolor_code=getattr(match, "recolor_code", "") or "",
            allow_same_folder_leftover=True,
            mesh_level_tiebreak=named_level,
        )

    textures0 = _pick(bodypart) if bodypart else []
    kit_unmatched = (
        is_hash_kit_mesh(mesh.name)
        or mesh_slot_prefix(mesh.name) == "kit"
        or (bodypart or "") in {"kit"}
        or str(bodypart or "").endswith("_kit")
    )
    if (bodypart is None or not textures0) and kit_unmatched and not textures0:
        hide_object(mesh)
        log.info("Hide %s (unmatched kit)", mesh.name)
        return {
            "mesh": mesh.name,
            "bodypart": bodypart or "kit",
            "wired": 0,
            "total": 0,
            "hidden": True,
        }
    parts = match.bodyparts()
    if not textures0:
        if len(parts) == 1:
            bodypart = parts[0]
            textures0 = _pick(bodypart)
        elif object_mode or not is_legend_character_name(prefix):
            bodypart = bodypart or (parts[0] if parts else "object")
            textures0 = _unique_slot_textures(match.textures)
    if bodypart is None and textures0:
        bodypart = parts[0] if parts else "object"
    if bodypart is None:
        raise RuntimeError(
            f"Could not match mesh '{mesh.name}' to a body part. "
            f"Known parts: {', '.join(match.bodyparts()) or '(none)'}"
        )

    mats = [m for m in mesh.data.materials if m is not None]
    if mesh.active_material is not None and mesh.active_material not in mats:
        mats.append(mesh.active_material)
    if not mats:
        mat = bpy.data.materials.new(name=f"{prefix}_{bodypart}")
        mesh.data.materials.append(mat)
        mesh.active_material = mat
        mats = [mat]

    adder = node_adder_cls or adder_for_bodypart(scene, bodypart)
    wired = 0
    total = 0
    have: list[str] = []
    parts_used: list[str] = []
    for mat in mats:
        slot_names = [mat.name, mesh.name]
        slot_bp = guess_bodypart(slot_names, match.bodyparts()) or bodypart
        mat = uniquify_material(mesh, mat, prefix, slot_bp)
        textures = _pick(slot_bp)
        if not textures:
            textures = textures0
        hashed = is_glass_family(slot_bp) or is_transparent_family(slot_bp)
        wired += shade_material(
            mat, adder, textures, bodypart=slot_bp, alpha_hashed=hashed
        )
        total += len(textures)
        have.extend(t.slot for t in textures if t.slot)
        if slot_bp not in parts_used:
            parts_used.append(slot_bp)
    return {
        "mesh": mesh.name,
        "bodypart": ", ".join(parts_used) if parts_used else bodypart,
        "wired": wired,
        "total": total,
        "missing": missing_slots(have),
        "slots": have,
    }


def shade_armature(
    armature: bpy.types.Object,
    node_adder_cls: type[NodeAdder],
    folder: Path | None = None,
    prefix: str | None = None,
    match: object | None = None,
) -> list[dict]:
    log.info("Shade armature %s", armature.name)
    scene = bpy.context.scene
    prefix = prefix or detect_prefix(armature, scene)
    folder = folder or detect_texture_folder(armature, scene)
    if folder is None:
        raise RuntimeError("No texture folder. Set it in the Apex Shader panel.")
    if not prefix:
        hint = ""
        if folder is not None:
            from ..naming import iter_texture_files, suggest_prefixes_from_names

            found = suggest_prefixes_from_names(p.name for p in iter_texture_files(folder))
            if found:
                hint = f" Folder looks like: {', '.join(found[:4])}."
        raise RuntimeError(
            "Could not read a CAST prefix from the armature name." + hint
        )

    extra = _cast_identity_names(armature)
    select_level = _scan_target_level(prefix, *extra)
    object_mode = is_object_shader(scene, node_adder_cls)
    recolor = _armature_recolor(armature)
    if match is None:
        match = _scan_shade_match(
            folder, prefix, extra, select_level, object_mode, recolor_code=recolor
        )
    reports = []
    meshes = material_meshes(armature)
    from .extras import hide_higher_lods

    hide_higher_lods(armature)
    hide_duplicate_hair(armature)
    for i, mesh in enumerate(meshes):
        log.info("Shade %s (%s/%s)", mesh.name, i, len(meshes))
        try:
            reports.append(
                shade_mesh(mesh, node_adder_cls, folder=folder, prefix=prefix, match=match)
            )
        except Exception as exc:
            log.warning("Skip %s: %s", mesh.name, exc)
            reports.append(
                {"mesh": mesh.name, "bodypart": None, "wired": 0, "total": 0, "error": str(exc)}
            )
    return reports


def shade_selected(
    objects: Iterable[bpy.types.Object],
    node_adder_cls: type[NodeAdder],
    folder: Path | None = None,
    prefix: str | None = None,
    match: object | None = None,
    finish: bool = True,
) -> list[dict]:
    reports: list[dict] = []
    for obj in objects:
        if obj.type == "ARMATURE":
            reports.extend(
                shade_armature(
                    obj, node_adder_cls, folder=folder, prefix=prefix, match=match
                )
            )
        elif obj.type == "MESH":
            try:
                reports.append(
                    shade_mesh(
                        obj, node_adder_cls, folder=folder, prefix=prefix, match=match
                    )
                )
            except Exception as exc:
                reports.append(
                    {"mesh": obj.name, "bodypart": None, "wired": 0, "total": 0, "error": str(exc)}
                )
        else:
            log.warning("%s is not a mesh or armature", obj.name)
    if finish:
        _finish_shade(objects, reports, folder)
    return reports


def _finish_shade(
    objects: Iterable[bpy.types.Object],
    reports: list[dict] | None = None,
    folder: Path | None = None,
) -> None:
    from ..anim import apply_model_size, deselect_all, view_front_and_frame
    from .extras import store_status
    from ..prefs import post_shade_frame_view, post_shade_hide_rig, post_shade_orient

    context = bpy.context
    scene = getattr(context, "scene", None)
    if reports is not None and scene is not None:
        store_status(scene, reports, folder)
    do_orient = post_shade_orient()
    do_hide = post_shade_hide_rig()
    do_frame = post_shade_frame_view()
    framed = None
    sized: set[str] = set()
    for obj in objects:
        if obj is None:
            continue
        arm = resolve_armature(obj)
        if arm is not None and arm.name not in sized:
            if do_orient:
                apply_model_size(arm)
            hide_duplicate_hair(arm)
            if do_hide:
                hide_rig(obj)
            sized.add(arm.name)
            if framed is None:
                framed = arm
        else:
            if do_hide:
                hide_rig(obj)
    if framed is not None:
        if do_frame:
            view_front_and_frame(context, framed)
        if do_hide:
            hide_rig(framed)
        deselect_all(context)
        for mesh in material_meshes(framed):
            if not mesh.hide_get():
                context.view_layer.objects.active = mesh
                break


def uniquify_material(mesh, mat, prefix: str, bodypart: str):
    if mat is None:
        return mat
    arm = None
    try:
        arm = mesh.find_armature()
    except Exception:
        pass
    shared = False
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj == mesh:
            continue
        if mat not in list(obj.data.materials):
            continue
        other = None
        try:
            other = obj.find_armature()
        except Exception:
            pass
        if other is not None and arm is not None and other != arm:
            shared = True
            break
    if not shared:
        return mat
    copy = mat.copy()
    copy.name = f"{prefix}_{bodypart}"
    for i, slot in enumerate(mesh.data.materials):
        if slot == mat:
            mesh.data.materials[i] = copy
    mesh.active_material = copy
    log.info("Unique material %s for %s", copy.name, mesh.name)
    return copy


def recolorSelected(
    objects: Iterable[bpy.types.Object],
    node_adder_cls: type[NodeAdder],
    folder: Path | None = None,
) -> tuple[str, list[dict]]:
    from ..anim import deselect_all, remember_character, resolve_character

    objs = [o for o in objects if o is not None]
    arm = None
    for obj in objs:
        arm = resolve_armature(obj)
        if arm is not None:
            break
    if arm is None:
        arm = resolve_character(bpy.context)
    if arm is None:
        raise RuntimeError("Select the character armature first.")
    remember_character(arm)
    scene = bpy.context.scene
    folder = folder or detect_texture_folder(arm, scene)
    if folder is None:
        raise RuntimeError("No texture folder. Set it in the Apex Shader panel.")
    prefix = detect_prefix(arm, scene)
    if not prefix:
        raise RuntimeError("Could not read a CAST prefix from the model name.")
    from .extras import CHAR_RECOLOR, CHAR_TAG

    available = list_folder_recolors(folder, prefix)
    current = str(arm.get(CHAR_RECOLOR, "") or "")
    nxt = cycle_recolor_code(available, current)
    if not available and nxt == "":
        raise RuntimeError(f"No recolors (rt/rc) found for '{prefix}'.")
    extra = _cast_identity_names(arm)
    merged = scan_recolor_stack(
        folder,
        prefix,
        apply_recolor=bool(nxt),
        recolor_code=nxt,
        target_level=_scan_target_level(prefix, *extra),
        source_name=extra[0] if extra else "",
    )
    if not merged.textures:
        raise RuntimeError(
            f"No recolor / level maps for prefix '{prefix}' in {folder}."
        )
    reports = shade_selected(
        [arm], node_adder_cls, folder=folder, prefix=prefix, match=merged, finish=False
    )
    from ..naming import with_recolor_prefix

    arm[CHAR_RECOLOR] = nxt
    tagged = str(arm.get(CHAR_TAG, "") or prefix)
    arm[CHAR_TAG] = with_recolor_prefix(tagged, nxt) if nxt else split_recolor_prefix(tagged)[0] or tagged
    deselect_all(bpy.context)
    return nxt or "original", reports


def remove_texture_mesh(mesh: bpy.types.Object, texture_type: str) -> int:
    log.info("Remove %s from %s", texture_type, mesh.name)
    from ..naming import canonical_slot

    mats = [m for m in mesh.data.materials if m is not None]
    if mesh.active_material is not None and mesh.active_material not in mats:
        mats.append(mesh.active_material)
    removed = 0
    want = texture_type.lower()
    for mat in mats:
        if mat.node_tree is None:
            continue
        for node in list(mat.node_tree.nodes):
            if node.type != "TEX_IMAGE" or node.image is None:
                continue
            stem = Path(bpy.path.abspath(node.image.filepath)).stem
            if "_" not in stem:
                continue
            raw = stem[stem.rindex("_") + 1 :]
            slot = canonical_slot(raw) or raw.lower()
            if slot == want:
                log.info("Removed %s", stem)
                mat.node_tree.nodes.remove(node)
                removed += 1
    return removed


def remove_texture_armature(armature: bpy.types.Object, texture_type: str) -> int:
    log.info("Remove %s from armature %s", texture_type, armature.name)
    total = 0
    for mesh in material_meshes(armature):
        total += remove_texture_mesh(mesh, texture_type)
    return total


def remove_texture_selected(objects: Iterable[bpy.types.Object], texture_type: str) -> int:
    total = 0
    for obj in objects:
        if obj.type == "ARMATURE":
            total += remove_texture_armature(obj, texture_type)
        elif obj.type == "MESH":
            total += remove_texture_mesh(obj, texture_type)
    return total
