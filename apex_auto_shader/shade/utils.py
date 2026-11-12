from __future__ import annotations

from pathlib import Path
from typing import Iterable

import bpy
from bpy.app.handlers import persistent

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
    is_base_hair02_name,
    base_hair02_to_hide,
    fallback_bodypart,
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
    iter_texture_files,
    model_dir_name,
    parse_skin_identity,
    overlay_match,
    prefer_textures,
    scan_folder,
    scan_object_folder,
    scan_recolor_stack,
    season_prefix_aliases,
    part_hash_kind,
    prefer_non_base_sets,
    preferred_skin_prefix,
    prefixes_for_legend_codename,
    should_hide_base_hair,
    strip_blender_suffix,
    tokenize,
    skin_prefix,
    split_mesh_variant,
    split_recolor_prefix,
    suggest_prefixes_from_names,
    prefixes_compatible,
    prefixes_for_pilot_model,
    pilot_slot_model,
    mesh_texture_prefixes,
    candidate_matches_mesh,
    mesh_requests_head,
    dominant_mesh_prefix,
    prefixes_for_short_season,
    texture_set_prefix,
    texture_prefix_from_source,
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
        sources.extend([arm.get(CHAR_TAG, ""), arm.get(CHAR_CAST, ""), arm.name])
    if obj is not None:
        sources.append(object_source_name(obj))
    picked = preferred_skin_prefix(*sources)
    if picked:
        return picked
    object_mode = is_object_shader(scene)
    for source in sources:
        if not source:
            continue
        raw = Path(str(source)).name
        pref = texture_prefix_from_source(raw, object_mode)
        if pref:
            return pref
    return ""


def _candidate_prefixes(prefix: str, folder: Path | None, mesh_names: Iterable[str]) -> list[str]:
    """Pilot slot models use the PNG name, not the folder name. Every legend."""
    found: list[str] = []

    def add(value: str) -> None:
        value = (value or "").strip("_")
        if value and value not in found:
            found.append(value)

    if folder is not None:
        slot = pilot_slot_model(prefix) or pilot_slot_model(folder.name)
        if slot:
            names = [path.name for path in iter_texture_files(folder)]
            ranked = prefixes_for_pilot_model(prefix or folder.name, names)
            own_folder = pilot_slot_model(folder.name) is not None
            if own_folder or len(ranked) == 1:
                for item in ranked[:1]:
                    add(item)
    for item in season_prefix_aliases(prefix, mesh_names):
        add(item)
    return found


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


def _armature_of(obj: bpy.types.Object | None):
    if obj is None:
        return None
    try:
        if obj.type == "ARMATURE":
            return obj
    except ReferenceError:
        return None
    if getattr(obj, "type", "") == "MESH":
        arm = None
        try:
            arm = obj.find_armature()
        except Exception:
            arm = None
        if arm is None:
            cursor = obj
            while getattr(cursor, "parent", None) is not None:
                cursor = cursor.parent
                if getattr(cursor, "type", "") == "ARMATURE":
                    arm = cursor
                    break
        return arm
    return None


def _bone_collections(data):
    cols = getattr(data, "collections_all", None)
    if cols:
        return list(cols)
    cols = getattr(data, "collections", None)
    return list(cols) if cols else []


def _enable_bone_overlay() -> None:
    """The Joints armature draws nothing while the viewport Bones overlay is off."""
    try:
        wm = bpy.context.window_manager
    except Exception:
        return
    for window in getattr(wm, "windows", []) or []:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in getattr(screen, "areas", []) or []:
            if getattr(area, "type", "") != "VIEW_3D":
                continue
            space = getattr(area, "spaces", None)
            space = space.active if space is not None else None
            overlay = getattr(space, "overlay", None)
            if overlay is None:
                continue
            try:
                overlay.show_overlays = True
            except Exception:
                pass
            for attr in ("show_bones", "show_extras"):
                if hasattr(overlay, attr):
                    try:
                        setattr(overlay, attr, True)
                    except Exception:
                        pass


def _is_cast_armature(obj) -> bool:
    if getattr(obj, "type", "") != "ARMATURE":
        return False
    if obj.get("apex_cast_path") or obj.get("apex_tag") or obj.get("apex_is_victim"):
        return True
    name = getattr(getattr(obj, "data", None), "name", "") or ""
    return name == "Joints" or name.startswith("Joints.")


def _clear_joint_shapes(arm: bpy.types.Object) -> None:
    """Shapes draws the custom octahedron. Leave that checkbox off."""
    data = getattr(arm, "data", None)
    if data is not None:
        try:
            data.show_bone_custom_shapes = False
        except Exception:
            pass
    pose = getattr(arm, "pose", None)
    if pose is not None:
        for pb in pose.bones:
            try:
                if pb.custom_shape is not None:
                    pb.custom_shape = None
            except Exception:
                pass
    junk = bpy.data.objects.get("ApexJointShape")
    if junk is not None:
        try:
            bpy.data.objects.remove(junk, do_unlink=True)
        except Exception:
            pass


def _lengthen_stub_bones(arm: bpy.types.Object) -> None:
    """CAST creates every bone 0.0025 long, so the armature draws as nothing."""
    if arm.get("apex_joints_sized"):
        return
    data = getattr(arm, "data", None)
    bones = list(getattr(data, "bones", []) or [])
    if data is None or not bones:
        return
    from mathutils import Vector

    heads = []
    lengths = []
    for bone in bones:
        head = Vector(bone.head_local)
        tail = Vector(bone.tail_local)
        heads.append(head)
        lengths.append((tail - head).length)
    span = 0.0
    if heads:
        xs = [head.x for head in heads]
        ys = [head.y for head in heads]
        zs = [head.z for head in heads]
        span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    min_len = max(span * 0.02, 0.02) if span >= 0.05 else 0.04
    ordered = sorted(lengths)
    median = ordered[len(ordered) // 2] if ordered else 0.0
    if median >= min_len * 0.75:
        arm["apex_joints_sized"] = True
        return
    found = None
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((reg for reg in area.regions if reg.type == "WINDOW"), None)
                if region is not None:
                    found = (window, area, region)
                    break
            if found:
                break
    except Exception:
        found = None
    if found is None:
        return
    window, area, region = found
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = arm.mode
    try:
        bpy.context.view_layer.objects.active = arm
        with bpy.context.temp_override(window=window, area=area, region=region, active_object=arm, object=arm):
            if arm.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
            for eb in data.edit_bones:
                direction = eb.tail - eb.head
                if direction.length >= min_len:
                    continue
                if direction.length < 1e-8:
                    direction = Vector((0.0, min_len, 0.0))
                else:
                    direction = direction.normalized() * min_len
                eb.tail = eb.head + direction
            restore = prev_mode if prev_mode in {"OBJECT", "POSE"} else "OBJECT"
            if arm.mode != restore:
                bpy.ops.object.mode_set(mode=restore)
        arm["apex_joints_sized"] = True
    except Exception as exc:
        log.warning("Could not lengthen joints on %s: %s", arm.name, exc)
    finally:
        try:
            bpy.context.view_layer.objects.active = prev_active
        except Exception:
            pass


def _use_native_bones(arm: bpy.types.Object) -> None:
    _clear_joint_shapes(arm)
    _lengthen_stub_bones(arm)
    try:
        arm["apex_joints_native"] = True
        arm["apex_joint_shapes"] = 0
    except Exception:
        pass


def _reveal_joint_draw(arm: bpy.types.Object) -> None:
    """Make the CAST 'Joints' armature actually draw.

    Hiding used to set hide_viewport. That flag is the monitor icon, which the
    outliner eye does not clear, so the armature stayed invisible. Stick bones
    inside the mesh also read as 'not there' unless they draw in front.
    """
    try:
        arm.hide_set(False)
    except Exception:
        pass
    try:
        arm.hide_viewport = False
        arm.hide_render = False
    except Exception:
        pass
    try:
        arm.show_in_front = True
    except Exception:
        pass
    data = getattr(arm, "data", None)
    if data is not None:
        try:
            data.display_type = "OCTAHEDRAL"
        except Exception:
            pass
        for bone in list(getattr(data, "bones", []) or []):
            try:
                bone.hide = False
            except Exception:
                pass
        for col in _bone_collections(data):
            try:
                col.is_visible = True
            except Exception:
                pass
            if hasattr(col, "is_solo"):
                try:
                    col.is_solo = False
                except Exception:
                    pass
    pose = getattr(arm, "pose", None)
    if pose is not None:
        for pb in getattr(pose, "bones", []) or []:
            try:
                pb.bone.hide = False
            except Exception:
                pass
    _use_native_bones(arm)
    _enable_bone_overlay()


def show_rig(obj: bpy.types.Object | None) -> None:
    """Unhide the armature and its bones in the viewport."""
    arm = _armature_of(obj)
    if arm is None:
        return
    try:
        arm["apex_bones_shown"] = True
        arm["apex_rig_gated"] = False
    except Exception:
        pass
    _reveal_joint_draw(arm)
    try:
        bpy.context.scene.apex_character = arm.name
    except Exception:
        pass


def _hide_rig_now(obj: bpy.types.Object | None) -> None:
    arm = _armature_of(obj)
    if arm is None:
        return
    try:
        arm["apex_bones_shown"] = False
        arm["apex_rig_gated"] = True
    except Exception:
        pass
    # Eye only. hide_viewport survives the outliner eye and keeps Joints invisible.
    try:
        arm.hide_viewport = False
    except Exception:
        pass
    hide_object(arm)
    try:
        arm.hide_set(True)
    except Exception:
        pass
    try:
        bpy.context.scene.apex_character = arm.name
    except Exception:
        pass


def set_rig_hidden(obj: bpy.types.Object | None, hidden: bool) -> None:
    if hidden:
        _hide_rig_now(obj)
    else:
        show_rig(obj)


_VIS_HOLD = 0


def hold_rig_visibility(hold: bool) -> None:
    """Animation apply unhides the armature so it can be selected. Do not treat that as the user turning joints on."""
    global _VIS_HOLD
    _VIS_HOLD += 1 if hold else -1
    if _VIS_HOLD < 0:
        _VIS_HOLD = 0


def rig_visibility_held() -> bool:
    return _VIS_HOLD > 0


def restore_rig_visibility(obj: bpy.types.Object | None, hidden: bool) -> None:
    """Put joints back. Off stays off, on stays on."""
    arm = _armature_of(obj)
    if arm is not None:
        _reveal_names.discard(getattr(arm, "name", ""))
    set_rig_hidden(obj, bool(hidden))


def hide_rig(obj: bpy.types.Object | None) -> None:
    """Hide bones only while Preferences → Hide bones is on.

    The eye on a character row sets apex_bones_shown so a later shade or
    animation does not hide that rig again.
    """
    if obj is None:
        return
    try:
        from ..prefs import post_shade_hide_rig
    except Exception:
        post_shade_hide_rig = lambda: True  # noqa: E731
    if not post_shade_hide_rig():
        return
    arm = _armature_of(obj)
    if arm is not None and arm.get("apex_bones_shown"):
        return
    _hide_rig_now(obj)


def rig_is_hidden(obj: bpy.types.Object | None) -> bool:
    arm = _armature_of(obj)
    if arm is None:
        return False
    try:
        if arm.hide_viewport:
            return True
    except Exception:
        pass
    try:
        return bool(arm.hide_get())
    except Exception:
        return False


def character_objects(arm: bpy.types.Object | None) -> list:
    """Armature, its children, and the rest of the imported CAST collection."""
    if arm is None:
        return []
    found = []
    seen: set[str] = set()

    def add(obj):
        if obj is None or getattr(obj, "name", "") in seen:
            return
        if (getattr(obj, "name", "") or "").startswith("Apex "):
            return
        seen.add(obj.name)
        found.append(obj)

    add(arm)
    for obj in list(getattr(arm, "children_recursive", []) or []):
        add(obj)
    raw = str(arm.get("apex_cast_collection", "") or "")
    for name in raw.split("|"):
        col = bpy.data.collections.get(name) if name else None
        if col is None:
            continue
        for obj in list(getattr(col, "all_objects", []) or []):
            add(obj)
    return found


def character_is_hidden(obj: bpy.types.Object | None) -> bool:
    arm = _armature_of(obj)
    if arm is None:
        return False
    bodies = [item for item in character_objects(arm) if getattr(item, "type", "") == "MESH"]
    targets = bodies or [arm]
    hidden = True
    for item in targets:
        try:
            hidden = hidden and bool(item.hide_get())
        except Exception:
            hidden = False
    return hidden


def set_character_hidden(obj: bpy.types.Object | None, hidden: bool) -> None:
    """Hide or show the mesh and the armature. The eye is hide_set, not hide_viewport."""
    arm = _armature_of(obj)
    if arm is None:
        return
    for item in character_objects(arm):
        try:
            item.hide_viewport = False
        except Exception:
            pass
        try:
            item.hide_set(bool(hidden))
        except Exception:
            pass
    if hidden:
        return
    try:
        from ..prefs import post_shade_hide_rig
    except Exception:
        return
    if post_shade_hide_rig():
        try:
            arm.hide_set(True)
            arm["apex_bones_shown"] = False
        except Exception:
            pass


_reveal_names: set[str] = set()


def _armature_needs_reveal(obj) -> bool:
    """Eye is open, but Joints still cannot draw."""
    if not _is_cast_armature(obj):
        return False
    try:
        if obj.hide_get():
            return False
    except Exception:
        return False
    if getattr(obj, "hide_viewport", False):
        return True
    if obj.get("apex_rig_gated") and not bool(obj.get("apex_bones_shown")):
        return True
    # CAST bones are 0.0025 long and the custom-shape checkbox hides the real joints.
    return not bool(obj.get("apex_joints_native")) or bool(obj.get("apex_joint_shapes"))


def _flush_rig_reveal():
    if rig_visibility_held():
        return None
    names = list(_reveal_names)
    _reveal_names.clear()
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or not _armature_needs_reveal(obj):
            continue
        try:
            show_rig(obj)
        except Exception:
            pass
    return None


def reveal_visible_joints() -> None:
    """CAST joints are stubs. Give every visible one a shape the viewport can draw."""
    if rig_visibility_held():
        return
    for obj in list(getattr(bpy.data, "objects", []) or []):
        try:
            if not _is_cast_armature(obj) or obj.hide_get():
                continue
            if obj.get("apex_joints_native") and not obj.get("apex_joint_shapes"):
                continue
            show_rig(obj)
        except Exception:
            continue


def _reveal_visible_joints_later():
    reveal_visible_joints()
    return None


@persistent
def apex_reveal_visible_joints(_dummy):
    try:
        if not bpy.app.timers.is_registered(_reveal_visible_joints_later):
            bpy.app.timers.register(_reveal_visible_joints_later, first_interval=0.4)
    except Exception:
        reveal_visible_joints()


def queue_rig_reveal(obj) -> None:
    if rig_visibility_held() or not _armature_needs_reveal(obj):
        return
    _reveal_names.add(obj.name)
    try:
        if not bpy.app.timers.is_registered(_flush_rig_reveal):
            bpy.app.timers.register(_flush_rig_reveal, first_interval=0.05)
    except Exception:
        _flush_rig_reveal()


@persistent
def apex_reveal_unhidden_rigs(scene, depsgraph=None):
    """Outliner eye opens the Joints armature. Finish the unhide on a timer."""
    _ = scene
    updates = getattr(depsgraph, "updates", None) if depsgraph is not None else None
    if not updates:
        return
    for update in updates:
        obj = getattr(update, "id", None)
        if obj is None:
            continue
        try:
            queue_rig_reveal(obj)
        except Exception:
            continue


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
    """Hide base lashes and base hair02 when a real hair mesh is in the rig.

    body_0_*_base_hair hides when any real hair exists.
    body_0_*_base_hair02 hides only when another mesh ends in hair02.
    The numbered hair mesh and the cosmetic hair02 stay visible.
    """
    meshes = material_meshes(root)
    lashes = []
    has_real = False
    for mesh in meshes:
        if is_base_hair02_name(mesh.name):
            has_real = True
            continue
        if _is_base_lash(mesh.name):
            lashes.append(mesh)
            continue
        if part_hash_kind(mesh.name) == "hair":
            has_real = True
            continue
        toks = [t.lower() for t in tokenize(strip_blender_suffix(mesh.name))]
        if "hair02" in toks or "stubinhair" in toks or "stubinahair" in toks:
            has_real = True
        elif toks and toks[-1] in {"hair", "hair02"}:
            has_real = True
    if has_real:
        for mesh in lashes:
            _hide_fully(mesh)
            log.info("Hide %s (base hair / lashes, real hair present)", mesh.name)
    hide_names = set(base_hair02_to_hide(mesh.name for mesh in meshes))
    for mesh in meshes:
        if mesh.name not in hide_names:
            continue
        _hide_fully(mesh)
        log.info("Hide %s (base hair02, cosmetic hair02 present)", mesh.name)


def _is_base_lash(name: str) -> bool:
    if part_hash_kind(name) == "hair":
        return False
    low = strip_blender_suffix(name).lower()
    if "hair02" in low or "stubinhair" in low or "stubinahair" in low:
        return False
    if low.endswith("_base_hair") or "_base_hair" in low:
        return True
    toks = [t.lower() for t in tokenize(name)]
    return bool(toks) and toks[-1] == "hair" and "base" in toks


def _hide_fully(mesh: bpy.types.Object) -> None:
    try:
        mesh.hide_set(True)
    except Exception:
        pass
    try:
        mesh.hide_viewport = True
    except Exception:
        pass
    try:
        mesh.hide_render = True
    except Exception:
        pass


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


def _skin_is_base(pref: str) -> bool:
    if not pref:
        return False
    ident = parse_skin_identity(pref)
    if ident.rarity == "base":
        return True
    return ident.skin in {"", "base"} and ident.rarity in {"", "base"}


def _part_ok_for_hash(bodypart: str, kind: str) -> bool:
    last = (bodypart or "").split("_")[-1]
    if kind == "head":
        return last in {"head", "helmet", "face"}
    if kind == "hair":
        return last in {"hair", "hair02", "stubinhair", "stubinahair"}
    if kind == "gear":
        return last in {"gear", "suit", "kit", "jumpkit", "zipline"}
    return True


def _fill_missing_slots(primary: list, fallback: list) -> list:
    have = {tex.slot for tex in primary if getattr(tex, "slot", None)}
    out = list(primary)
    for tex in fallback:
        slot = getattr(tex, "slot", None)
        if slot and slot not in have:
            out.append(tex)
            have.add(slot)
    return out


def _blank_hash_material(mesh, prefix: str, kind: str) -> None:
    """Copy a shared material off this mesh so a body shade cannot stick to it."""
    mats = [m for m in mesh.data.materials if m is not None]
    if mesh.active_material is not None and mesh.active_material not in mats:
        mats.append(mesh.active_material)
    for mat in mats:
        mat = uniquify_material(mesh, mat, prefix or "apex", kind)
        tree = getattr(mat, "node_tree", None)
        if tree is not None:
            tree.nodes.clear()


_TEX_LABEL = {
    "albedo": "Albedo",
    "ao": "AO",
    "normal": "Normal",
    "gloss": "Glossiness",
    "emissive": "Emissive",
    "spec": "Specular",
    "cavity": "Cavity",
    "opacity": "Opacity",
    "scatter": "Subsurface",
    "aniso": "Aniso",
    "ehl": "EHL",
    "ehm": "EHM",
}
_TEX_RANK = {name: index for index, name in enumerate(_TEX_LABEL)}


def _layout_wired_textures(mat, group, output, textures) -> None:
    """Stack map nodes in shader-socket order, collapsed, one row per input."""
    tree = getattr(mat, "node_tree", None)
    if tree is None or group is None:
        return
    by_file: dict[str, str] = {}
    for tex in textures:
        slot = getattr(tex, "slot", None) or ""
        for raw in (getattr(tex, "filename", ""), getattr(tex, "path", "")):
            name = Path(str(raw)).name.lower()
            if name:
                by_file[name] = slot
    placed: dict = {}
    try:
        sockets = list(group.inputs)
    except Exception:
        sockets = []
    for index, sock in enumerate(sockets):
        for link_ in list(getattr(sock, "links", []) or []):
            src = getattr(link_, "from_node", None)
            if src is not None and getattr(src, "type", "") == "TEX_IMAGE":
                placed.setdefault(src, index)
    for node in tree.nodes:
        if getattr(node, "type", "") != "TEX_IMAGE" or getattr(node, "image", None) is None:
            continue
        blob = f"{node.image.name} {getattr(node.image, 'filepath', '')}".lower()
        slot = ""
        for name, found in by_file.items():
            if name in blob:
                slot = found
                break
        if slot:
            node.label = _TEX_LABEL.get(slot, slot)
        node.hide = True
        try:
            node.width = 240.0
        except Exception:
            pass
    group.location = (460.0, 0.0)
    if output is not None:
        output.location = (820.0, 0.0)
    header = 32.0
    pitch = 22.0
    for node, index in placed.items():
        node.location = (group.location.x - 300.0, group.location.y - header - pitch * index)
    spare = group.location.y - header - pitch * max(len(sockets), 1)
    for node in tree.nodes:
        if getattr(node, "type", "") == "TEX_IMAGE" and node not in placed:
            node.location = (group.location.x - 300.0, spare)
            spare -= pitch
        elif getattr(node, "type", "") in {"MIX_SHADER", "BSDF_TRANSPARENT"}:
            node.location = (group.location.x, group.location.y + 160.0)


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

    ordered = sorted(
        list(textures),
        key=lambda tex: _TEX_RANK.get(tex.slot or "", 50),
    )
    wired = 0
    has_opacity = False
    for tex in ordered:
        ok = node_adder_cls.addImageTexture(
            Path(tex.path), mat, cas_node_group, (0.0, 0.0)
        )
        flag = "O" if ok else "X"
        log.info("Add %s (%s) %s", tex.filename, tex.slot or tex.slot_raw, flag)
        if ok:
            wired += 1
            if tex.slot == "opacity":
                has_opacity = True
    _layout_wired_textures(mat, cas_node_group, output_node, ordered)
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
    known_sets: Iterable[str] | None = None,
    discovered: str = "",
    scan_cache: dict | None = None,
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
            "Import the CAST or use Find Skin so the texture folder is stored on the character."
        )
    if not prefix:
        raise RuntimeError(
            f"Could not read a CAST prefix from '{mesh.name}'. "
            "Select the imported armature or a mesh named after the CAST file."
        )
    hash_kind = part_hash_kind(mesh.name)
    if hash_kind:
        # Shared CAST materials are named "..._body". Detach before any miss
        # so a gear/head/hair mesh cannot keep the body maps.
        _blank_hash_material(mesh, prefix, hash_kind)

    extra = _cast_identity_names(mesh)
    select_level = _scan_target_level(prefix, *extra)
    object_mode = is_object_shader(scene, node_adder_cls)
    recolor = _armature_recolor(mesh)
    cache = scan_cache if scan_cache is not None else {}

    def _scanned(cand: str):
        if cand not in cache:
            cache[cand] = _scan_shade_match(
                folder, cand, extra, select_level, object_mode, recolor_code=recolor
            )
        return cache[cand]

    def _fits(trial):
        if not trial or not getattr(trial, "textures", None):
            return None
        return guess_bodypart(mesh_match_names(mesh), trial.bodyparts())

    chosen = None
    chosen_prefix = prefix or ""
    bodypart = None
    recolor_locked = bool(getattr(match, "recolor_code", "") or "")
    if match is not None and getattr(match, "textures", None):
        bodypart = _fits(match)
        if hash_kind in {"head", "hair", "gear"}:
            forced = guess_bodypart([mesh.name], match.bodyparts())
            if forced and _part_ok_for_hash(forced, hash_kind):
                bodypart = forced
                chosen = match
        elif bodypart or recolor_locked:
            chosen = match
    if chosen is None and not recolor_locked:
        order = prefer_non_base_sets(
            mesh_texture_prefixes(prefix or "", mesh.name, known_sets or [], discovered),
            mesh.name,
        )
        if hash_kind in {"head", "hair", "gear"}:
            legend = _mesh_legend(mesh) or parse_skin_identity(prefix or "").legend
            if legend:
                base_name = f"{legend}_base"
                if base_name not in order:
                    order.append(base_name)
            if hash_kind == "gear":
                for extra_pref in list(known_sets or []):
                    extra_pref = (extra_pref or "").strip("_").lower()
                    if extra_pref and extra_pref not in order:
                        order.append(extra_pref)
            rest = [item for item in order if not _skin_is_base(item)]
            base_prefs = [item for item in order if _skin_is_base(item)]
            if rest:
                order = rest + base_prefs
        mesh_pref = skin_prefix(mesh.name)
        wants_head = hash_kind == "head" or mesh_requests_head(mesh.name)
        own = None
        own_prefix = ""
        for cand in order:
            if not candidate_matches_mesh(mesh.name, cand):
                continue
            trial = _scanned(cand)
            hit = _fits(trial)
            if hash_kind in {"head", "hair", "gear"}:
                forced = guess_bodypart([mesh.name], trial.bodyparts() if trial else [])
                # The material name is often "..._body". Do not wear that on gear/head/hair.
                hit = forced or None
            if wants_head and hit and hit.split("_")[-1] not in {"head", "helmet", "face"}:
                hit = None
            if hit:
                chosen = trial
                chosen_prefix = cand
                bodypart = hit
                break
            if (
                own is None
                and mesh_pref
                and cand == mesh_pref
                and getattr(trial, "textures", None)
            ):
                own = trial
                own_prefix = cand
        if chosen is None and own is not None:
            chosen = own
            chosen_prefix = own_prefix
            bodypart = _fits(own)
            if wants_head and bodypart and bodypart.split("_")[-1] not in {"head", "helmet", "face"}:
                head_part = next(
                    (
                        part
                        for part in own.bodyparts()
                        if part.split("_")[-1] in {"head", "helmet", "face"}
                    ),
                    "",
                )
                bodypart = head_part or bodypart
    if chosen is None or not getattr(chosen, "textures", None):
        raise RuntimeError(prefix_conflict_message(folder, prefix or mesh.name))
    match = chosen
    prefix = chosen_prefix or prefix

    mesh_prefix = skin_prefix(mesh.name)
    if mesh_prefix and mesh_prefix != prefix and not bodypart:
        narrowed = [
            tex
            for tex in match.textures
            if prefixes_compatible(Path(tex.filename).name, mesh_prefix)
        ]
        if narrowed:
            match = type(match)(
                source_name=match.source_name,
                prefix=mesh_prefix,
                textures=narrowed,
                recolor_code=getattr(match, "recolor_code", "") or "",
            )
            prefix = mesh_prefix
            bodypart = guess_bodypart(mesh_match_names(mesh), match.bodyparts())

    if bodypart is None:
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
    if hash_kind in {"head", "hair", "gear"}:
        forced = guess_bodypart([mesh.name], parts)
        if forced and _part_ok_for_hash(forced, hash_kind):
            bodypart = forced
            textures0 = _pick(bodypart)
        elif bodypart and not _part_ok_for_hash(bodypart, hash_kind):
            bodypart = None
            textures0 = []
    if bodypart is None:
        named = fallback_bodypart(mesh.name, parts)
        if named:
            bodypart = named
            textures0 = _pick(bodypart)
    suit_tail = last_name_token(mesh.name)
    if (
        not textures0
        and hash_kind != "gear"
        and suit_tail in {"suit", "gear", "jumpkit", "zipline", "kit"}
    ):
        body_part = next((part for part in parts if part.split("_")[-1] == "body"), "")
        if body_part:
            bodypart = body_part
            textures0 = _pick(bodypart)
    if hash_kind in {"head", "hair"} and folder is not None:
        legend = _mesh_legend(mesh) or parse_skin_identity(prefix or "").legend
        base_name = f"{legend}_base" if legend else ""
        if base_name and not _skin_is_base(prefix or ""):
            trial = _scanned(base_name)
            if trial and getattr(trial, "textures", None):
                base_bp = guess_bodypart([mesh.name], trial.bodyparts())
                if base_bp and _part_ok_for_hash(base_bp, hash_kind):
                    base_tex = prefer_textures(trial.textures, base_bp)
                    if base_tex:
                        if not textures0:
                            textures0 = base_tex
                            bodypart = base_bp
                        else:
                            textures0 = _fill_missing_slots(textures0, base_tex)
    if not textures0 and hash_kind not in {"head", "hair", "gear"}:
        if len(parts) == 1:
            bodypart = parts[0]
            textures0 = _pick(bodypart)
        elif object_mode or not is_legend_character_name(prefix):
            bodypart = bodypart or (parts[0] if parts else "object")
            textures0 = _unique_slot_textures(match.textures)
    if bodypart is None and textures0:
        bodypart = parts[0] if parts else "object"
    if bodypart is None:
        if hash_kind:
            _blank_hash_material(mesh, prefix or mesh.name, hash_kind)
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
        if hash_kind in {"head", "hair", "gear"} and bodypart:
            slot_bp = bodypart
            textures = list(textures0)
        else:
            slot_names = [mat.name, mesh.name]
            slot_bp = guess_bodypart(slot_names, match.bodyparts()) or bodypart
            textures = _pick(slot_bp)
            if not textures:
                textures = textures0
        mat = uniquify_material(mesh, mat, prefix, slot_bp)
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
        raise RuntimeError("No texture folder stored on this character. Import the CAST or use Find Skin.")
    if not prefix:
        hint = ""
        if folder is not None:
            found = suggest_prefixes_from_names(p.name for p in iter_texture_files(folder))
            if found:
                hint = f" Folder looks like: {', '.join(found[:4])}."
        raise RuntimeError(
            "Could not read a CAST prefix from the armature name." + hint
        )

    extra = _cast_identity_names(armature)
    known: list[str] = []
    discovered = ""
    if match is None and folder is not None:
        file_names: list[str] = []
        counts: dict[str, int] = {}
        for path in iter_texture_files(folder):
            file_names.append(path.name)
            pref = texture_set_prefix(path.name)
            if pref:
                counts[pref] = counts.get(pref, 0) + 1
        known = [key for key, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        if pilot_slot_model(prefix) or pilot_slot_model(folder.name):
            ranked = prefixes_for_pilot_model(prefix or folder.name, file_names)
            own_folder = pilot_slot_model(folder.name) is not None
            if ranked and (own_folder or len(ranked) == 1):
                discovered = ranked[0]
        if not discovered:
            coded = prefixes_for_legend_codename(prefix or folder.name, file_names)
            if not coded and folder is not None:
                coded = prefixes_for_legend_codename(prefix or "", file_names)
            if coded:
                discovered = coded[0]
        if not discovered:
            mesh_names = [mesh.name for mesh in material_meshes(armature)]
            discovered = dominant_mesh_prefix(mesh_names)
        if not discovered:
            mesh_names = [mesh.name for mesh in material_meshes(armature)]
            ranked = prefixes_for_short_season(prefix or folder.name, file_names, mesh_names)
            if ranked:
                discovered = ranked[0]
    reports = []
    meshes = material_meshes(armature)
    from .extras import hide_higher_lods

    hide_higher_lods(armature)
    hide_duplicate_hair(armature)
    cache: dict = {}
    for i, mesh in enumerate(meshes):
        log.info("Shade %s (%s/%s)", mesh.name, i, len(meshes))
        try:
            reports.append(
                shade_mesh(
                    mesh,
                    node_adder_cls,
                    folder=folder,
                    prefix=prefix,
                    match=match,
                    known_sets=known,
                    discovered=discovered,
                    scan_cache=cache,
                )
            )
        except Exception as exc:
            log.warning("Skip %s: %s", mesh.name, exc)
            reports.append(
                {"mesh": mesh.name, "bodypart": None, "wired": 0, "total": 0, "error": str(exc)}
            )
    hide_duplicate_hair(armature)
    return reports


def shade_selected(
    objects: Iterable[bpy.types.Object],
    node_adder_cls: type[NodeAdder],
    folder: Path | None = None,
    prefix: str | None = None,
    match: object | None = None,
    finish: bool = True,
) -> list[dict]:
    from ..naming import pop_texture_cache, push_texture_cache

    push_texture_cache()
    try:
        return _shade_selected(
            objects, node_adder_cls, folder=folder, prefix=prefix, match=match, finish=finish
        )
    finally:
        pop_texture_cache()


def _shade_selected(
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
        if part_hash_kind(mesh.name) and (other == arm or other is None):
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
        raise RuntimeError("No texture folder stored on this character. Import the CAST or use Find Skin.")
    prefix = detect_prefix(arm, scene)
    if not prefix:
        raise RuntimeError("Could not read a CAST prefix from the model name.")
    from .extras import CHAR_RECOLOR, CHAR_TAG

    mesh_names = [mesh.name for mesh in material_meshes(arm)]
    ordered: list[str] = []

    def _add_cand(value: str) -> None:
        value = (value or "").strip("_")
        if value and value not in ordered and candidate_matches_mesh(arm.name, value):
            ordered.append(value)

    _add_cand(prefix)
    from ..naming.tex import texture_prefixes_for_mesh

    for alias in texture_prefixes_for_mesh(prefix):
        if alias and alias not in ordered:
            ordered.insert(0, alias)
    for mesh_name in mesh_names:
        _add_cand(skin_prefix(mesh_name))
    for cand in _candidate_prefixes(prefix, folder, mesh_names):
        _add_cand(cand)
    if not ordered:
        ordered = [prefix]
    current = str(arm.get(CHAR_RECOLOR, "") or "")
    extra = _cast_identity_names(arm)
    merged = None
    nxt = ""
    chosen = ""
    for cand in ordered:
        available = list_folder_recolors(folder, cand)
        if not available:
            continue
        nxt_try = cycle_recolor_code(available, current)
        if nxt_try == (current or ""):
            continue
        base = split_recolor_prefix(cand)[0] or cand
        trial = scan_recolor_stack(
            folder,
            base,
            apply_recolor=bool(nxt_try),
            recolor_code=nxt_try or None,
            target_level=_scan_target_level(base, *extra),
            source_name=extra[0] if extra else "",
        )
        if trial.textures:
            chosen = base
            nxt = nxt_try
            merged = trial
            break
    if merged is None or not merged.textures:
        raise RuntimeError(
            f"No recolor / level maps for prefix '{prefix}' in {folder}."
        )
    tex_path = Path(str(merged.textures[0].path))
    if tex_path.parent.is_dir():
        folder = tex_path.parent
        arm["apex_texture_dir"] = str(folder)
    reports = shade_selected(
        [arm], node_adder_cls, folder=folder, prefix=chosen or prefix, match=merged, finish=False
    )
    from ..naming import texture_prefixes_for_mesh, with_recolor_prefix

    tagged = str(arm.get(CHAR_TAG, "") or chosen or prefix)
    base_tag = split_recolor_prefix(tagged)[0] or tagged
    alias = texture_prefixes_for_mesh(base_tag)
    skin_base = split_recolor_prefix(alias[0])[0] if alias else (chosen or base_tag)
    if nxt:
        arm[CHAR_RECOLOR] = nxt
        arm[CHAR_TAG] = with_recolor_prefix(skin_base, nxt)
    else:
        if CHAR_RECOLOR in arm:
            try:
                del arm[CHAR_RECOLOR]
            except Exception:
                arm[CHAR_RECOLOR] = ""
        arm[CHAR_TAG] = skin_base
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
