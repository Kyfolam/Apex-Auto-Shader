from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from .. import config
from ..log import existing_dir
from ..blender_compat import material_meshes, resolve_armature
from ..naming import (
    is_model_cast,
    mesh_lod,
    strip_blender_suffix,
    suggest_prefixes_from_names,
)
from ..node_adder import current_node_adder, shader_cache

CHAR_TEX = "apex_texture_dir"
CHAR_CAST = "apex_cast_path"
CHAR_TAG = "apex_tag"
CHAR_COLL = "apex_cast_collection"
CHAR_RECOLOR = "apex_recolor"
CHAR_ANIM = "apex_anim_dir"
CHAR_LEGEND = "apex_legend"


def tag_character(arm, folder=None, cast_path=None, collection=None, anim_folder=None, recolor=None) -> None:
    if arm is None:
        return
    if folder is not None:
        arm[CHAR_TEX] = str(folder)
    if cast_path is not None:
        arm[CHAR_CAST] = str(cast_path)
        arm[CHAR_TAG] = strip_blender_suffix(Path(str(cast_path)).stem)
        from ..naming import guess_legend_from_path

        slug = guess_legend_from_path(cast_path)
        if slug:
            arm[CHAR_LEGEND] = slug
    elif CHAR_TAG not in arm:
        arm[CHAR_TAG] = strip_blender_suffix(arm.name)
    if collection is not None:
        arm[CHAR_COLL] = str(collection)
    if anim_folder is not None:
        arm[CHAR_ANIM] = str(anim_folder)
    if recolor:
        arm[CHAR_RECOLOR] = str(recolor)


def armature_legend(arm) -> str:
    if arm is None:
        return ""
    stored = str(arm.get(CHAR_LEGEND, "") or "")
    if stored:
        return stored.lower().replace(" ", "")
    from ..naming import guess_legend_from_anim, guess_legend_from_path

    for src in (arm.get(CHAR_CAST, ""), arm.get(CHAR_TAG, ""), arm.name):
        if not src:
            continue
        slug = guess_legend_from_path(src) or guess_legend_from_anim(str(src))
        if slug:
            return slug
    return ""


def tagged_armatures(scene=None, include_victims: bool = False) -> list:
    scene = scene or bpy.context.scene
    found = []
    for obj in scene.objects:
        if obj.type != "ARMATURE":
            continue
        if not include_victims and obj.get("apex_is_victim"):
            continue
        if CHAR_TAG in obj or CHAR_TEX in obj:
            found.append(obj)
    if found:
        return found
    return [
        obj
        for obj in scene.objects
        if obj.type == "ARMATURE" and (include_victims or not obj.get("apex_is_victim"))
    ]


def folder_for(obj, scene=None) -> Path | None:
    scene = scene or getattr(bpy.context, "scene", None)
    arm = resolve_armature(obj) if obj is not None else None
    if arm is not None:
        stored = arm.get(CHAR_TEX, "")
        if stored:
            path = existing_dir(stored)
            if path is not None:
                return path
    if scene is not None:
        explicit = getattr(scene, "apex_texture_dir", "") or ""
        if explicit:
            path = existing_dir(explicit)
            if path is not None:
                return path
    return None


def adder_for_bodypart(scene, bodypart: str | None):
    return current_node_adder(scene)


def lod_only_zero(scene=None) -> bool:
    from ..prefs import hide_higher_lods_pref

    return hide_higher_lods_pref()


def should_skip_lod(mesh) -> bool:
    if not lod_only_zero():
        return False
    return mesh_lod(mesh.name) > 0


def hide_higher_lods(root) -> int:
    from .utils import hide_object

    if not lod_only_zero() or root is None:
        return 0
    n = 0
    for mesh in material_meshes(root):
        if mesh_lod(mesh.name) > 0:
            hide_object(mesh)
            n += 1
    return n


def prefix_conflict_message(folder: Path, prefix: str) -> str:
    from ..naming import iter_texture_files

    names = [p.name for p in iter_texture_files(folder)]
    found = suggest_prefixes_from_names(names)
    msg = f"No PNGs matching prefix '{prefix}' in {folder}"
    if found:
        msg += f". Folder looks like: {', '.join(found[:4])}"
    else:
        msg += ". No recognizable texture names in that folder"
    return msg


def store_status(scene, reports, folder=None) -> str:
    from ..constants import SLOT_SHORT

    ok = sum(1 for r in reports if r.get("wired"))
    total = sum(1 for r in reports if not r.get("hidden"))
    hidden = sum(1 for r in reports if r.get("hidden"))
    fail = sum(1 for r in reports if r.get("error"))
    parts = [f"Shaded {ok}/{total} meshes"]
    if hidden:
        parts.append(f"{hidden} hidden")
    if fail:
        parts.append(f"{fail} skipped")
    missing_bits = []
    fail_bits = []
    for r in reports or []:
        bp = r.get("bodypart") or r.get("mesh") or "?"
        miss = r.get("missing") or []
        if miss:
            shorts = [SLOT_SHORT.get(s, s) for s in miss]
            missing_bits.append(f"{bp} {', '.join(shorts)}")
        err = r.get("error")
        if err:
            fail_bits.append(f"{r.get('mesh', '?')}: {err}")
    if missing_bits:
        parts.append("Missing: " + "; ".join(missing_bits[:8]))
    if fail_bits:
        parts.append("Failed: " + "; ".join(fail_bits[:4]))
    msg = " · ".join(parts)
    if scene is not None:
        try:
            scene.apex_last_status = msg
        except Exception:
            try:
                scene["apex_last_status"] = msg
            except Exception:
                pass
    return msg


def action_frame_range(action) -> tuple[int, int] | None:
    if action is None:
        return None
    fr = getattr(action, "frame_range", None)
    if fr is not None:
        try:
            start, end = int(fr[0]), int(fr[1])
            if end > start:
                return start, end
        except Exception:
            pass
    frames = []
    from ..anim import _action_fcurves

    for curve in _action_fcurves(action):
        for kp in getattr(curve, "keyframe_points", []):
            frames.append(kp.co[0])
    if not frames:
        return None
    start, end = int(min(frames)), int(max(frames))
    if end <= start:
        return None
    return start, end


def sync_frame_range(context, arm) -> tuple[int, int] | None:
    ad = getattr(arm, "animation_data", None)
    action = ad.action if ad is not None else None
    rng = action_frame_range(action)
    if rng is None:
        return None
    context.scene.frame_start = rng[0]
    context.scene.frame_end = rng[1]
    context.scene.frame_set(rng[0])
    return rng


def apply_eevee_ready(scene) -> None:
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.film_transparent = False
    eevee = getattr(scene, "eevee", None)
    if eevee is None:
        return
    for attr, value in (
        ("use_shadows", True),
        ("use_raytracing", True),
        ("use_gtao", True),
        ("gtao_distance", 0.2),
        ("use_bloom", False),
        ("taa_samples", 16),
        ("taa_render_samples", 64),
        ("use_volumetric_shadows", True),
        ("shadow_ray_count", 4),
        ("shadow_step_count", 8),
    ):
        if hasattr(eevee, attr):
            try:
                setattr(eevee, attr, value)
            except Exception:
                pass
    view = getattr(scene, "view_settings", None)
    if view is not None and hasattr(view, "view_transform"):
        for name in ("AgX", "Filmic", "Standard"):
            try:
                view.view_transform = name
                break
            except Exception:
                continue


def purge_orphans() -> int:
    removed = 0
    pools = [
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.armatures,
        bpy.data.actions,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.collections,
    ]
    for _ in range(4):
        batch = 0
        for coll in pools:
            for block in list(coll):
                try:
                    if getattr(block, "users", 1) == 0:
                        coll.remove(block)
                        batch += 1
                except Exception:
                    pass
        removed += batch
        if batch == 0:
            break
    shader_cache.clear()
    try:
        bpy.ops.outliner.orphans_purge(
            do_local_ids=True, do_linked_ids=True, do_recursive=True
        )
    except Exception:
        pass
    return removed


def check_for_updates() -> str:
    local = config.ADDON_VERSION_STR
    local_t = _parse_semver(local)
    data, code = _github_get(config.UPDATE_API)
    tag = ""
    if code == 404 or (isinstance(data, dict) and data.get("message") == "Not Found"):
        tags, tcode = _github_get(config.UPDATE_TAGS)
        if tcode == 404 or tags is None:
            return (
                f"v{local} · GitHub repo not public yet. "
                "Publish https://github.com/Kyfolam/Apex-Auto-Shader and create a Release tagged v"
                f"{local}"
            )
        if isinstance(tags, list) and tags:
            tag = str(tags[0].get("name") or "")
        else:
            return f"v{local} · no GitHub release yet. Create a Release tagged v{local}"
    elif data is None:
        return f"v{local} · update check failed"
    else:
        tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        return f"v{local} · no GitHub release yet. Create a Release tagged v{local}"
    remote = _parse_semver(tag)
    if remote is None:
        return f"v{local} · GitHub {tag}"
    if remote > local_t:
        return f"Update available: {tag} (you have v{local})"
    if remote == local_t:
        return f"Up to date (v{local})"
    return f"v{local} · newer than GitHub {tag}"


def _parse_semver(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if match:
        return tuple(int(x) for x in match.groups())
    match = re.search(r"(\d+)\.(\d+)", text or "")
    if match:
        return (int(match.group(1)), int(match.group(2)), 0)
    return (0, 0, 0)


def _github_get(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"ApexAutoShader/{config.ADDON_VERSION_STR}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8")), getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        return None, int(getattr(exc, "code", 0) or 0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None, 0


def list_model_casts(folder: str | Path) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        return []
    files = [p for p in sorted(root.rglob("*.cast")) if p.is_file()]
    models = [p for p in files if is_model_cast(p.name)]
    return models or files


@persistent
def apex_on_frame(scene, depsgraph=None):
    end = int(getattr(scene, "frame_end", 0) or 0)
    current = int(getattr(scene, "frame_current", 0) or 0)
    if end <= 0 or current < end:
        return
    if bool(getattr(scene, "apex_anim_loop", True)):
        return

    def _stop():
        try:
            if bpy.context.screen.is_animation_playing:
                bpy.ops.screen.animation_cancel(restore_frame=False)
            from ..anim import restore_showcase_resolution, restore_studio_camera

            restore_studio_camera(bpy.context)
            restore_showcase_resolution(bpy.context.scene)
        except Exception:
            pass
        return None

    bpy.app.timers.register(_stop, first_interval=0.02)


def register_handlers():
    handlers = bpy.app.handlers.frame_change_post
    # Drop every previous banner-cam sync. Rewriting rotation each frame spins it.
    for fn in list(handlers):
        if getattr(fn, "__name__", "") == "sync_banner_camera":
            handlers.remove(fn)
    if apex_on_frame not in handlers:
        handlers.append(apex_on_frame)


def unregister_handlers():
    handlers = bpy.app.handlers.frame_change_post
    for fn in list(handlers):
        if getattr(fn, "__name__", "") in {"apex_on_frame", "sync_banner_camera"}:
            handlers.remove(fn)
