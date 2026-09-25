from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Vector

from .character import (
    _is_scene_collection,
    _purge_collection,
    apply_model_size,
    import_cast_model,
    remember_character,
    resolve_character,
)
from .const import CHAR_VICTIM, START_BONE
from .studio import (
    _action_fcurves,
    _find_pose_bone,
    _flip_imported_cameras,
    _hide_imported_cameras,
    apply_banner_lights,
    apply_camera_pov,
    apply_camera_preset,
    clear_banner_lights,
    is_pov_camera,
    refresh_studio_camera,
    restore_studio_camera,
    set_studio_lights_visible,
)
from ..blender_compat import deselect_objects, ignore_rna, material_meshes, resolve_armature
from ..log import existing_file, log
from ..naming import is_banner_clip, is_capturemode_clip, strip_blender_suffix
from ..prefs import cast_importer_available, model_scale
from ..utils import hide_rig

def _unhide(obj: bpy.types.Object) -> bool:
    hidden = bool(obj.hide_get()) or bool(getattr(obj, "hide_viewport", False))
    try:
        obj.hide_set(False)
    except (ReferenceError, RuntimeError, AttributeError) as exc:
        ignore_rna(exc, f"unhide {getattr(obj, 'name', obj)}")
    try:
        obj.hide_viewport = False
    except (ReferenceError, AttributeError) as exc:
        ignore_rna(exc, f"unhide viewport {getattr(obj, 'name', obj)}")
    return hidden


def make_armature_active(context, arm: bpy.types.Object) -> None:
    if context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    _unhide(arm)
    deselect_objects(context)
    arm.select_set(True)
    context.view_layer.objects.active = arm
    children = getattr(arm, "children_recursive", None)
    pool = list(children) if children is not None else list(getattr(arm, "children", []))
    for child in pool:
        try:
            child.select_set(True)
        except Exception:
            pass


def deselect_all(context) -> None:
    deselect_objects(context)


def _view3d_override(context):
    windows = list(getattr(context.window_manager, "windows", []))
    current = getattr(context, "window", None)
    if current is not None and current not in windows:
        windows.insert(0, current)
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is not None:
                return window, area, region
    return None, None, None


def view_front_and_frame(context, obj: bpy.types.Object) -> None:
    target = resolve_armature(obj) or obj
    window, area, region = _view3d_override(context)
    deselect_objects(context)
    active = None
    meshes = material_meshes(target) if target is not None else []
    for mesh in meshes:
        if mesh.hide_get() or getattr(mesh, "hide_viewport", False):
            continue
        try:
            mesh.select_set(True)
        except Exception:
            continue
        if active is None:
            active = mesh
            context.view_layer.objects.active = mesh
    if active is None and target is not None:
        _unhide(target)
        try:
            target.select_set(True)
            context.view_layer.objects.active = target
            active = target
        except Exception:
            pass
    if window is None or active is None:
        return
    try:
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.view3d.view_axis(type="TOP")
            bpy.ops.view3d.view_selected()
    except Exception:
        pass
    set_material_viewport(context)


def set_material_viewport(context) -> None:
    windows = list(getattr(context.window_manager, "windows", []))
    current = getattr(context, "window", None)
    if current is not None and current not in windows:
        windows.insert(0, current)
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = getattr(area, "spaces", None)
            space = space.active if space is not None else None
            shading = getattr(space, "shading", None) if space is not None else None
            if shading is None:
                continue
            try:
                shading.type = "MATERIAL"
            except Exception:
                pass


OBJECT_TRANSFORM_PATHS = frozenset(
    {
        "location",
        "rotation_euler",
        "rotation_quaternion",
        "rotation_axis_angle",
        "scale",
        "delta_location",
        "delta_rotation_euler",
        "delta_rotation_quaternion",
        "delta_scale",
    }
)


def _capture_transform(obj: bpy.types.Object) -> dict:
    mode = obj.rotation_mode
    data = {
        "location": obj.location.copy(),
        "scale": obj.scale.copy(),
        "mode": mode,
    }
    if mode == "QUATERNION":
        data["quaternion"] = obj.rotation_quaternion.copy()
    elif mode == "AXIS_ANGLE":
        data["axis_angle"] = tuple(obj.rotation_axis_angle)
    else:
        data["euler"] = obj.rotation_euler.copy()
    return data


def _object_mode(context) -> None:
    try:
        if getattr(getattr(context, "object", None), "mode", "OBJECT") != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass


def _autokey_off(context):
    ts = getattr(context, "tool_settings", None)
    if ts is None:
        return None
    state = (
        bool(getattr(ts, "use_keyframe_insert_auto", False)),
        bool(getattr(ts, "use_keyframe_insert_keyingset", False)),
    )
    try:
        ts.use_keyframe_insert_auto = False
        ts.use_keyframe_insert_keyingset = False
    except Exception:
        pass
    return state


def _autokey_restore(context, state) -> None:
    if not state:
        return
    ts = getattr(context, "tool_settings", None)
    if ts is None:
        return
    try:
        ts.use_keyframe_insert_auto = state[0]
        ts.use_keyframe_insert_keyingset = state[1]
    except Exception:
        pass


def _zero_object_rotation(obj: bpy.types.Object) -> None:
    """Keep the armature at XYZ 0,0,0. Animation must not add a 90° X tilt."""
    try:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        obj.rotation_axis_angle = (0.0, 1.0, 0.0, 0.0)
        obj.delta_rotation_euler = (0.0, 0.0, 0.0)
    except Exception:
        pass


def _strip_object_rotation_keys(obj: bpy.types.Object) -> None:
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad is not None else None
    if action is None:
        return
    for curve in list(_action_fcurves(action)):
        path = getattr(curve, "data_path", "") or ""
        if path in {"rotation_euler", "rotation_quaternion", "rotation_axis_angle"} or path.startswith(
            "delta_rotation"
        ):
            _remove_fcurve(action, curve)


def _restore_transform(obj: bpy.types.Object, data: dict | None) -> None:
    """Keep scale and origin; rotation stays XYZ 0°."""
    apply_model_size(obj)
    _zero_object_rotation(obj)
    if data and data.get("location") is not None:
        try:
            obj.location = data["location"]
        except Exception:
            pass
    try:
        obj.delta_location = (0.0, 0.0, 0.0)
        obj.delta_rotation_euler = (0.0, 0.0, 0.0)
        obj.delta_scale = (1.0, 1.0, 1.0)
    except Exception:
        pass


def _pick_cast_action_slot(action):
    """Prefer CAST's own slot (Blender 4.4+/5.x layered actions).

    Order: name_display/name == "cast" (or starts with cast), then
    target_id_type OBJECT, else slots[0].
    """
    slots = getattr(action, "slots", None)
    if not slots:
        return None
    cast_named = []
    object_typed = []
    for slot in slots:
        name = (
            getattr(slot, "name_display", None)
            or getattr(slot, "name", None)
            or ""
        )
        name_l = str(name).strip().lower()
        if name_l == "cast" or name_l.startswith("cast"):
            cast_named.append(slot)
        tid = getattr(slot, "target_id_type", None)
        tid_s = str(getattr(tid, "name", tid) or "").upper()
        if tid_s == "OBJECT" or tid_s.endswith(".OBJECT"):
            object_typed.append(slot)
    if cast_named:
        # Prefer cast-named that is also OBJECT when both exist
        for slot in cast_named:
            if slot in object_typed:
                return slot
        return cast_named[0]
    if object_typed:
        return object_typed[0]
    try:
        return slots[0]
    except Exception:
        return None


def _action_slot(obj, action=None):
    ad = getattr(obj, "animation_data", None)
    action = action or getattr(ad, "action", None)
    if ad is None or action is None:
        return None, action
    slots = getattr(action, "slots", None)
    chosen = _pick_cast_action_slot(action) if slots else None
    if chosen is None:
        chosen = getattr(ad, "action_slot", None)
    if chosen is not None:
        try:
            ad.action_slot = chosen
        except Exception:
            pass
    return getattr(ad, "action_slot", None) or chosen, action


def _channelbag_for(obj, action=None):
    slot, action = _action_slot(obj, action)
    if action is None:
        return None
    try:
        from bpy_extras import anim_utils

        if slot is not None:
            ensure = getattr(anim_utils, "action_ensure_channelbag_for_slot", None)
            if callable(ensure):
                return ensure(action, slot)
            getter = getattr(anim_utils, "action_get_channelbag_for_slot", None)
            if callable(getter):
                bag = getter(action, slot)
                if bag is not None:
                    return bag
    except Exception:
        pass
    try:
        layer = action.layers[0] if getattr(action, "layers", None) else None
        if layer is None:
            layer = action.layers.new("Layer")
        strip = layer.strips[0] if getattr(layer, "strips", None) else None
        if strip is None:
            strip = layer.strips.new(type="KEYFRAME")
        bag_fn = getattr(strip, "channelbag", None)
        if callable(bag_fn) and slot is not None:
            try:
                return bag_fn(slot, ensure=True)
            except TypeError:
                return bag_fn(slot)
    except Exception:
        return None
    return None


def _ensure_object_fcurve(obj, data_path: str, index: int = 0, group: str = "ApexLayout"):
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad is not None else None
    if action is None:
        return None
    ensure = getattr(action, "fcurve_ensure_for_datablock", None)
    if callable(ensure):
        try:
            return ensure(obj, data_path, index=index, group_name=group)
        except TypeError:
            try:
                return ensure(obj, data_path, index=index)
            except Exception:
                pass
        except Exception:
            pass
    bag = _channelbag_for(obj, action)
    fcs = getattr(bag, "fcurves", None) if bag is not None else None
    if fcs is not None:
        ens = getattr(fcs, "ensure", None)
        if callable(ens):
            try:
                return ens(data_path, index=index, group_name=group)
            except TypeError:
                try:
                    return ens(data_path, index=index)
                except Exception:
                    pass
        find = getattr(fcs, "find", None)
        if callable(find):
            try:
                found = find(data_path, index=index)
                if found is not None:
                    return found
            except Exception:
                pass
        new = getattr(fcs, "new", None)
        if callable(new):
            try:
                return new(data_path, index=index, group_name=group)
            except TypeError:
                try:
                    return new(data_path, index=index)
                except Exception:
                    pass
    return None


def _write_constant_curve(curve, value: float, start: int, end: int) -> None:
    kps = getattr(curve, "keyframe_points", None)
    if kps is None:
        return
    try:
        kps.clear()
    except Exception:
        pass
    frames = (start,) if end == start else (start, end)
    for frame in frames:
        kp = None
        try:
            kp = kps.insert(frame, float(value), options={"FAST"})
        except TypeError:
            try:
                kp = kps.insert(frame, float(value))
            except Exception:
                continue
        except Exception:
            continue
        try:
            kp.interpolation = "CONSTANT"
            kp.handle_left_type = "VECTOR"
            kp.handle_right_type = "VECTOR"
        except Exception:
            pass
    try:
        curve.extrapolation = "CONSTANT"
    except Exception:
        pass
    try:
        curve.mute = False
        curve.update()
    except Exception:
        pass


def _remove_fcurve(action, curve) -> bool:
    collections = [getattr(action, "fcurves", None)]
    try:
        from bpy_extras import anim_utils

        getter = getattr(anim_utils, "action_get_channelbag_for_slot", None)
        if callable(getter):
            for slot in list(getattr(action, "slots", []) or []):
                try:
                    bag = getter(action, slot)
                except Exception:
                    bag = None
                if bag is not None:
                    collections.append(getattr(bag, "fcurves", None))
    except Exception:
        pass
    try:
        slots = list(getattr(action, "slots", []) or [])
        for layer in getattr(action, "layers", []) or []:
            for strip in getattr(layer, "strips", []) or []:
                bag_fn = getattr(strip, "channelbag", None)
                if callable(bag_fn):
                    for slot in slots or [None]:
                        try:
                            bag = bag_fn(slot) if slot is not None else bag_fn()
                        except Exception:
                            bag = None
                        if bag is not None:
                            collections.append(getattr(bag, "fcurves", None))
                elif bag_fn is not None:
                    collections.append(getattr(bag_fn, "fcurves", None))
                extra = getattr(strip, "channelbags", None)
                if extra:
                    for item in extra:
                        collections.append(getattr(item, "fcurves", None))
    except Exception:
        pass
    for coll in collections:
        if not coll:
            continue
        try:
            coll.remove(curve)
            return True
        except Exception:
            continue
    try:
        curve.data_path = ""
        return True
    except Exception:
        return False


def _strip_object_transform_keys(obj: bpy.types.Object) -> None:
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad is not None else None
    if action is None:
        return
    for curve in list(_action_fcurves(action)):
        path = getattr(curve, "data_path", "") or ""
        if path in OBJECT_TRANSFORM_PATHS:
            _remove_fcurve(action, curve)


def _constant_keys(curve) -> None:
    try:
        for kp in curve.keyframe_points:
            kp.interpolation = "CONSTANT"
    except Exception:
        pass


def _pin_object_layout(obj: bpy.types.Object, saved: dict | None = None) -> None:
    """Pin location/scale. Strip rotation keys so CAST cannot tilt the armature by 90°."""
    _restore_transform(obj, saved)
    _strip_object_rotation_keys(obj)
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad is not None else None
    if action is None:
        _zero_object_rotation(obj)
        return
    _action_slot(obj, action)
    loc = obj.location
    scl = obj.scale
    scene = getattr(bpy.context, "scene", None)
    start = int(getattr(scene, "frame_start", 1) or 1)
    end = int(getattr(scene, "frame_end", start) or start)
    if end < start:
        end = start
    channels = (
        ("location", 0, float(loc[0])),
        ("location", 1, float(loc[1])),
        ("location", 2, float(loc[2])),
        ("scale", 0, float(scl[0])),
        ("scale", 1, float(scl[1])),
        ("scale", 2, float(scl[2])),
    )
    wrote = False
    for path, index, value in channels:
        curve = _ensure_object_fcurve(obj, path, index)
        if curve is None:
            continue
        _write_constant_curve(curve, value, start, end)
        wrote = True
    if not wrote:
        try:
            for frame in dict.fromkeys((start, end)):
                for index in range(3):
                    obj.keyframe_insert(data_path="location", index=index, frame=frame)
                    obj.keyframe_insert(data_path="scale", index=index, frame=frame)
        except Exception as exc:
            log.warning("Could not pin layout transform on %s: %s", obj.name, exc)
    _strip_object_rotation_keys(obj)
    _zero_object_rotation(obj)


def delete_victim_objects(arm: bpy.types.Object) -> None:
    from ..extras import CHAR_COLL

    col_names = []
    try:
        stored = arm.get(CHAR_COLL) or ""
        col_names = [part for part in str(stored).split("|") if part]
        name = strip_blender_suffix(arm.name)
        if name.endswith("_victim"):
            col_names.append(name)
        else:
            col_names.append(f"{name}_victim")
    except ReferenceError:
        return
    extra = []
    try:
        extra.append(arm)
        children = getattr(arm, "children_recursive", None)
        if children is not None:
            extra.extend(list(children))
        for obj in list(bpy.data.objects):
            try:
                if obj.find_armature() == arm:
                    extra.append(obj)
            except Exception:
                pass
    except ReferenceError:
        extra = []
    seen = set()
    for obj in extra:
        try:
            name = obj.name
        except ReferenceError:
            continue
        if name in seen:
            continue
        seen.add(name)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    for name in dict.fromkeys(col_names):
        col = bpy.data.collections.get(name)
        if col is None or _is_scene_collection(col):
            continue
        try:
            _purge_collection(col)
        except Exception:
            try:
                bpy.data.collections.remove(col)
            except Exception:
                pass


def _sync_transform(src: bpy.types.Object, dst: bpy.types.Object) -> None:
    try:
        dst.location = src.location.copy()
        dst.scale = src.scale.copy()
        dst.rotation_mode = "XYZ"
        src.rotation_mode = "XYZ"
        dst.rotation_euler = src.rotation_euler.copy()
    except ReferenceError:
        pass


def _bone_world_loc(arm: bpy.types.Object, name: str) -> Vector | None:
    bone = _find_pose_bone(arm, name)
    if bone is None:
        return None
    try:
        return arm.matrix_world @ Vector(bone.head)
    except Exception:
        try:
            return arm.matrix_world @ bone.matrix.to_translation()
        except Exception:
            return None


def _home_collection(obj: bpy.types.Object):
    for col in list(getattr(obj, "users_collection", []) or []):
        if not _is_scene_collection(col):
            return col
    cols = list(getattr(obj, "users_collection", []) or [])
    return cols[0] if cols else None


def _set_single_collection(obj: bpy.types.Object, col) -> None:
    if obj is None or col is None:
        return
    if obj.name not in col.objects:
        try:
            col.objects.link(obj)
        except Exception:
            pass
    for other in list(obj.users_collection):
        if other == col:
            continue
        try:
            other.objects.unlink(obj)
        except Exception:
            pass


def _ensure_named_collection(context, name: str):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    parent = context.scene.collection
    if col.name not in parent.children:
        try:
            parent.children.link(col)
        except Exception:
            pass
    return col


def _victim_tree(arm: bpy.types.Object) -> list:
    objs = [arm]
    children = getattr(arm, "children_recursive", None)
    if children is not None:
        objs.extend(list(children))
    else:
        objs.extend(list(getattr(arm, "children", [])))
    for obj in list(bpy.data.objects):
        try:
            if obj.find_armature() == arm and obj not in objs:
                objs.append(obj)
        except Exception:
            pass
    return objs


def _park_victim(context, arm: bpy.types.Object, home=None) -> None:
    from ..extras import CHAR_COLL, tag_character

    if home is None:
        stored = arm.get(CHAR_COLL) or ""
        for part in str(stored).split("|"):
            col = bpy.data.collections.get(part)
            if col is not None and not _is_scene_collection(col):
                home = col
                break
        if home is None:
            home = _home_collection(arm)
        if home is None or _is_scene_collection(home):
            home = _ensure_named_collection(context, f"{strip_blender_suffix(arm.name)}_victim")
    for obj in _victim_tree(arm):
        _set_single_collection(obj, home)
    tag_character(arm, collection=home.name)


def _align_start_bones(attacker: bpy.types.Object, victim: bpy.types.Object) -> bool:
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    origin = _bone_world_loc(attacker, START_BONE)
    other = _bone_world_loc(victim, START_BONE)
    if origin is None or other is None:
        log.warning("Bone '%s' missing on attacker or victim — skip start alignment", START_BONE)
        return False
    try:
        victim.location = victim.location + (origin - other)
    except ReferenceError:
        return False
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return True


def _mirror_victim_y(attacker: bpy.types.Object, victim: bpy.types.Object) -> None:
    try:
        victim.rotation_mode = "XYZ"
        attacker.rotation_mode = "XYZ"
        victim.rotation_euler = attacker.rotation_euler.copy()
        scale = attacker.scale.copy()
        victim.scale = (scale.x, -abs(float(scale.y) or model_scale()), scale.z)
        victim.location = attacker.location.copy()
    except ReferenceError:
        pass


def _place_victim(attacker: bpy.types.Object, victim: bpy.types.Object) -> None:
    _mirror_victim_y(attacker, victim)
    _align_start_bones(attacker, victim)


def _object_alive(obj) -> bool:
    if obj is None:
        return False
    try:
        obj.name
        return True
    except ReferenceError:
        return False


def _require_armature(arm: bpy.types.Object | None, role: str = "character") -> bpy.types.Object:
    if arm is None:
        raise RuntimeError(f"No {role} armature. Import a CAST model first.")
    if not _object_alive(arm):
        raise RuntimeError(f"{role.title()} armature was removed. Re-import the model.")
    if getattr(arm, "type", "") != "ARMATURE":
        raise RuntimeError(f"{role.title()} '{arm.name}' is not an armature.")
    if getattr(arm, "data", None) is None:
        raise RuntimeError(f"{role.title()} '{arm.name}' has no armature data.")
    return arm


def _require_anim_file(filepath: str, kind: str = "Animation") -> Path:
    path = existing_file(filepath)
    if path is None:
        raise RuntimeError(f"{kind} not found: {filepath or '(empty path)'}")
    return path


def _armature_has_bone(arm: bpy.types.Object, name: str) -> bool:
    return _find_pose_bone(arm, name) is not None


def existing_victim(context):
    from ..extras import tagged_armatures

    for arm in tagged_armatures(context.scene, include_victims=True):
        if not arm.get(CHAR_VICTIM):
            continue
        try:
            arm.name
        except ReferenceError:
            continue
        return arm
    return None


def apply_cast_animation(
    context,
    filepath: str,
    arm: bpy.types.Object,
    play: bool = True,
    aim_camera: bool = True,
) -> bool:
    arm = _require_armature(arm, "character")
    if not cast_importer_available():
        raise RuntimeError(
            "CAST importer not found. Install dtzxporter/cast, then restart Blender."
        )
    path = _require_anim_file(filepath, "Animation")
    remember_character(arm)
    saved = _capture_transform(arm)
    before = set(bpy.data.objects.keys())
    make_armature_active(context, arm)
    _object_mode(context)
    _zero_object_rotation(arm)
    autokey = _autokey_off(context)
    try:
        bpy.ops.import_scene.cast(
            "EXEC_DEFAULT",
            filepath=str(path),
            import_reset=True,
            import_time=False,
            import_skin=False,
            import_ik=False,
            import_constraints=False,
            import_blend_shapes=False,
            import_hair=False,
            import_merge=False,
        )
    except Exception as exc:
        raise RuntimeError(f"CAST failed to apply '{path.name}': {exc}") from exc
    finally:
        _autokey_restore(context, autokey)
    if not _object_alive(arm):
        raise RuntimeError(
            f"Armature was removed while loading '{path.name}'. Re-import the character."
        )
    # CAST 2.01: layered actions need the cast OBJECT slot rebound explicitly
    # before strip/pin/sync, otherwise pose plays but nothing is visible.
    try:
        _action_slot(arm)
    except Exception:
        pass
    _object_mode(context)
    _strip_object_transform_keys(arm)
    _strip_object_rotation_keys(arm)
    _restore_transform(arm, saved)
    action = getattr(getattr(arm, "animation_data", None), "action", None)
    if action is None:
        log.warning("No action on %s after loading %s", arm.name, path.name)
    capture = is_capturemode_clip(path.name)
    banner = capture or is_banner_clip(path.name)
    if banner:
        _hide_imported_cameras(before)
    else:
        _flip_imported_cameras(before)
    context.view_layer.update()
    from ..extras import sync_frame_range

    sync_frame_range(context, arm)
    make_armature_active(context, arm)
    _pin_object_layout(arm, saved)
    context.view_layer.update()
    context.scene.frame_set(context.scene.frame_start)
    _strip_object_rotation_keys(arm)
    _restore_transform(arm, saved)
    _zero_object_rotation(arm)
    hide_rig(arm)
    remember_character(arm)
    deselect_all(context)
    _stop_animation(context)
    setup = {}
    if banner:
        from ..naming.anim import guess_legend_from_anim
        from ..naming.cosmetics import banner_setup_for

        setup = banner_setup_for(path.name, guess_legend_from_anim(path.name))
    static_banner = bool(banner and setup.get("kind") == "static")
    if static_banner:
        action = getattr(getattr(arm, "animation_data", None), "action", None)
        if action is not None:
            try:
                action.use_cyclic = False
            except Exception:
                pass
        try:
            context.scene.frame_end = context.scene.frame_start
        except Exception:
            pass
        context.scene.frame_set(context.scene.frame_start)
    if capture and aim_camera:
        try:
            _apply_banner_staging(context, path, arm, setup)
        except Exception as exc:
            log.warning("Capture camera/lights failed for %s: %s", path.name, exc)
            apply_camera_preset(context, "front", create=True)
    elif banner:
        clear_banner_lights()
        set_studio_lights_visible(True)
        if is_pov_camera(getattr(context, "scene", None)):
            apply_camera_preset(context, "front", create=False)
        else:
            refresh_studio_camera(context)
    elif aim_camera:
        clear_banner_lights()
        set_studio_lights_visible(True)
        if is_pov_camera(getattr(context, "scene", None)):
            apply_camera_preset(context, "front", create=False)
        else:
            refresh_studio_camera(context)
    if (not static_banner) and play and not context.screen.is_animation_playing:
        bpy.ops.screen.animation_play()
    return True


def _stop_animation(context) -> None:
    screen = getattr(context, "screen", None)
    if screen is None or not getattr(screen, "is_animation_playing", False):
        return
    try:
        bpy.ops.screen.animation_cancel(restore_frame=False)
        return
    except Exception:
        pass
    try:
        bpy.ops.screen.animation_play()
    except Exception:
        pass


def _apply_banner_staging(context, path: Path, arm: bpy.types.Object, setup: dict | None = None) -> None:
    from ..naming.anim import guess_legend_from_anim
    from ..naming.cosmetics import banner_setup_for

    if not setup:
        setup = banner_setup_for(path.name, guess_legend_from_anim(path.name))
    apply_camera_pov(
        context,
        create=True,
        fov=setup.get("fov"),
        isolate=True,
        offset=setup.get("offset"),
    )
    context.view_layer.update()
    try:
        context.view_layer.depsgraph.update()
    except Exception:
        pass
    apply_banner_lights(context, setup, None)


def _purge_victim_characters(context) -> None:
    from ..extras import tagged_armatures

    victims = [
        arm
        for arm in tagged_armatures(context.scene, include_victims=True)
        if arm.get(CHAR_VICTIM)
    ]
    for arm in victims:
        try:
            delete_victim_objects(arm)
        except Exception:
            pass


def duplicate_character(context, arm: bpy.types.Object):
    from ..extras import tag_character

    arm = _require_armature(arm, "attacker")
    _unhide(arm)
    mapping: dict = {}
    home = _ensure_named_collection(context, f"{strip_blender_suffix(arm.name)}_victim")
    try:
        new_arm = arm.copy()
        if getattr(arm, "data", None) is not None:
            new_arm.data = arm.data.copy()
    except Exception as exc:
        raise RuntimeError(f"Could not duplicate '{arm.name}' as victim: {exc}") from exc
    if new_arm is None:
        raise RuntimeError(f"Could not duplicate '{arm.name}' as victim.")
    _set_single_collection(new_arm, home)
    mapping[arm] = new_arm
    children = getattr(arm, "children_recursive", None)
    pool = list(children) if children is not None else list(getattr(arm, "children", []))
    for child in pool:
        try:
            dup = child.copy()
            if getattr(child, "data", None) is not None:
                dup.data = child.data.copy()
        except Exception:
            continue
        _set_single_collection(dup, home)
        mapping[child] = dup
    for old, new in mapping.items():
        parent = getattr(old, "parent", None)
        if parent in mapping:
            new.parent = mapping[parent]
            try:
                new.matrix_parent_inverse = old.matrix_parent_inverse.copy()
            except Exception:
                pass
        if new.type == "MESH":
            for mod in new.modifiers:
                if mod.type == "ARMATURE" and getattr(mod, "object", None) in mapping:
                    mod.object = mapping[mod.object]
    victim = new_arm
    try:
        if victim.animation_data:
            victim.animation_data_clear()
    except Exception:
        pass
    victim[CHAR_VICTIM] = True
    victim["apex_victim_custom"] = False
    tag_character(
        victim,
        folder=arm.get("apex_texture_dir"),
        cast_path=arm.get("apex_cast_path"),
        collection=home.name,
    )
    _sync_transform(arm, victim)
    hide_rig(victim)
    return victim


def import_victim_from_cast(context, filepath: str, attacker: bpy.types.Object):
    from ..extras import tag_character
    from ..node_adder import current_node_adder
    from .. import utils

    scene = context.scene
    saved_cast = getattr(scene, "apex_cast_path", "")
    saved_tex = getattr(scene, "apex_texture_dir", "")
    saved_char = getattr(scene, "apex_character", "")
    saved_anim = getattr(scene, "apex_anim_dir", "")
    arm, folder = import_cast_model(context, filepath)
    try:
        scene.apex_cast_path = saved_cast
        scene.apex_texture_dir = saved_tex
        scene.apex_character = saved_char
        scene.apex_anim_dir = saved_anim
    except Exception:
        pass
    if arm is None:
        raise RuntimeError(f"Victim CAST has no armature: {filepath}")
    apply_model_size(arm)
    try:
        utils.shade_selected([arm], current_node_adder(scene), folder=folder, finish=False)
    except Exception as exc:
        log.warning("Victim shade skipped for %s: %s", arm.name, exc)
    arm[CHAR_VICTIM] = True
    arm["apex_victim_custom"] = True
    tag_character(arm, folder=folder, cast_path=filepath)
    _park_victim(context, arm)
    _sync_transform(attacker, arm)
    hide_rig(arm)
    remember_character(attacker)
    return arm


def has_custom_victim(context, attacker=None) -> bool:
    victim = existing_victim(context)
    if victim is None:
        return False
    if victim.get("apex_victim_custom"):
        return True
    if attacker is None:
        attacker = resolve_character(context)
    if attacker is None:
        return False
    a_path = str(attacker.get("apex_cast_path") or "")
    v_path = str(victim.get("apex_cast_path") or "")
    if not a_path or not v_path:
        return False
    try:
        return Path(a_path).resolve() != Path(v_path).resolve()
    except Exception:
        return a_path != v_path


def apply_finisher_full(
    context,
    attack_path: str,
    victim_path: str,
    arm: bpy.types.Object,
    victim_cast: str = "",
    force_base: bool = False,
) -> list[str]:
    arm = _require_armature(arm, "attacker")
    notes: list[str] = []
    if context.screen.is_animation_playing:
        bpy.ops.screen.animation_play()
    saved = _capture_transform(arm)
    victim = None
    if victim_cast:
        _purge_victim_characters(context)
        victim = import_victim_from_cast(context, victim_cast, arm)
    elif force_base:
        _purge_victim_characters(context)
        victim = duplicate_character(context, arm)
    if victim is None:
        victim = existing_victim(context)
    if victim is None:
        victim = duplicate_character(context, arm)
    victim = _require_armature(victim, "victim")
    atk = attack_path or victim_path
    vic = victim_path or attack_path
    if not atk:
        raise RuntimeError("No finisher attacker animation path.")
    if not vic:
        notes.append("No separate victim clip — attacker animation is used on both.")
    apply_cast_animation(context, atk, arm, play=False, aim_camera=False)
    _restore_transform(arm, saved)
    if not _object_alive(victim):
        log.warning("Victim was removed while loading attacker clip; duplicating again")
        victim = duplicate_character(context, arm)
        victim = _require_armature(victim, "victim")
    if vic:
        apply_cast_animation(context, vic, victim, play=False, aim_camera=False)
        _restore_transform(victim, saved)
    if not _object_alive(arm) or not _object_alive(victim):
        raise RuntimeError("Attacker or victim disappeared after loading finisher clips.")
    _unhide(arm)
    _unhide(victim)
    if not _armature_has_bone(arm, START_BONE):
        notes.append(f"Attacker is missing bone '{START_BONE}' — victim alignment skipped")
    elif not _armature_has_bone(victim, START_BONE):
        notes.append(f"Victim is missing bone '{START_BONE}' — victim alignment skipped")
    else:
        _place_victim(arm, victim)
    _park_victim(context, victim)
    hide_rig(arm)
    hide_rig(victim)
    remember_character(arm)
    context.view_layer.update()
    if not context.screen.is_animation_playing:
        bpy.ops.screen.animation_play()
    refresh_studio_camera(context)
    deselect_all(context)
    for note in notes:
        log.warning("%s", note)
    return notes


def clear_animation(context, arm: bpy.types.Object) -> None:
    if context.screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
    make_armature_active(context, arm)
    if arm.animation_data:
        arm.animation_data.action = None
        tracks = arm.animation_data.nla_tracks
        while tracks:
            tracks.remove(tracks[0])
        arm.animation_data_clear()
    for bone in arm.pose.bones:
        bone.matrix_basis.identity()
    children = getattr(arm, "children_recursive", None)
    pool = list(children) if children is not None else list(getattr(arm, "children", []))
    for child in pool:
        ad = getattr(child, "animation_data", None)
        if ad is not None:
            child.animation_data_clear()
    context.scene.frame_set(context.scene.frame_start)
    restore_studio_camera(context)
    hide_rig(arm)
    _purge_victim_characters(context)


