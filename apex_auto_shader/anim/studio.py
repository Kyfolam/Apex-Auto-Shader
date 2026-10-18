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


def apply_frame_orientation(scene) -> None:
    """Portrait or landscape from the camera panel toggle. Banner POV still forces portrait."""
    if scene is None:
        return
    portrait = bool(getattr(scene, "apex_cam_portrait", True))
    render = scene.render
    try:
        if portrait:
            render.resolution_x = 1080
            render.resolution_y = 1920
        else:
            render.resolution_x = 1920
            render.resolution_y = 1080
        render.resolution_percentage = 100
    except Exception:
        pass


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
    origin, height, radius, _center, _forward = _visual_frame(obj)
    return origin, height, radius


_FACE_BONES = (
    "def_c_hips",
    "def_c_pelvis",
    "def_c_spineA",
    "def_c_spine_01",
    "jx_c_start",
)


def _refresh_pose() -> None:
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    try:
        bpy.context.view_layer.depsgraph.update()
    except Exception:
        pass


def _evaluated_mesh(obj):
    try:
        return obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    except Exception:
        return obj


def _flatten(vec: Vector, up: Vector) -> Vector:
    flat = vec - up * vec.dot(up)
    if flat.length_squared < 1e-8:
        return Vector((0.0, 0.0, 0.0))
    return flat.normalized()


def _character_facing(arm) -> tuple[Vector, Vector]:
    """World up stays Y. Forward follows the posed hips, else the moved armature."""
    up = _layout_up()
    forward = _layout_forward()
    if arm is None:
        return up, forward
    bases = []
    bone = _pose_bone(arm, _FACE_BONES)
    if bone is not None:
        try:
            bases.append((arm.matrix_world @ bone.matrix).to_3x3())
        except Exception:
            pass
    try:
        bases.append(arm.matrix_world.to_3x3())
    except Exception:
        pass
    for basis in bases:
        for axis in (Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, -1.0))):
            flat = _flatten(basis @ axis, up)
            if flat.length_squared > 0.5:
                return up, flat
    return up, forward


def _align_staging(empty, origin: Vector, up: Vector, forward: Vector) -> None:
    y_axis = up.normalized()
    z_axis = _flatten(forward, y_axis)
    if z_axis.length_squared < 0.5:
        z_axis = _layout_forward()
    x_axis = y_axis.cross(z_axis)
    if x_axis.length_squared < 1e-8:
        x_axis = Vector((1.0, 0.0, 0.0))
    x_axis.normalize()
    z_axis = x_axis.cross(y_axis).normalized()
    empty.location = origin
    empty.rotation_mode = "QUATERNION"
    empty.rotation_quaternion = Matrix(
        (
            (x_axis.x, y_axis.x, z_axis.x),
            (x_axis.y, y_axis.y, z_axis.y),
            (x_axis.z, y_axis.z, z_axis.z),
        )
    ).to_quaternion()


def _character_bounds(obj: bpy.types.Object | None) -> tuple[Vector, float, float, Vector]:
    """Feet origin + visual center from the current pose, not the rest armature origin."""
    fallback = Vector((0.0, 0.0, 0.0))
    if obj is None:
        return fallback, 1.8, 0.6, Vector((0.0, 0.9, 0.0))
    _refresh_pose()
    target = resolve_armature(obj) or obj
    up = _layout_up()
    coords: list[Vector] = []
    pool = [target]
    children = getattr(target, "children_recursive", None)
    pool.extend(list(children) if children is not None else list(getattr(target, "children", [])))
    for item in pool:
        if getattr(item, "type", "") not in {"MESH", "ARMATURE"}:
            continue
        src = _evaluated_mesh(item) if item.type == "MESH" else item
        try:
            mat = src.matrix_world.copy()
            for corner in src.bound_box:
                coords.append(mat @ Vector(corner))
        except Exception:
            coords.append(item.matrix_world.translation.copy())
    arm = target if getattr(target, "type", "") == "ARMATURE" else resolve_armature(target)
    if arm is not None and getattr(arm, "pose", None) is not None:
        mw = arm.matrix_world
        for bone in arm.pose.bones:
            try:
                coords.append(mw @ bone.head)
                coords.append(mw @ bone.tail)
            except Exception:
                pass
    object_origin = target.matrix_world.translation.copy()
    if not coords:
        return object_origin, 1.8, 0.6, object_origin + up * 0.9
    along = [c.dot(up) for c in coords]
    low = min(along)
    high = max(along)
    height = max(high - low, 0.4)
    center = Vector((0.0, 0.0, 0.0))
    for c in coords:
        center += c
    center /= len(coords)
    # Feet under the visual center, so a posed/moved model is framed where it stands.
    origin = center - up * center.dot(up) + up * low
    flat = [c - up * c.dot(up) for c in coords]
    span = 0.3
    if flat:
        fx = [c.x for c in flat]
        fz = [c.z for c in flat]
        span = max(max(fx) - min(fx), max(fz) - min(fz), 0.3)
    radius = span * 0.5
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


def _bone_world_loc(arm, bone) -> Vector:
    return (arm.matrix_world @ bone.matrix).to_translation()


def _look_at_y_up(cam: bpy.types.Object, origin: Vector, target: Vector) -> None:
    if cam.parent is None:
        cam.matrix_world = _look_matrix(origin, target)
        return
    direction = target - origin
    if direction.length_squared < 1e-12:
        return
    world = _look_matrix(origin, target).to_quaternion()
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = cam.parent.matrix_world.to_quaternion().inverted() @ world


def _view3d_parts(context):
    area = getattr(context, "area", None)
    if area is not None and getattr(area, "type", "") == "VIEW_3D":
        region = next((r for r in area.regions if getattr(r, "type", "") == "WINDOW"), None)
        return area, region, area.spaces.active
    screen = getattr(context, "screen", None)
    areas = getattr(screen, "areas", []) if screen is not None else []
    for item in areas:
        if getattr(item, "type", "") != "VIEW_3D":
            continue
        region = next((r for r in item.regions if getattr(r, "type", "") == "WINDOW"), None)
        return item, region, item.spaces.active
    return None, None, None


def _view3d_space(context):
    _area, _region, space = _view3d_parts(context)
    return space


def _soften_studio_lights(cam, target: Vector) -> None:
    """Key / fill / rim far enough that the model is not blown out."""
    look = bpy.data.objects.get(STAGING_TARGET)
    if look is not None:
        _clear_cam_lock(look)
        look.parent = None
        look.location = target
    eye = cam.matrix_world.translation.copy()
    dist = max((eye - target).length, 2.4)
    forward = target - eye
    if forward.length_squared < 1e-8:
        forward = Vector((0.0, 0.0, -1.0))
    forward.normalize()
    up = _layout_up()
    right = up.cross(forward)
    if right.length_squared < 1e-8:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    spots = (
        (eye - right * dist * 1.35 + up * dist * 0.9 - forward * dist * 0.15, 180.0, max(dist * 1.6, 2.4), (1.0, 0.96, 0.9)),
        (target + up * dist * 2.0 - forward * dist * 0.15, 70.0, max(dist * 2.0, 3.0), (0.88, 0.92, 1.0)),
        (target - forward * dist * 1.7 + right * dist * 0.85 + up * dist * 0.6, 55.0, max(dist * 1.4, 2.0), (1.0, 0.97, 0.94)),
    )
    for name, (loc, energy, size, color) in zip(STAGING_LIGHTS, spots):
        light = bpy.data.objects.get(name)
        if light is None:
            continue
        _clear_cam_lock(light)
        light.parent = None
        light.location = loc
        data = getattr(light, "data", None)
        if data is not None:
            try:
                data.energy = energy
                data.size = size
                data.color = color
            except Exception:
                pass
        if look is not None:
            _track_to(light, look)


def capture_viewport_camera(context, cam: bpy.types.Object | None = None) -> bpy.types.Object:
    """Match Blender's Align Camera to View. Copying view_matrix alone frames too tight."""
    area, region, space = _view3d_parts(context)
    r3d = getattr(space, "region_3d", None) if space is not None else None
    if r3d is None or area is None or region is None:
        raise RuntimeError("No 3D Viewport. Frame the shot in the viewport first.")
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        cam = bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        cam = add_camera_rig(context, resolve_character(context), snap_view=False)
    _clear_cam_lock(cam)
    _clear_cam_lock(bpy.data.objects.get(STAGING_EMPTY))
    cam.parent = None
    cam.parent_type = "OBJECT"
    try:
        cam.parent_bone = ""
    except Exception:
        pass
    data = cam.data
    try:
        data.type = "PERSP"
        data.lens = float(space.lens)
        data.clip_start = float(space.clip_start)
        data.clip_end = float(space.clip_end)
        data.sensor_width = 36.0
        data.sensor_fit = "AUTO"
        data.shift_x = 0.0
        data.shift_y = 0.0
    except Exception:
        pass
    context.scene.camera = cam
    matched = False
    try:
        override = context.temp_override(window=context.window, area=area, region=region, space_data=space)
        with override:
            result = bpy.ops.view3d.camera_to_view()
        matched = "FINISHED" in set(result)
    except Exception:
        matched = False
    if not matched:
        quat = r3d.view_rotation.copy()
        cam.rotation_mode = "QUATERNION"
        cam.rotation_quaternion = quat
        cam.location = Vector(r3d.view_location) + quat @ Vector((0.0, 0.0, float(r3d.view_distance)))
    target = Vector(r3d.view_location)
    _soften_studio_lights(cam, target)
    try:
        context.scene.apex_cam_preset = "view"
    except Exception:
        pass
    context.scene.camera = cam
    context.view_layer.update()
    return cam


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


def add_camera_rig(context, obj: bpy.types.Object | None, snap_view: bool = True) -> bpy.types.Object:
    origin, height, radius = _character_metrics(obj)
    _remove_staging()
    coll = _ensure_collection(context)

    empty = bpy.data.objects.new(STAGING_EMPTY, None)
    empty.empty_display_type = "PLAIN_AXES"
    coll.objects.link(empty)
    _align_staging(empty, origin, *_character_facing(resolve_armature(obj) or obj))

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

    add_area(STAGING_LIGHTS[0], (-dist * 1.4, height * 1.3, dist * 0.9), 180.0, max(height * 1.6, 2.2))
    add_area(STAGING_LIGHTS[1], (0.0, height * 2.4, -dist * 0.4), 70.0, max(height * 2.2, 2.8))
    add_area(STAGING_LIGHTS[2], (dist * 1.3, height * 1.1, dist * 0.8), 55.0, max(height * 1.4, 1.8))
    preset = getattr(context.scene, "apex_cam_preset", "front") or "front"
    if preset == "pov":
        preset = "front"
    if snap_view:
        try:
            capture_viewport_camera(context, cam)
            apply_light_boost(context.scene)
            sync_closeup_dof(context)
            return cam
        except Exception:
            pass
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


def focus_object(context):
    """Viewport selection wins. The dropdown is only the fallback."""
    active = getattr(context, "active_object", None)
    if active is not None and getattr(active, "type", "") in {"MESH", "ARMATURE"}:
        if not (active.name or "").startswith("Apex "):
            return active
    selected = [
        obj for obj in list(getattr(context, "selected_objects", []) or [])
        if getattr(obj, "type", "") in {"MESH", "ARMATURE"} and not (obj.name or "").startswith("Apex ")
    ]
    if selected:
        return selected[0]
    scene = getattr(context, "scene", None)
    name = str(getattr(scene, "apex_cam_target", "") or "")
    if name and name != "ACTIVE":
        picked = bpy.data.objects.get(name)
        if picked is not None:
            return picked
    return resolve_character(context)


def _head_focus(obj):
    """Current posed head. Front / 3/4 / close-up all hang off this point."""
    up = _layout_up()
    forward = _layout_forward()
    if not _IN_LOCK:
        _refresh_pose()
    arm = None
    if obj is not None:
        arm = resolve_armature(obj) or (obj if getattr(obj, "type", "") == "ARMATURE" else None)
    head = _pose_bone(arm, HEAD_BONES) if arm is not None else None
    if head is None and arm is not None and getattr(arm, "pose", None) is not None:
        for bone in arm.pose.bones:
            name = (bone.name or "").lower()
            if "head" in name and "camera" not in name and not name.startswith("jx_"):
                head = bone
                break
    if head is not None and arm is not None:
        loc = arm.matrix_world @ Vector(head.head)
        basis = (arm.matrix_world @ head.matrix).to_3x3()
        best = None
        best_up = 2.0
        for axis in ((0.0, 0.0, 1.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)):
            raw = basis @ Vector(axis)
            if raw.length_squared < 1e-8:
                continue
            vertical = abs(raw.normalized().dot(up))
            flat = _flatten(raw, up)
            if flat.length_squared < 0.25:
                continue
            if vertical < best_up:
                best_up = vertical
                best = flat
        if best is not None:
            forward = best
        else:
            flat = _flatten(arm.matrix_world.to_3x3() @ Vector(LAYOUT_FORWARD), up)
            if flat.length_squared > 0.5:
                forward = flat
        hips = _pose_bone(arm, _FACE_BONES)
        if hips is not None:
            height = max((loc - (arm.matrix_world @ Vector(hips.head))).length * 1.45, 1.2)
        else:
            height = 1.7
        return loc, height, forward
    origin, height, _radius, center, forward = _visual_frame(obj)
    return origin + up * (height * 0.88) if height else center, max(height, 1.2), forward


_IN_LOCK = False


def _body_points(arm) -> list[Vector]:
    pts = []
    if arm is None or getattr(arm, "pose", None) is None:
        return pts
    mw = arm.matrix_world
    for bone in arm.pose.bones:
        name = (bone.name or "").lower()
        if name.startswith("jx_") or "camera" in name or "weapon" in name or "attach" in name:
            continue
        if not name.startswith("def_"):
            continue
        try:
            pts.append(mw @ bone.head)
        except Exception:
            pass
    return pts


def _look_matrix(eye: Vector, target: Vector) -> Matrix:
    direction = target - eye
    if direction.length_squared < 1e-12:
        direction = Vector((0.0, 0.0, -1.0))
    z_axis = -direction.normalized()
    world_up = _layout_up()
    x_axis = world_up.cross(z_axis)
    if x_axis.length_squared < 1e-12:
        x_axis = Vector((1.0, 0.0, 0.0))
    x_axis.normalize()
    y_axis = z_axis.cross(x_axis)
    mat = Matrix(
        (
            (x_axis.x, y_axis.x, z_axis.x, eye.x),
            (x_axis.y, y_axis.y, z_axis.y, eye.y),
            (x_axis.z, y_axis.z, z_axis.z, eye.z),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    return mat


def _unparent_keep_world(obj) -> None:
    if obj is None:
        return
    world = obj.matrix_world.copy()
    obj.parent = None
    try:
        obj.parent_type = "OBJECT"
        obj.parent_bone = ""
    except Exception:
        pass
    try:
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.delta_location = (0.0, 0.0, 0.0)
        obj.delta_rotation_euler = (0.0, 0.0, 0.0)
    except Exception:
        pass
    obj.matrix_world = world


def _visual_frame(obj):
    """Posed body bones first. Rest mesh boxes stay at the import spot."""
    up = _layout_up()
    forward = _layout_forward()
    fallback_origin = Vector((0.0, 0.0, 0.0))
    if obj is None:
        return fallback_origin, 1.8, 0.45, up * 0.9, forward
    if not _IN_LOCK:
        _refresh_pose()
    arm = resolve_armature(obj) or (obj if getattr(obj, "type", "") == "ARMATURE" else None)
    if arm is not None:
        flat = _flatten(arm.matrix_world.to_3x3() @ Vector(LAYOUT_FORWARD), up)
        if flat.length_squared > 0.5:
            forward = flat
    coords = _body_points(arm)
    if len(coords) < 6 and not _IN_LOCK:
        pool = []
        if getattr(obj, "type", "") == "MESH":
            pool.append(obj)
        root = arm or obj
        children = getattr(root, "children_recursive", None)
        kids = list(children) if children is not None else list(getattr(root, "children", []))
        for item in [root, *kids]:
            if getattr(item, "type", "") == "MESH" and item not in pool:
                pool.append(item)
        for item in pool:
            src = _evaluated_mesh(item)
            try:
                mat = src.matrix_world.copy()
                for corner in src.bound_box:
                    coords.append(mat @ Vector(corner))
            except Exception:
                coords.append(item.matrix_world.translation.copy())
    if not coords and arm is not None:
        coords.append(arm.matrix_world.translation.copy())
    if not coords:
        return fallback_origin, 1.8, 0.45, up * 0.9, forward
    along = [c.dot(up) for c in coords]
    low = min(along)
    height = max(max(along) - low, 0.4)
    center = Vector((0.0, 0.0, 0.0))
    for c in coords:
        center += c
    center /= len(coords)
    origin = center - up * center.dot(up) + up * low
    flat_pts = [c - up * c.dot(up) for c in coords]
    span = max(
        max(c.x for c in flat_pts) - min(c.x for c in flat_pts),
        max(c.z for c in flat_pts) - min(c.z for c in flat_pts),
        0.3,
    )
    return origin, height, span * 0.5, center, forward


def _place_camera_world(cam, eye: Vector, target: Vector) -> None:
    _clear_cam_lock(cam)
    _unparent_keep_world(cam)
    try:
        cam.delta_location = (0.0, 0.0, 0.0)
        cam.delta_rotation_euler = (0.0, 0.0, 0.0)
    except Exception:
        pass
    cam.matrix_world = _look_matrix(eye, target)



_LIGHT_ORIG = "apex_light_energy"
_DOF_FLAG = "apex_dof_prev"
_DOF_DIST = "apex_dof_dist_prev"
_DOF_FSTOP = "apex_dof_fstop_prev"


def apply_light_boost(scene) -> None:
    """Same scale as Optic Enhancer: energy = captured base * (1 + percent/100)."""
    if scene is None:
        return
    try:
        pct = float(getattr(scene, "apex_light_boost", 0.0) or 0.0)
    except (TypeError, ValueError):
        pct = 0.0
    mul = 1.0 + max(0.0, pct) / 100.0
    for name in STAGING_LIGHTS:
        obj = bpy.data.objects.get(name)
        if obj is None or getattr(obj, "type", "") != "LIGHT":
            continue
        data = getattr(obj, "data", None)
        if data is None:
            continue
        if obj.get(_LIGHT_ORIG) is None:
            try:
                obj[_LIGHT_ORIG] = float(getattr(data, "energy", 0.0))
            except Exception:
                continue
        try:
            data.energy = float(obj[_LIGHT_ORIG]) * mul
        except Exception:
            pass


def sync_closeup_dof(context) -> None:
    """Shallow DOF only on the close-up preset, and only when Close-up DOF is on."""
    scene = getattr(context, "scene", None)
    cam = bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        cam = getattr(scene, "camera", None) if scene is not None else None
    if scene is None or cam is None or getattr(cam, "type", "") != "CAMERA":
        return
    data = getattr(cam, "data", None)
    dof = getattr(data, "dof", None) if data is not None else None
    if dof is None or not hasattr(dof, "use_dof"):
        return
    preset = str(getattr(scene, "apex_cam_preset", "") or "")
    want = preset == "closeup" and bool(getattr(scene, "apex_closeup_dof", False))
    if want:
        if cam.get(_DOF_FLAG) is None:
            try:
                cam[_DOF_FLAG] = 1 if bool(dof.use_dof) else 0
            except Exception:
                cam[_DOF_FLAG] = 0
            try:
                cam[_DOF_DIST] = float(getattr(dof, "focus_distance", 0.35))
            except Exception:
                cam[_DOF_DIST] = 0.35
            try:
                cam[_DOF_FSTOP] = float(getattr(dof, "aperture_fstop", 2.8))
            except Exception:
                cam[_DOF_FSTOP] = 2.8
        try:
            dof.focus_object = None
        except Exception:
            pass
        dist = 0.35
        target = getattr(context, "active_object", None)
        if target is not None and target != cam:
            try:
                delta = cam.matrix_world.translation - target.matrix_world.translation
                dist = float(delta.length)
            except Exception:
                dist = 0.35
        try:
            dof.use_dof = True
            dof.focus_distance = max(0.05, dist)
        except Exception:
            pass
        if hasattr(dof, "aperture_fstop"):
            try:
                dof.aperture_fstop = 2.8
            except Exception:
                pass
        return
    if cam.get(_DOF_FLAG) is None:
        return
    try:
        dof.use_dof = bool(int(cam[_DOF_FLAG]))
    except Exception:
        pass
    if hasattr(dof, "focus_distance") and cam.get(_DOF_DIST) is not None:
        try:
            dof.focus_distance = float(cam[_DOF_DIST])
        except Exception:
            pass
    if hasattr(dof, "aperture_fstop") and cam.get(_DOF_FSTOP) is not None:
        try:
            dof.aperture_fstop = float(cam[_DOF_FSTOP])
        except Exception:
            pass
    for key in (_DOF_FLAG, _DOF_DIST, _DOF_FSTOP):
        if key in cam:
            try:
                del cam[key]
            except Exception:
                pass


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
    focus = focus_object(context)
    cam = ensure_camera_rig(context) if create else bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or cam.type != "CAMERA":
        return
    head, height, forward = _head_focus(focus)
    up = _layout_up()
    dist = max(height * 1.35, 1.8)
    right = up.cross(forward)
    if right.length_squared < 1e-8:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    if key == "closeup":
        look_at = head
        eye = head + forward * CLOSEUP_DIST + up * 0.04
        _place_camera_world(cam, eye, look_at)
        _set_closeup_lens(cam)
    elif key == "three_quarter":
        look_at = head - up * (height * 0.12)
        eye = head + forward * dist * 0.92 + right * dist * 0.48
        _place_camera_world(cam, eye, look_at)
        _set_studio_lens(cam)
    else:
        look_at = head - up * (height * 0.18)
        eye = head + forward * dist
        _place_camera_world(cam, eye, look_at)
        _set_studio_lens(cam)
    _set_passepartout(cam, 0.0)
    set_studio_lights_visible(True)
    apply_frame_orientation(getattr(context, "scene", None))
    context.view_layer.update()
    _soften_studio_lights(cam, look_at)
    context.scene.camera = cam
    if bool(getattr(context.scene, "apex_cam_lock", False)):
        look = bpy.data.objects.get(STAGING_TARGET)
        if look is not None:
            look.location = head
        _ensure_lock_track(cam)
    context.view_layer.update()
    apply_light_boost(getattr(context, "scene", None))
    sync_closeup_dof(context)


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
    _refresh_pose()
    try:
        cam.matrix_world.translation = _bone_world_loc(arm, cam_bone)
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


def _lock_target_object(scene):
    name = str(getattr(scene, "apex_cam_lock_name", "") or "")
    if name:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            return obj
    target = str(getattr(scene, "apex_cam_target", "") or "")
    if target and target != "ACTIVE":
        return bpy.data.objects.get(target)
    return None


def _ensure_lock_track(cam) -> None:
    look = bpy.data.objects.get(STAGING_TARGET)
    if cam is None or look is None:
        return
    if cam.parent is not None:
        _unparent_keep_world(cam)
    for con in list(cam.constraints):
        if con.name == CON_STUDIO_TRACK and con.type != "DAMPED_TRACK":
            cam.constraints.remove(con)
    for con in list(cam.constraints):
        if con.type == "DAMPED_TRACK" and con.name == CON_STUDIO_TRACK:
            con.target = look
            con.track_axis = "TRACK_NEGATIVE_Z"
            return
    con = cam.constraints.new("DAMPED_TRACK")
    con.name = CON_STUDIO_TRACK
    con.target = look
    con.track_axis = "TRACK_NEGATIVE_Z"


def set_camera_lock(context, enabled: bool, obj=None) -> None:
    scene = context.scene
    scene.apex_cam_lock = bool(enabled)
    cam = bpy.data.objects.get(STAGING_CAMERA)
    if cam is None or getattr(cam, "type", "") != "CAMERA":
        cam = ensure_camera_rig(context)
    if not enabled:
        scene.apex_cam_lock_name = ""
        if cam is not None:
            for con in list(cam.constraints):
                if con.name == CON_STUDIO_TRACK:
                    cam.constraints.remove(con)
        return
    if obj is None:
        obj = focus_object(context)
    if obj is None:
        scene.apex_cam_lock = False
        return
    scene.apex_cam_lock_name = obj.name
    aim_locked_camera(scene)
    if cam is not None:
        _ensure_lock_track(cam)


def aim_locked_camera(scene) -> None:
    global _IN_LOCK
    if _IN_LOCK or scene is None or not bool(getattr(scene, "apex_cam_lock", False)):
        return
    _IN_LOCK = True
    try:
        _aim_locked_camera(scene)
    finally:
        _IN_LOCK = False


def _aim_locked_camera(scene) -> None:
    if scene is None or not bool(getattr(scene, "apex_cam_lock", False)):
        return
    obj = _lock_target_object(scene)
    cam = bpy.data.objects.get(STAGING_CAMERA)
    look = bpy.data.objects.get(STAGING_TARGET)
    if obj is None or cam is None:
        return
    head, _height, _forward = _head_focus(obj)
    if look is None:
        look = bpy.data.objects.new(STAGING_TARGET, None)
        look.empty_display_type = "SPHERE"
        look.empty_display_size = 0.05
        try:
            scene.collection.objects.link(look)
        except Exception:
            pass
    look.parent = None
    look.location = head
    look.hide_viewport = True
    look.hide_render = True
    _ensure_lock_track(cam)


@persistent
def _lock_camera_handler(scene, *_args) -> None:
    try:
        if scene is not None and bool(getattr(scene, "apex_cam_lock", False)):
            aim_locked_camera(scene)
    except Exception:
        pass
