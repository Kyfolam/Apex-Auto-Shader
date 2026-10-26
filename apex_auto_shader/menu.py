from __future__ import annotations

import bpy

from .anim import anim_classes, register_camera_keys, unregister_camera_keys
from .anim.studio import _lock_camera_handler, apex_cam_lock_load_post, sync_cam_lock_handlers
from .extras import register_handlers, unregister_handlers
from .menu_apex import apex_classes, apex_menu_func
from .panel import panel_classes, register_props, unregister_props
from .prefs import APEX_OT_uninstall, ApexAutoShaderPreferences, notify_missing_cast
from .install import APEX_OT_drop_old_copy, APEX_OT_install_zip, schedule_existing_check

classes = (
    ApexAutoShaderPreferences,
    APEX_OT_uninstall,
    APEX_OT_install_zip,
    APEX_OT_drop_old_copy,
    *anim_classes,
    *apex_classes,
    *panel_classes,
)

menu_funcs = (
    apex_menu_func,
)


def register():
    for c in classes:
        if c is not None:
            bpy.utils.register_class(c)
    register_props()
    register_handlers()
    for menu_func in menu_funcs:
        bpy.types.VIEW3D_MT_object_context_menu.append(menu_func)
        bpy.types.VIEW3D_MT_pose_context_menu.append(menu_func)
    try:
        bpy.app.timers.register(notify_missing_cast, first_interval=0.4)
    except Exception:
        notify_missing_cast()
    schedule_existing_check()
    register_camera_keys()
    # Lock-camera handler only while Lock camera is on (not every depsgraph update).
    if apex_cam_lock_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(apex_cam_lock_load_post)
    sync_cam_lock_handlers()
    try:
        bpy.app.timers.register(lambda: sync_cam_lock_handlers(), first_interval=0.8)
    except Exception:
        pass


def unregister():
    unregister_camera_keys()
    for bucket in (bpy.app.handlers.frame_change_post, bpy.app.handlers.depsgraph_update_post):
        if _lock_camera_handler in bucket:
            bucket.remove(_lock_camera_handler)
    if apex_cam_lock_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(apex_cam_lock_load_post)
    unregister_handlers()
    for menu_func in menu_funcs:
        bpy.types.VIEW3D_MT_object_context_menu.remove(menu_func)
        bpy.types.VIEW3D_MT_pose_context_menu.remove(menu_func)
    unregister_props()
    for c in reversed(classes):
        if c is not None:
            bpy.utils.unregister_class(c)