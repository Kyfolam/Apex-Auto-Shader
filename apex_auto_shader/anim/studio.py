from __future__ import annotations

import math

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from .character import resolve_character
from .const import (
    CAM_BONES,
    CLOSEUP_DIST,
    CLOSEUP_LENS,
    CON_CAM_LOC,
    CON_CAM_NAMES,
    CON_CAM_TRACK,
    CON_FOLLOW_LOC,
    CON_FOLLOW_ROT,
    CON_STUDIO_TRACK,
    HEAD_BONES,
    LAYOUT_FORWARD,
    LAYOUT_UP,
    PORTRAIT_RES_X,
    PORTRAIT_RES_Y,
    POV_BONES,
    POV_FOV_DEG,
    POV_LENS,
    STAGING_CAMERA,
    STAGING_COLL,
    STAGING_EMPTY,
    STAGING_LIGHTS,
    STAGING_OBJECTS,
    STAGING_PIVOT,
    STAGING_TARGET,
    STUDIO_LENS,
    BANNER_LIGHT_TAG,
    HOLOCARD_LIGHTS,
)
from ..blender_compat import resolve_armature


def redraw_view3d(context) -> None:
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def _look_through_camera(context, cam) -> None:
    try:
        context.scene.camera = cam
    except Exception:
        pass
    screen = getattr(context, "screen", None)
    areas = getattr(screen, "areas", []) if screen is not None else []
    for area in areas:
        if getattr(area, "type", "") != "VIEW_3D":
            continue
        for space in getattr(area, "spaces", []):
            if getattr(space, "type", "") != "VIEW_3D":
                continue
            try:
                space.camera = cam
                space.region_3d.view_perspective = "CAMERA"
            except Exception:
                pass


_POV_RES_X = "apex_pov_prev_res_x"
_POV_RES_Y = "apex_pov_prev_res_y"
_POV_RES_PCT = "apex_pov_prev_res_pct"
_POV_RES_SAVED = "apex_pov_res_saved"


def apply_portrait_render(scene, enabled: bool = True) -> None:
    """Banner holocards are 9:16. Studio presets restore the previous size."""
    if scene is None:
        return
    render = getattr(scene, "render", None)
    if render is None:
        return
    if enabled:
        if not scene.get(_POV_RES_SAVED):
            try:
                scene[_POV_RES_X] = int(render.resolution_x)
                scene[_POV_RES_Y] = int(render.resolution_y)
                scene[_POV_RES_PCT] = int(getattr(render, "resolution_percentage", 100) or 100)
                scene[_POV_RES_SAVED] = True
            except Exception:
                pass
        try:
            render.resolution_x = PORTRAIT_RES_X
            render.resolution_y = PORTRAIT_RES_Y
        except Exception:
            pass
        return
    if not scene.get(_POV_RES_SAVED):
        return
    try:
        if _POV_RES_X in scene:
            render.resolution_x = int(scene[_POV_RES_X])
        if _POV_RES_Y in scene:
            render.resolution_y = int(scene[_POV_RES_Y])
        if _POV_RES_PCT in scene and hasattr(render, "resolution_percentage"):
            render.resolution_percentage = int(scene[_POV_RES_PCT])
    except Exception:
        pass
    for key in (_POV_RES_X, _POV_RES_Y, _POV_RES_PCT, _POV_RES_SAVED):
        try:
            del scene[key]
        except Exception:
            pass


def _find_pose_bone(arm: bpy.types.Object, name: str):
    bones = arm.pose.bones
    key = name.lower()
    if name in bones:
        return bones[name]
    for bone in bones:
        if bone.name.lower() == key:
            return bone
    for bone in bones:
        stem = bone.name.lower().rsplit(".", 1)[0]
        if stem == key:
            return bone
    for bone in bones:
        if key in bone.name.lower():
            return bone
    return None


def _strip_named_constraints(obj: bpy.types.Object, names: set[str]) -> None:
    for con in list(obj.constraints):
        if con.name in names:
            obj.constraints.remove(con)


def _set_camera_shift(cam: bpy.types.Object, holocard: bool) -> None:
    """Holocard: jx_c_pov is the top edge of the 9:16 frame, not the image center.

    Damped Track keeps the optical axis on POV. Vertical lens shift then places
    that axis on the top edge so the body fills the card. Shift is a fraction of
    render width; half the portrait height = 0.5 * (1920 / 1080).
    """
    data = getattr(cam, "data", None)
    if data is None:
        return
    try:
        data.shift_x = 0.0
        data.shift_y = (-0.5 * (PORTRAIT_RES_Y / PORTRAIT_RES_X)) if holocard else 0.0
    except Exception:
        pass


def _set_studio_lens(cam: bpy.types.Object) -> None:
    data = cam.data
    try:
        data.lens_unit = "MILLIMETERS"
    except Exception:
        pass
    try:
        data.sensor_fit = "VERTICAL"
    except Exception:
        pass
    data.lens = STUDIO_LENS
    data.clip_start = 0.01
    data.clip_end = 1000.0
    _set_camera_shift(cam, False)


def _front_distance(height: float, radius: float) -> float:
    try:
        half = math.tan(math.radians(19.0))
    except Exception:
        half = 0.34
    return max(height * 0.56 / max(half, 0.12), height * 2.35, radius * 3.8, 1.5)


def _set_closeup_lens(cam: bpy.types.Object) -> None:
    data = cam.data
    try:
        data.lens_unit = "MILLIMETERS"
    except Exception:
        pass
    try:
        data.sensor_fit = "VERTICAL"
    except Exception:
        pass
    data.lens = CLOSEUP_LENS
    data.clip_start = 0.01
    data.clip_end = 1000.0
    _set_camera_shift(cam, False)


def _ensure_collection(context) -> bpy.types.Collection:
    coll = bpy.data.collections.get(STAGING_COLL)
    if coll is None:
        coll = bpy.data.collections.new(STAGING_COLL)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


def studio_camera_exists() -> bool:
    coll = bpy.data.collections.get(STAGING_COLL)
    cam = bpy.data.objects.get(STAGING_CAMERA)
    return (coll is not None) or (cam is not None and getattr(cam, "type", "") == "CAMERA")


def is_pov_camera(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return str(getattr(scene, "apex_cam_preset", "") or "") == "pov"


def refresh_studio_camera(context) -> bool:
    if not studio_camera_exists():
        return False
    if is_pov_camera(getattr(context, "scene", None)):
        apply_camera_pov(context, create=False)
        return True
    return True


def _hide_imported_cameras(before_names: set[str]) -> None:
    skip = set(STAGING_OBJECTS)
    for name in list(bpy.data.objects.keys()):
        if name in before_names or name in skip:
            continue
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        low = name.lower()
        if obj.type != "CAMERA" and "capture" not in low and "camera" not in low:
            continue
        try:
            obj.hide_set(True)
            obj.hide_viewport = True
            obj.hide_render = True
        except Exception:
            pass


def _flip_object_y(obj) -> None:
    try:
        loc = obj.location.copy()
        loc.y = -loc.y
        obj.location = loc
        obj.rotation_mode = "XYZ"
        euler = obj.rotation_euler.copy()
        euler.z += math.pi
        obj.rotation_euler = euler
    except Exception:
        pass


def _flip_imported_cameras(before_names: set[str]) -> None:
    skip = set(STAGING_OBJECTS)
    for name in list(bpy.data.objects.keys()):
        if name in before_names or name in skip:
            continue
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        is_cam = obj.type == "CAMERA"
        low = name.lower()
        if not is_cam and "capture" not in low and "camera" not in low:
            continue
        _flip_object_y(obj)


def use_imported_capture(context, before_names: set[str]) -> bool:
    """Keep CAST capture-mode camera (and lights if present) and look through it.

    ``*_capturemode`` clips store the holocard camera. Lighting in the CAST is
    optional — Apex uses a separate capture light kit — so studio lights stay
    unless the clip actually imported lamps.
    """
    skip = set(STAGING_OBJECTS)
    cams: list = []
    lights: list = []
    for name in list(bpy.data.objects.keys()):
        if name in before_names or name in skip:
            continue
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        low = name.lower()
        if obj.type == "CAMERA" or "capture" in low or "camera" in low:
            cams.append(obj)
        elif obj.type == "LIGHT":
            lights.append(obj)
    if not cams:
        return False
    for cam in cams:
        _flip_object_y(cam)
        try:
            cam.hide_set(False)
            cam.hide_viewport = False
            cam.hide_render = False
        except Exception:
            pass
    for light in lights:
        _flip_object_y(light)
        try:
            light.hide_set(False)
            light.hide_viewport = False
            light.hide_render = False
        except Exception:
            pass
    cam = next((c for c in cams if getattr(c, "type", "") == "CAMERA"), cams[0])
    try:
        context.scene.camera = cam
    except Exception:
        pass
    screen = getattr(context, "screen", None)
    areas = getattr(screen, "areas", []) if screen is not None else []
    for area in areas:
        if getattr(area, "type", "") != "VIEW_3D":
            continue
        for space in getattr(area, "spaces", []):
            if getattr(space, "type", "") != "VIEW_3D":
                continue
            try:
                space.camera = cam
                space.region_3d.view_perspective = "CAMERA"
            except Exception:
                pass
    return True


def restore_studio_camera(context) -> None:
    refresh_studio_camera(context)


def _character_metrics(obj: bpy.types.Object | None) -> tuple[Vector, float, float]:
    origin, height, radius, _center = _character_bounds(obj)
    return origin, height, radius


def _character_bounds(obj: bpy.types.Object | None) -> tuple[Vector, float, float, Vector]:
    fallback = Vector((0.0, 0.0, 0.0))
    if obj is None:
        return fallback, 1.8, 0.6, Vector((0.0, 0.9, 0.0))
    target = resolve_armature(obj) or obj
    coords: list[Vector] = []
    pool = [target]
    children = getattr(target, "children_recursive", None)
    pool.extend(list(children) if children is not None else list(getattr(target, "children", [])))
    for item in pool:
        if item.type not in {"MESH", "ARMATURE"}:
            continue
        try:
            for corner in item.bound_box:
                coords.append(item.matrix_world @ Vector(corner))
        except Exception:
            coords.append(item.matrix_world.translation.copy())
    origin = target.matrix_world.translation.copy()
    if not coords:
        return origin, 1.8, 0.6, origin + Vector((0.0, 0.9, 0.0))
    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]
    height = max(max(ys) - min(ys), 0.4)
    radius = max(max(xs) - min(xs), max(zs) - min(zs), 0.3) * 0.5
    center = Vector(
        (
            (min(xs) + max(xs)) * 0.5,
            (min(ys) + max(ys)) * 0.5,
            (min(zs) + max(zs)) * 0.5,
        )
    )
    return origin, height, radius, center


def _action_fcurves(action):
    if action is None:
        return []
    curves = []
    seen: set[int] = set()

    def add(seq) -> None:
        for curve in list(seq or []):
            ident = id(curve)
            if ident in seen:
                continue
            seen.add(ident)
            curves.append(curve)

    raw = getattr(action, "fcurves", None)
    if raw is not None:
        try:
            add(raw)
        except Exception:
            pass
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
                    add(getattr(bag, "fcurves", None))
    except Exception:
        pass
    try:
        slots = list(getattr(action, "slots", []) or [])
        for layer in getattr(action, "layers", []) or []:
            for strip in getattr(layer, "strips", []) or []:
                bag_fn = getattr(strip, "channelbag", None)
                if callable(bag_fn):
                    targets = slots or [None]
                    for slot in targets:
                        try:
                            bag = bag_fn(slot, ensure=False) if slot is not None else bag_fn()
                        except TypeError:
                            try:
                                bag = bag_fn(slot) if slot is not None else bag_fn()
                            except Exception:
                                bag = None
                        except Exception:
                            bag = None
                        if bag is not None:
                            add(getattr(bag, "fcurves", None))
                extra = getattr(strip, "channelbags", None)
                if extra:
                    for item in extra:
                        add(getattr(item, "fcurves", None))
    except Exception:
        pass
    return curves


def _remove_staging() -> None:
    clear_banner_lights()
    for name in STAGING_OBJECTS:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    cam = bpy.data.cameras.get(STAGING_CAMERA)
    if cam is not None:
        bpy.data.cameras.remove(cam)
    for name in STAGING_LIGHTS:
        light = bpy.data.lights.get(name)
        if light is not None:
            bpy.data.lights.remove(light)


def _damped_track(obj: bpy.types.Object, target: bpy.types.Object, bone: str = "") -> None:
    con = obj.constraints.new("DAMPED_TRACK")
    con.name = CON_CAM_TRACK
    con.target = target
    if bone:
        con.subtarget = bone
    con.track_axis = "TRACK_NEGATIVE_Z"


def _track_to(obj: bpy.types.Object, target: bpy.types.Object) -> None:
    con = obj.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"


def _active_camera(context) -> bpy.types.Object | None:
    cam = getattr(getattr(context, "scene", None), "camera", None)
    if cam is not None and getattr(cam, "type", "") == "CAMERA":
        return cam
    cam = bpy.data.objects.get(STAGING_CAMERA)
    if cam is not None and getattr(cam, "type", "") == "CAMERA":
        return cam
    return None


def _layout_up() -> Vector:
    return Vector(LAYOUT_UP)


def _layout_forward() -> Vector:
    return Vector(LAYOUT_FORWARD)


def _studio_cam_offset(offset: Vector, dist: float, three_quarter: bool = False) -> Vector:
    fwd = _layout_forward() * dist
    if three_quarter:
        side = _layout_up().cross(_layout_forward())
        if side.length_squared < 1e-8:
            side = Vector((1.0, 0.0, 0.0))
        side = side.normalized() * (dist * 0.42)
        fwd = fwd * 0.86
        return offset + side + fwd
    return offset + fwd


def _bone_world_loc(arm, bone) -> Vector:
    return (arm.matrix_world @ bone.matrix).to_translation()


def _look_at_y_up(cam: bpy.types.Object, origin: Vector, target: Vector) -> None:
    direction = target - origin
    if direction.length_squared < 1e-12:
        return
    z_axis = -direction.normalized()
    world_up = _layout_up()
    x_axis = world_up.cross(z_axis)
    if x_axis.length_squared < 1e-12:
        x_axis = Vector((1.0, 0.0, 0.0))
    x_axis.normalize()
    y_axis = z_axis.cross(x_axis)
    rot_world = Matrix(
        (
            (x_axis.x, y_axis.x, z_axis.x),
            (x_axis.y, y_axis.y, z_axis.y),
            (x_axis.z, y_axis.z, z_axis.z),
        )
    ).to_quaternion()
    cam.rotation_mode = "QUATERNION"
    if cam.parent is not None:
        cam.rotation_quaternion = cam.parent.matrix_world.to_quaternion().inverted() @ rot_world
    else:
        cam.rotation_quaternion = rot_world


def _point_camera_at(cam: bpy.types.Object, world_target: Vector) -> None:
    _look_at_y_up(cam, cam.matrix_world.translation.copy(), world_target)


@persistent
def sync_banner_camera(scene, *_args) -> None:
    """One-shot aim. Not a frame handler — rewriting rotation every frame spins the camera."""
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return
    cam = bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        return
    try:
        arm = resolve_character(bpy.context)
    except Exception:
        return
    cam_bone = _pose_bone(arm, CAM_BONES)
    pov = _pose_bone(arm, POV_BONES)
    if arm is None or cam_bone is None or pov is None:
        return
    _look_at_y_up(cam, _bone_world_loc(arm, cam_bone), _bone_world_loc(arm, pov))


def _clear_cam_lock(obj: bpy.types.Object | None) -> None:
    """Drop every constraint — leftover Track To / Damped Track will spin the camera."""
    if obj is None:
        return
    constraints = getattr(obj, "constraints", None)
    if constraints is None:
        return
    for con in list(constraints):
        try:
            constraints.remove(con)
        except Exception:
            pass
    try:
        if obj.animation_data:
            obj.animation_data_clear()
    except Exception:
        pass


def add_camera_rig(context, obj: bpy.types.Object | None) -> bpy.types.Object:
    origin, height, radius = _character_metrics(obj)
    _remove_staging()
    coll = _ensure_collection(context)

    empty = bpy.data.objects.new(STAGING_EMPTY, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.location = origin
    coll.objects.link(empty)

    look = bpy.data.objects.new(STAGING_TARGET, None)
    look.empty_display_type = "SPHERE"
    look.empty_display_size = 0.05
    look.location = origin + _layout_up() * (height * 0.52)
    coll.objects.link(look)
    look.hide_viewport = True
    look.hide_render = True

    pivot = bpy.data.objects.new(STAGING_PIVOT, None)
    pivot.empty_display_type = "PLAIN_AXES"
    coll.objects.link(pivot)
    pivot.hide_viewport = True
    pivot.hide_render = True

    dist = _front_distance(height, radius)
    mid = height * 0.48
    empty["apex_studio_dist"] = dist
    empty["apex_studio_lift"] = mid
    empty["apex_studio_height"] = height

    cam_data = bpy.data.cameras.new(STAGING_CAMERA)
    cam = bpy.data.objects.new(STAGING_CAMERA, cam_data)
    cam.parent = empty
    cam.location = _layout_up() * mid + _layout_forward() * dist
    coll.objects.link(cam)
    _set_studio_lens(cam)
    context.scene.camera = cam

    def add_area(name: str, loc, energy: float, size: float):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "SQUARE"
        data.size = size
        light = bpy.data.objects.new(name, data)
        light.location = loc
        light.parent = empty
        coll.objects.link(light)
        _track_to(light, look)
        return light

    add_area(STAGING_LIGHTS[0], (-dist * 0.55, height * 0.85, dist * 0.35), 450.0, max(height * 0.8, 0.6))
    add_area(STAGING_LIGHTS[1], (0.0, height * 1.55, -dist * 0.12), 280.0, max(height * 1.1, 0.8))
    add_area(STAGING_LIGHTS[2], (dist * 0.55, height * 0.55, dist * 0.22), 160.0, max(height * 0.7, 0.5))
    preset = getattr(context.scene, "apex_cam_preset", "front") or "front"
    if preset == "pov":
        preset = "front"
    apply_camera_preset(context, preset)
    return cam


def ensure_camera_rig(context) -> bpy.types.Object:
    cam = bpy.data.objects.get(STAGING_CAMERA)
    empty = bpy.data.objects.get(STAGING_EMPTY)
    if cam is None or cam.type != "CAMERA" or empty is None:
        cam = add_camera_rig(context, resolve_character(context))
    return cam


def _pose_bone(arm, names) -> object | None:
    if arm is None:
        return None
    if isinstance(names, str):
        names = (names,)
    for name in names:
        bone = _find_pose_bone(arm, name)
        if bone is not None:
            return bone
    return None


def _copy_loc(obj, arm, bone=None, name=CON_FOLLOW_LOC):
    _strip_named_constraints(obj, {name, CON_FOLLOW_LOC, CON_FOLLOW_ROT, CON_CAM_LOC, CON_CAM_TRACK, CON_STUDIO_TRACK})
    loc = obj.constraints.new("COPY_LOCATION")
    loc.name = name
    loc.target = arm
    if bone is not None:
        loc.subtarget = bone.name
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0.0, 0.0, 0.0)
    return loc


def apply_camera_preset(context, preset: str, create: bool = True) -> None:
    if preset == "pov":
        apply_camera_pov(context, create=create)
        return
    key = preset if preset in {"front", "three_quarter", "closeup"} else "front"
    try:
        context.scene.apex_cam_preset = key
    except Exception:
        pass
    clear_banner_lights()
    set_studio_lights_visible(True)
    if not create and not studio_camera_exists():
        return
    arm = resolve_character(context)
    cam = ensure_camera_rig(context) if create else bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or cam.type != "CAMERA":
        return
    empty = bpy.data.objects.get(STAGING_EMPTY)
    look = bpy.data.objects.get(STAGING_TARGET)
    origin, height, radius, center = _character_bounds(arm)
    dist = _front_distance(height, radius)
    offset = center - origin
    _clear_cam_lock(empty)
    _clear_cam_lock(look)
    _clear_cam_lock(cam)
    _clear_cam_lock(bpy.data.objects.get(STAGING_PIVOT))
    if empty is not None:
        empty["apex_studio_dist"] = dist
        empty["apex_studio_lift"] = offset.y
        empty["apex_studio_height"] = height
        if empty.animation_data:
            empty.animation_data_clear()
        empty.rotation_mode = "XYZ"
        empty.rotation_euler = (0.0, 0.0, 0.0)
        empty.location = origin
    context.view_layer.update()
    if key == "closeup":
        apply_portrait_render(getattr(context, "scene", None), False)
        _apply_closeup_portrait(context, cam, arm, empty, look, height)
        _set_passepartout(cam, 0.0)
        return
    if look is not None:
        look.parent = empty
        look.location = (offset.x, offset.y, offset.z)
    cam.parent = empty
    cam.parent_type = "OBJECT"
    try:
        cam.parent_bone = ""
    except Exception:
        pass
    if key == "three_quarter":
        cam.location = _studio_cam_offset(offset, dist, three_quarter=True)
    else:
        cam.location = _studio_cam_offset(offset, dist)
    _set_studio_lens(cam)
    _set_passepartout(cam, 0.0)
    clear_banner_lights()
    set_studio_lights_visible(True)
    apply_portrait_render(getattr(context, "scene", None), False)
    context.view_layer.update()
    _point_camera_at(cam, center)
    context.scene.camera = cam
    context.view_layer.update()


def _apply_closeup_portrait(context, cam, arm, empty, look, height) -> None:
    head = _pose_bone(arm, HEAD_BONES)
    _clear_cam_lock(cam)
    if arm is not None and head is not None:
        look_at = _bone_world_loc(arm, head)
    elif empty is not None:
        look_at = empty.matrix_world.translation + _layout_up() * (height * 0.88)
    else:
        look_at = _layout_up() * (height * 0.88)
    cam.parent = empty
    cam.parent_type = "OBJECT"
    try:
        cam.parent_bone = ""
    except Exception:
        pass
    push = _layout_forward() * CLOSEUP_DIST + _layout_up() * 0.06
    if empty is not None:
        local = empty.matrix_world.inverted() @ look_at
        cam.location = local + push
    else:
        cam.location = look_at + push
    if look is not None:
        look.parent = empty
        if empty is not None:
            look.location = empty.matrix_world.inverted() @ look_at
        else:
            look.location = look_at
    _set_closeup_lens(cam)
    context.view_layer.update()
    _point_camera_at(cam, look_at)
    context.scene.camera = cam
    context.view_layer.update()


def _fcurve_value(curve, frame: float) -> float | None:
    try:
        return float(curve.evaluate(frame))
    except Exception:
        pass
    kps = getattr(curve, "keyframe_points", None)
    if not kps:
        return None
    try:
        return float(kps[0].co[1])
    except Exception:
        return None


def _as_fov_degrees(value) -> float | None:
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if 5.0 <= val <= 170.0:
        return val
    if 0.08 <= val <= 3.0:
        return math.degrees(val)
    return None


def detect_cast_camera_fov(arm=None) -> float | None:
    """Read FOV from CAST-imported cameras or animation curves, if present."""
    for obj in list(bpy.data.objects):
        if getattr(obj, "type", "") != "CAMERA" or obj.name == STAGING_CAMERA:
            continue
        data = getattr(obj, "data", None)
        if data is None:
            continue
        raw = getattr(data, "angle", None)
        found = _as_fov_degrees(math.degrees(raw) if raw is not None and raw < 4.0 else raw)
        if found:
            return found
        lens = getattr(data, "lens", None)
        width = getattr(data, "sensor_width", 36.0) or 36.0
        if lens and float(lens) > 1.0:
            try:
                fov = math.degrees(2.0 * math.atan((width * 0.5) / float(lens)))
                found = _as_fov_degrees(fov)
                if found:
                    return found
            except Exception:
                pass
    frame = float(getattr(getattr(bpy.context, "scene", None), "frame_current", 0) or 0)
    action = None
    if arm is not None:
        action = getattr(getattr(arm, "animation_data", None), "action", None)
    if action is None:
        return None
    for curve in _action_fcurves(action):
        path = (getattr(curve, "data_path", "") or "").lower()
        if "fov" not in path and "field_of_view" not in path and not path.endswith("lens"):
            continue
        raw = _fcurve_value(curve, frame)
        if raw is None:
            continue
        if "lens" in path and "fov" not in path:
            try:
                found = _as_fov_degrees(math.degrees(2.0 * math.atan(18.0 / float(raw))))
                if found:
                    return found
            except Exception:
                continue
        found = _as_fov_degrees(raw)
        if found:
            return found
    if arm is not None:
        bone = _pose_bone(arm, CAM_BONES)
        if bone is not None:
            keys = list(bone.keys()) if hasattr(bone, "keys") else []
            for key in keys:
                if "fov" in str(key).lower():
                    found = _as_fov_degrees(bone[key])
                    if found:
                        return found
    return None


def _set_pov_lens(cam: bpy.types.Object, arm=None, fov=None) -> None:
    data = cam.data
    if fov is None:
        fov = detect_cast_camera_fov(arm)
    try:
        data.lens_unit = "FOV"
    except Exception:
        pass
    # itemflav horizontalFOV is the short side of the 9:16 holocard.
    try:
        data.sensor_fit = "HORIZONTAL" if fov is not None else "VERTICAL"
    except Exception:
        pass
    if fov is not None:
        try:
            data.angle = math.radians(float(fov))
        except Exception:
            data.lens = POV_LENS
    else:
        try:
            data.angle = math.radians(POV_FOV_DEG)
        except Exception:
            data.lens = POV_LENS
    data.clip_start = 0.01
    data.clip_end = 1000.0
    _set_camera_shift(cam, True)


def apply_camera_pov(context, create: bool = True, fov=None, isolate: bool = False, offset=None) -> None:
    """Lock the studio camera to jx_c_camera, aiming at jx_c_pov."""
    arm = resolve_character(context)
    if arm is None:
        raise RuntimeError("No character armature. Import a CAST model first.")
    cam_bone = _pose_bone(arm, CAM_BONES)
    pov_bone = _pose_bone(arm, POV_BONES)
    if cam_bone is None:
        raise RuntimeError("Bone 'jx_c_camera' not found on this armature.")
    if pov_bone is None:
        raise RuntimeError("Bone 'jx_c_pov' not found on this armature.")
    cam = bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or cam.type != "CAMERA":
        if not create:
            return
        cam = add_camera_rig(context, arm)
    _clear_cam_lock(cam)
    _clear_cam_lock(bpy.data.objects.get(STAGING_EMPTY))
    cam.parent = None
    cam.parent_type = "OBJECT"
    try:
        cam.parent_bone = ""
    except Exception:
        pass
    loc = cam.constraints.new("COPY_LOCATION")
    loc.name = CON_CAM_LOC
    loc.target = arm
    loc.subtarget = cam_bone.name
    # Bak behavior: never apply camOffset via COPY_LOCATION use_offset —
    # that shifted the POV camera wrongly. FOV / portrait stay below.
    # `offset` kept in signature for callers (banner_setup_for) but ignored here.
    loc.use_offset = False
    cam.location = (0.0, 0.0, 0.0)
    try:
        cam.delta_location = (0.0, 0.0, 0.0)
        cam.delta_rotation_euler = (0.0, 0.0, 0.0)
    except Exception:
        pass
    _set_pov_lens(cam, arm, fov=fov)
    _set_passepartout(cam, 1.0 if isolate else 0.7)
    try:
        data = cam.data
        if fov is not None:
            data.sensor_fit = "HORIZONTAL"
            data.lens_unit = "FOV"
            data.angle = math.radians(float(fov))
        else:
            data.sensor_fit = "VERTICAL"
    except Exception:
        pass
    try:
        context.scene.apex_cam_preset = "pov"
    except Exception:
        pass
    apply_portrait_render(getattr(context, "scene", None), True)
    context.scene.camera = cam
    context.view_layer.update()
    try:
        context.view_layer.depsgraph.update()
    except Exception:
        pass
    sync_banner_camera(getattr(context, "scene", None))
    _damped_track(cam, arm, pov_bone.name)
    _look_through_camera(context, cam)
    redraw_view3d(context)


def _set_passepartout(cam, alpha: float) -> None:
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        return
    data = getattr(cam, "data", None)
    if data is None:
        return
    try:
        data.show_passepartout = float(alpha) > 0.001
        data.passepartout_alpha = max(0.0, min(1.0, float(alpha)))
    except Exception:
        pass


def apply_cast_camera_framing(context, cam, fov=None, isolate: bool = True) -> None:
    """FOV / portrait / isolate on a CAST-imported holocard camera."""
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        return
    _set_pov_lens(cam, None, fov=fov)
    _set_passepartout(cam, 1.0 if isolate else 0.7)
    try:
        if fov is not None:
            cam.data.sensor_fit = "HORIZONTAL"
            cam.data.lens_unit = "FOV"
            cam.data.angle = math.radians(float(fov))
    except Exception:
        pass
    try:
        context.scene.apex_cam_preset = "pov"
    except Exception:
        pass
    apply_portrait_render(getattr(context, "scene", None), True)
    _look_through_camera(context, cam)
    redraw_view3d(context)


def set_studio_lights_visible(visible: bool) -> None:
    hide = not visible
    for name in STAGING_LIGHTS:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            obj.hide_set(hide)
        except Exception:
            pass
        try:
            obj.hide_viewport = hide
            obj.hide_render = hide
        except Exception:
            pass


def clear_banner_lights() -> None:
    for obj in list(bpy.data.objects):
        tagged = False
        try:
            tagged = bool(obj.get(BANNER_LIGHT_TAG))
        except Exception:
            tagged = False
        if not tagged and obj.name not in HOLOCARD_LIGHTS:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    for name in HOLOCARD_LIGHTS:
        data = bpy.data.lights.get(name)
        if data is not None:
            try:
                bpy.data.lights.remove(data)
            except Exception:
                pass


def _banner_light_energy(brightness: float) -> float:
    # itemflav 0.05–0.4 is typical; a handful of legacy poses store 2–10.
    try:
        value = float(brightness)
    except (TypeError, ValueError):
        return 0.0
    if value <= 1e-6:
        return 0.0
    return 40.0 + min(value, 1.25) * 1800.0


def _light_num(spec: dict, *keys, default: float = 0.0) -> float:
    for key in keys:
        if spec.get(key) is None:
            continue
        try:
            return float(spec[key])
        except (TypeError, ValueError):
            continue
    return default


def _ensure_holocard_look(context, arm) -> object | None:
    coll = _ensure_collection(context)
    look = bpy.data.objects.get(STAGING_TARGET)
    if look is None:
        look = bpy.data.objects.new(STAGING_TARGET, None)
        look.empty_display_type = "SPHERE"
        look.empty_display_size = 0.05
        coll.objects.link(look)
    look.hide_viewport = True
    look.hide_render = True
    _clear_cam_lock(look)
    pov = _pose_bone(arm, POV_BONES)
    if arm is None or pov is None:
        return look
    loc = look.constraints.new("COPY_LOCATION")
    loc.name = CON_CAM_LOC
    loc.target = arm
    loc.subtarget = pov.name
    loc.use_offset = False
    look.parent = None
    return look


def _place_holocard_spots(context, arm, lights: list[dict]) -> list:
    """4-spot holocard kit from itemflav light0–3, parented to the active camera."""
    cam = _active_camera(context)
    if cam is None:
        return []
    coll = _ensure_collection(context)
    look_obj = _ensure_holocard_look(context, arm)
    context.view_layer.update()
    origin, height, radius, center = _character_bounds(arm)
    pov = _pose_bone(arm, POV_BONES)
    look = _bone_world_loc(arm, pov) if pov is not None else center
    cam_world = cam.matrix_world.translation.copy()
    forward = look - cam_world
    span = forward.length
    if span < 1e-6:
        forward = Vector(LAYOUT_FORWARD)
        span = max(height, 0.8)
    else:
        forward.normalize()
    up = Vector(LAYOUT_UP)
    right = up.cross(forward)
    if right.length_squared < 1e-8:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    up = forward.cross(right)
    up.normalize()
    # key, fill, rim, top — offsets as fractions of each light's itemflav distance
    layout = (
        (-0.50, 0.42, 0.22),
        (0.58, 0.18, 0.18),
        (0.12, 0.38, -0.78),
        (0.04, 0.95, 0.08),
    )
    created = []
    for idx, spec in enumerate(list(lights)[:4] or [{}] * 4):
        name = HOLOCARD_LIGHTS[idx] if idx < len(HOLOCARD_LIGHTS) else f"Apex Holocard {idx}"
        old = bpy.data.objects.get(name)
        if old is not None:
            try:
                bpy.data.objects.remove(old, do_unlink=True)
            except Exception:
                pass
        dist = _light_num(spec, "distance", default=800.0)
        world_d = max(span * (dist / 800.0), height * 0.15)
        lx, ly, lz = layout[idx] if idx < len(layout) else (0.0, 0.4, 0.2)
        world = look + right * (lx * world_d) + up * (ly * world_d) + forward * (lz * world_d)
        data = bpy.data.lights.new(name, "SPOT")
        data.energy = _banner_light_energy(_light_num(spec, "brightness", default=0.0))
        cone = _light_num(spec, "cone", default=50.0)
        try:
            data.spot_size = math.radians(max(8.0, min(160.0, cone)))
        except Exception:
            pass
        inner = _light_num(spec, "inner", "innercone", default=1.0)
        try:
            data.spot_blend = max(0.05, min(1.0, 1.0 - (inner / max(cone, 1.0))))
        except Exception:
            pass
        half = _light_num(spec, "half", "halfbrightfrac", default=0.25)
        try:
            data.use_custom_distance = True
            data.cutoff_distance = max(world_d * (2.2 + half * 3.0), span * 1.5)
        except Exception:
            pass
        try:
            data.use_shadow = spec.get("shadow", True) is not False
        except Exception:
            pass
        try:
            data.color = (1.0, 1.0, 1.0)
        except Exception:
            pass
        obj = bpy.data.objects.new(name, data)
        try:
            obj[BANNER_LIGHT_TAG] = True
        except Exception:
            pass
        coll.objects.link(obj)
        obj.parent = cam
        obj.parent_type = "OBJECT"
        try:
            obj.matrix_parent_inverse = Matrix.Identity(4)
        except Exception:
            pass
        try:
            obj.location = cam.matrix_world.inverted() @ world
        except Exception:
            obj.location = world
        if look_obj is not None:
            _strip_named_constraints(obj, set(CON_CAM_NAMES))
            _track_to(obj, look_obj)
        if data.energy <= 1e-6:
            try:
                obj.hide_viewport = True
                obj.hide_render = True
            except Exception:
                pass
        created.append(obj)
    return created


def tag_banner_light_objects(objects) -> None:
    for obj in objects:
        if obj is None:
            continue
        try:
            obj[BANNER_LIGHT_TAG] = True
        except Exception:
            pass


def apply_banner_lights(context, setup: dict | None, imported=None) -> None:
    """Rebuild the 4 itemflav spots for this pose. Always, even if specs are defaults."""
    clear_banner_lights()
    arm = resolve_character(context)
    for obj in list(imported or []):
        low = (getattr(obj, "name", "") or "").lower()
        if getattr(obj, "type", "") == "CAMERA" or "camera" in low:
            try:
                obj.hide_set(True)
                obj.hide_viewport = True
                obj.hide_render = True
            except Exception:
                pass
    context.view_layer.update()
    specs = list((setup or {}).get("lights") or [])
    _place_holocard_spots(context, arm, specs)
    set_studio_lights_visible(False)
