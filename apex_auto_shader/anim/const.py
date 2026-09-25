from __future__ import annotations

import math

# Apex/CAST is Y-up. Leave the armature at XYZ 0,0,0 and aim the camera instead.
MODEL_EULER_DEG = (0.0, 0.0, 0.0)
MODEL_EULER = tuple(math.radians(a) for a in MODEL_EULER_DEG)
LAYOUT_UP = (0.0, 1.0, 0.0)
LAYOUT_FORWARD = (0.0, 0.0, 1.0)

ANIM_SUFFIXES = {".cast"}
ANIM_LIST_CAP = 4000
ANIM_MIN_BYTES = 5 * 1024
CHAR_VICTIM = "apex_is_victim"
IMPORT_GAP = 1.5

STAGING_COLL = "Apex Camera"
STAGING_EMPTY = "Apex Staging"
STAGING_CAMERA = "Apex Camera"
STAGING_TARGET = "Apex Camera Target"
STAGING_LIGHTS = (
    "Apex Light Left",
    "Apex Light Overhead",
    "Apex Light Right",
)
STAGING_PIVOT = "Apex Closeup Pivot"
STAGING_OBJECTS = (STAGING_EMPTY, STAGING_CAMERA, STAGING_TARGET, STAGING_PIVOT) + STAGING_LIGHTS
BANNER_LIGHT_TAG = "apex_banner_light"
HOLOCARD_LIGHTS = (
    "Apex Holocard 0",
    "Apex Holocard 1",
    "Apex Holocard 2",
    "Apex Holocard 3",
)

START_BONE = "jx_c_start"
HEAD_BONES = ("def_c_forehead", "def_c_head", "def_c_neck")
CAM_BONES = ("jx_c_camera", "jx_c_cam")
POV_BONES = ("jx_c_pov", "jx_c_camera_pov")
CON_CAM_LOC = "ApexCamBone"
CON_CAM_TRACK = "ApexCamLook"
CON_STUDIO_TRACK = "ApexStudioLook"
CON_FOLLOW_LOC = "ApexFollowLoc"
CON_FOLLOW_ROT = "ApexFollowRot"
CON_CAM_NAMES = frozenset(
    {CON_CAM_LOC, CON_CAM_TRACK, CON_STUDIO_TRACK, CON_FOLLOW_LOC, CON_FOLLOW_ROT}
)
STUDIO_LENS = 50.0
CLOSEUP_LENS = 55.0
CLOSEUP_DIST = 0.62
POV_FOV_DEG = 50.0
POV_LENS = 35.0
PORTRAIT_RES_X = 1080
PORTRAIT_RES_Y = 1920
