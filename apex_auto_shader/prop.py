"""Attach a weapon CAST so its socket bone sits on the character bone ja_c_propGun."""

from __future__ import annotations

import re
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty

from .log import existing_dir, log

PROP_TAG = "apex_prop"
PROP_PATH = "apex_prop_path"
SOCKET_BONE = "ja_c_propGun"
_HIGHER_LOD = re.compile(r"_lod[1-9]\d*", re.IGNORECASE)
_PROP_CAP = 800


class _Bone:
    """Tiny stand-in so socket picking can be tested without a Blender rig."""

    def __init__(self, name: str, parent=None):
        self.name = name
        self.parent = parent


def _norm(name: str) -> str:
    return (name or "").lower().replace("_", "").replace(" ", "")


def pick_socket_bone(bones) -> str:
    """Character socket. Exact ja_c_propGun wins, then any propGun bone."""
    named = [getattr(bone, "name", "") for bone in bones if getattr(bone, "name", "")]
    by_norm = {_norm(name): name for name in named}
    exact = by_norm.get(_norm(SOCKET_BONE))
    if exact:
        return exact
    for name in named:
        if "propgun" in _norm(name):
            return name
    return ""


def pick_weapon_bone(bones) -> str:
    """Bone on the gun that should meet ja_c_propGun. Falls back to the root."""
    exact = pick_socket_bone(bones)
    if exact:
        return exact
    named = [bone for bone in bones if getattr(bone, "name", "")]
    for bone in named:
        low = bone.name.lower()
        if "gun" in low and any(word in low for word in ("attach", "grip", "root", "handle")):
            return bone.name
    roots = [bone for bone in named if getattr(bone, "parent", None) is None]
    if len(roots) == 1:
        return roots[0].name
    if roots:
        return min(roots, key=lambda bone: (len(bone.name), bone.name.lower())).name
    return named[0].name if named else ""


def is_prop_main_mesh(name: str) -> bool:
    """Weapon body and its own iron sight. Attachments (holo, laser, hcog) stay out."""
    return "base_main" in (name or "").lower()


def trim_prop_meshes(arm) -> list:
    """Hide every mesh that is not the weapon's base_main parts. Returns the ones to shade."""
    meshes = []
    for obj in list(getattr(arm, "children_recursive", []) or []):
        if getattr(obj, "type", "") == "MESH":
            meshes.append(obj)
    if not meshes and arm is not None:
        for obj in bpy.data.objects:
            if getattr(obj, "type", "") == "MESH" and getattr(obj, "parent", None) == arm:
                meshes.append(obj)
    main = [mesh for mesh in meshes if is_prop_main_mesh(mesh.name)]
    if not main:
        return meshes
    for mesh in meshes:
        if mesh in main:
            try:
                mesh.hide_set(False)
                mesh.hide_render = False
            except Exception:
                pass
            continue
        try:
            mesh.hide_set(True)
            mesh.hide_render = True
        except Exception:
            pass
    return main


_REF_TOKEN = re.compile(r"(?i)(?:^|_)ref_0(?=_|$)")
_HEIRLOOM_TOKEN = re.compile(r"(?i)(?:^|_)heirloom(?=_|$)")


def is_ref_prop(path: Path) -> bool:
    """Bind-pose casts are not listed. ref_0 never shows up in the name either."""
    return _REF_TOKEN.search(Path(path).stem) is not None


def prop_label(path: Path, kind: str = "") -> str:
    stem = _HIGHER_LOD.sub("", Path(path).stem)
    stem = re.sub(r"_lod0$", "", stem, flags=re.IGNORECASE)
    stem = _REF_TOKEN.sub("", stem)
    if (kind or "") == "heirloom":
        stem = _HEIRLOOM_TOKEN.sub("", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    text = stem.replace("_", " ").strip()
    return text or Path(path).stem


def _is_higher_lod(path: Path) -> bool:
    return _HIGHER_LOD.search(path.stem) is not None


_IMAGE_SUFFIXES = {".png", ".tga", ".jpg", ".jpeg", ".dds", ".tif", ".tiff", ".bmp"}
_SLOT_SUFFIX = {
    "col": "albedo",
    "color": "albedo",
    "colour": "albedo",
    "albedo": "albedo",
    "alb": "albedo",
    "nml": "normal",
    "nrm": "normal",
    "nrml": "normal",
    "normal": "normal",
    "gls": "gloss",
    "gloss": "gloss",
    "spc": "spec",
    "spec": "spec",
    "cav": "cavity",
    "cavity": "cavity",
    "ao": "ao",
    "ilm": "emissive",
    "emit": "emissive",
    "emissive": "emissive",
    "opa": "opacity",
    "opacity": "opacity",
    "sss": "scatter",
}


def prop_kind(path: Path) -> str:
    """Heirloom when the file or a nearby folder says so. Everything else is a gun."""
    blob = " ".join(part.lower() for part in Path(path).parts[-4:])
    if "heirloom" in blob:
        return "heirloom"
    return "gun"


def _images_in(folder: Path) -> list[Path]:
    found: list[Path] = []
    try:
        children = list(folder.iterdir())
    except OSError:
        return found
    for child in children:
        if child.is_file() and child.suffix.lower() in _IMAGE_SUFFIXES:
            found.append(child)
    return found


def _slot_of(name: str) -> str:
    tokens = Path(name).stem.split("_")
    if not tokens:
        return ""
    return _SLOT_SUFFIX.get(tokens[-1].lower(), "")


def _set_key(path: Path) -> str:
    tokens = path.stem.split("_")
    if tokens and _slot_of(path.name):
        tokens = tokens[:-1]
    return "_".join(tokens).lower()


def _cast_stem(name: str) -> str:
    stem = Path(str(name)).stem
    stem = re.sub(r"_lod\d+$", "", stem, flags=re.IGNORECASE)
    if stem.lower().endswith("_w"):
        stem = stem[:-2]
    return stem


def find_prop_texture_folder(cast_path: Path) -> Path | None:
    """Texture folder beside the CAST. A matching name wins, any image folder still counts."""
    path = Path(cast_path)
    parent = path.parent
    stem = _cast_stem(path.name)
    named = [parent / stem, parent / f"{stem}_w", parent / path.stem]
    if len(path.stem) > 5:
        named.insert(0, parent / path.stem[:-5])
    for cand in named:
        try:
            if cand.is_dir() and _images_in(cand):
                return cand
        except OSError:
            continue
    stem_tokens = {tok for tok in re.split(r"[_\s]+", stem.lower()) if tok}
    ranked: list[tuple[int, int, Path]] = []
    try:
        children = [child for child in parent.iterdir() if child.is_dir()]
    except OSError:
        children = []
    for cand in children:
        images = _images_in(cand)
        if not images:
            continue
        tokens = {tok for tok in re.split(r"[_\s]+", cand.name.lower()) if tok}
        ranked.append((len(stem_tokens & tokens), len(images), cand))
    if ranked:
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked[0][2]
    if _images_in(parent):
        return parent
    return None


def prop_texture_files(folder: Path, cast_name: str = "") -> list[Path]:
    """One texture set from the folder. Name overlap wins, otherwise the set with a color map."""
    groups: dict[str, list[Path]] = {}
    for path in _images_in(Path(folder)):
        if not _slot_of(path.name):
            continue
        groups.setdefault(_set_key(path), []).append(path)
    if not groups:
        return []
    stem_tokens = {tok for tok in re.split(r"[_\s]+", _cast_stem(cast_name).lower()) if tok}

    def score(key: str, files: list[Path]) -> tuple[int, int, int]:
        key_tokens = {tok for tok in key.split("_") if tok}
        overlap = len(stem_tokens & key_tokens)
        has_color = 1 if any(_slot_of(path.name) == "albedo" for path in files) else 0
        return (overlap, has_color, len(files))

    _key, files = max(groups.items(), key=lambda item: score(item[0], item[1]))
    return files


def prop_texture_match(folder: Path, cast_name: str = ""):
    """Textures for a prop, ignoring whether the file name matches the CAST."""
    from .naming.tex import MatchResult, TextureRef

    files = prop_texture_files(folder, cast_name)
    textures = []
    for path in files:
        slot = _slot_of(path.name)
        if not slot:
            continue
        textures.append(
            TextureRef(
                path=str(path),
                filename=path.name,
                prefix="prop",
                bodypart="prop",
                slot_raw=path.stem.split("_")[-1].lower(),
                slot=slot,
            )
        )
    if not textures:
        return None
    return MatchResult(source_name=Path(folder).name, prefix="prop", textures=textures)


def shade_prop_meshes(meshes, folder: Path, node_adder_cls, cast_name: str) -> int:
    """Put the prop's texture set on every visible mesh. Names do not have to match."""
    from .shade.utils import shade_material

    match = prop_texture_match(folder, cast_name)
    if match is None:
        return 0
    wired = 0
    for mesh in meshes:
        mats = [mat for mat in getattr(mesh.data, "materials", []) if mat is not None]
        if not mats:
            mat = bpy.data.materials.new(name=f"prop_{mesh.name}"[:60])
            mesh.data.materials.append(mat)
            mats = [mat]
        for mat in mats:
            wired += shade_material(mat, node_adder_cls, match.textures, bodypart="prop")
    return wired


def fill_prop_list(scene, folder) -> int:
    items = getattr(scene, "apex_prop_items", None)
    if items is None:
        return 0
    items.clear()
    root = existing_dir(folder) if folder else None
    if root is None:
        return 0
    found: list[Path] = []
    try:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() != ".cast":
                continue
            if _is_higher_lod(path) or is_ref_prop(path):
                continue
            found.append(path)
            if len(found) >= _PROP_CAP:
                break
    except Exception as exc:
        log.warning("Prop folder scan failed: %s", exc)
        return 0
    closed = {
        part
        for part in str(getattr(scene, "apex_prop_collapsed", "") or "").split("|")
        if part
    }
    groups: dict[str, list[Path]] = {}
    for path in sorted(found, key=lambda item: prop_label(item, prop_kind(item)).lower()):
        groups.setdefault(prop_kind(path), []).append(path)
    order = (("gun", "Guns"), ("heirloom", "Heirloom"))
    for key, label in order:
        paths = groups.get(key) or []
        if not paths:
            continue
        header = items.add()
        header.name = label
        header.path = ""
        header.kind = key
        header.is_header = True
        header.collapsed = key in closed
        for path in paths:
            item = items.add()
            item.name = prop_label(path, key)
            item.path = str(path)
            item.kind = key
            item.is_header = False
            item.collapsed = False
    if items:
        scene.apex_prop_index = min(int(getattr(scene, "apex_prop_index", 0) or 0), len(items) - 1)
    return len(items)


def _existing_prop(path: Path):
    needle = str(path)
    for obj in bpy.data.objects:
        if getattr(obj, "type", "") != "ARMATURE":
            continue
        if str(obj.get(PROP_PATH, "") or "") == needle:
            return obj
    return None


def _import_prop(context, path: Path):
    from .prefs import auto_shade, cast_importer_available, model_scale
    from .shade.utils import hide_rig

    if not cast_importer_available():
        raise RuntimeError("CAST importer not found. Install dtzxporter/cast, then restart Blender.")
    if not path.is_file():
        raise RuntimeError(f"CAST file not found: {path}")
    before = set(bpy.data.objects.keys())
    before_cols = set(bpy.data.collections.keys())
    bpy.ops.import_scene.cast("EXEC_DEFAULT", filepath=str(path))
    imported = [bpy.data.objects[name] for name in bpy.data.objects.keys() if name not in before]
    arm = next((obj for obj in imported if obj.type == "ARMATURE"), None)
    if arm is None:
        raise RuntimeError(f"No armature in {path.name}")
    arm[PROP_TAG] = 1
    arm[PROP_PATH] = str(path)
    scale = model_scale()
    arm.scale = (scale, scale, scale)
    try:
        arm.rotation_mode = "XYZ"
        arm.rotation_euler = (0.0, 0.0, 0.0)
    except Exception:
        pass
    for obj in imported:
        if obj != arm and obj.parent is None:
            try:
                obj.scale = (scale, scale, scale)
            except Exception:
                pass
    mains = trim_prop_meshes(arm)
    folder = find_prop_texture_folder(path)
    if folder is None:
        from .naming import find_texture_folder

        folder = find_texture_folder(path)
    if auto_shade() and folder is not None and mains:
        try:
            from .node_adder import current_node_adder

            wired = shade_prop_meshes(mains, folder, current_node_adder(context.scene), path.name)
            if not wired:
                from .shade.utils import shade_selected

                shade_selected(
                    mains,
                    current_node_adder(context.scene),
                    folder=folder,
                    finish=False,
                )
        except Exception as exc:
            log.warning("Prop shade skipped for %s: %s", path.name, exc)
    hide_rig(arm)
    from .anim.character import park_imported

    new_cols = [name for name in bpy.data.collections.keys() if name not in before_cols]
    park_imported(context, imported, "Props and Guns", new_cols)
    return arm


def _view3d(context):
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return None
    for window in getattr(wm, "windows", []) or []:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((reg for reg in area.regions if reg.type == "WINDOW"), None)
            if region is not None:
                return window, area, region
    return None


def _release_socket(character, bone_name: str, keep) -> None:
    for obj in list(bpy.data.objects):
        if obj == keep or getattr(obj, "type", "") != "ARMATURE":
            continue
        if obj.parent != character:
            continue
        if getattr(obj, "parent_type", "") == "BONE" and obj.parent_bone == bone_name:
            world = obj.matrix_world.copy()
            obj.parent = None
            try:
                obj.matrix_world = world
            except Exception:
                pass


def _align_bones(weapon, weapon_bone: str, character, char_bone: str) -> None:
    weapon.parent = None
    bpy.context.view_layer.update()
    src = weapon.matrix_world @ weapon.pose.bones[weapon_bone].matrix
    dst = character.matrix_world @ character.pose.bones[char_bone].matrix
    weapon.matrix_world = dst @ src.inverted() @ weapon.matrix_world
    bpy.context.view_layer.update()


def _parent_to_bone(context, weapon, character, bone_name: str) -> bool:
    found = _view3d(context)
    if found is None:
        return False
    window, area, region = found
    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_mode = character.mode
    selected = [obj for obj in view_layer.objects if obj.select_get()]
    world = weapon.matrix_world.copy()
    try:
        for obj in view_layer.objects:
            try:
                obj.select_set(False)
            except Exception:
                pass
        weapon.select_set(True)
        view_layer.objects.active = character
        character.data.bones.active = character.data.bones[bone_name]
        with context.temp_override(
            window=window,
            area=area,
            region=region,
            active_object=character,
            object=character,
            selected_objects=[weapon],
        ):
            if character.mode != "POSE":
                bpy.ops.object.mode_set(mode="POSE")
            character.data.bones[bone_name].select = True
            bpy.ops.object.parent_set(type="BONE", keep_transform=True)
            if prev_mode in {"OBJECT", "POSE"} and character.mode != prev_mode:
                bpy.ops.object.mode_set(mode=prev_mode)
        if weapon.parent == character and weapon.parent_bone == bone_name:
            return True
    except Exception as exc:
        log.warning("Bone parent failed, keeping the snap: %s", exc)
    finally:
        try:
            view_layer.objects.active = prev_active
        except Exception:
            pass
        for obj in view_layer.objects:
            try:
                obj.select_set(obj in selected)
            except Exception:
                pass
    try:
        weapon.parent = character
        weapon.parent_type = "BONE"
        weapon.parent_bone = bone_name
        bpy.context.view_layer.update()
        weapon.matrix_world = world
        return True
    except Exception:
        return False


def attach_prop(context, filepath: str):
    from .anim.character import resolve_character

    path = Path(bpy.path.abspath(filepath))
    character = resolve_character(context)
    if character is None:
        raise RuntimeError("Import a character first")
    socket = pick_socket_bone(character.data.bones)
    if not socket:
        raise RuntimeError(f"{character.name} has no {SOCKET_BONE} bone")
    weapon = _existing_prop(path)
    if weapon is None:
        weapon = _import_prop(context, path)
    else:
        trim_prop_meshes(weapon)
    gun_bone = pick_weapon_bone(weapon.data.bones)
    if not gun_bone:
        raise RuntimeError(f"{path.name} has no bones")
    _release_socket(character, socket, weapon)
    _align_bones(weapon, gun_bone, character, socket)
    _parent_to_bone(context, weapon, character, socket)
    try:
        from .shade.utils import hide_rig

        hide_rig(weapon)
    except Exception:
        pass
    matched = _norm(gun_bone) == _norm(socket) or "propgun" in _norm(gun_bone)
    return weapon, gun_bone, socket, matched


class APEX_PG_prop_item(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="")
    path: StringProperty(name="Path", default="")
    kind: StringProperty(name="Kind", default="")
    is_header: BoolProperty(name="Header", default=False)
    collapsed: BoolProperty(name="Collapsed", default=False)


class APEX_OT_toggle_prop_group(bpy.types.Operator):
    bl_idname = "apexaddon.toggle_prop_group"
    bl_label = "Toggle Prop Group"
    bl_description = "Collapse or expand Guns or Heirloom"
    bl_options = {"INTERNAL"}
    kind: StringProperty(default="")

    def execute(self, context):
        scene = context.scene
        kind = self.kind
        closed = {
            part
            for part in str(getattr(scene, "apex_prop_collapsed", "") or "").split("|")
            if part
        }
        if kind in closed:
            closed.discard(kind)
            collapsed = False
        else:
            closed.add(kind)
            collapsed = True
        scene.apex_prop_collapsed = "|".join(sorted(closed))
        for item in scene.apex_prop_items:
            if item.is_header and item.kind == kind:
                item.collapsed = collapsed
        return {"FINISHED"}


class APEX_UL_props(bpy.types.UIList):
    bl_idname = "APEX_UL_props"

    def draw_filter(self, context, layout):
        return

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if getattr(item, "is_header", False) or not item.path:
            tri = "TRIA_RIGHT" if item.collapsed else "TRIA_DOWN"
            op = layout.operator(
                APEX_OT_toggle_prop_group.bl_idname,
                text=item.name,
                icon=tri,
                emboss=False,
            )
            op.kind = item.kind
            return
        op = layout.operator(
            APEX_OT_attach_prop.bl_idname,
            text=prop_label(item.path, item.kind) if item.path else item.name,
            emboss=False,
            icon="OBJECT_DATAMODE",
        )
        op.filepath = item.path
        op.index = index

    def filter_items(self, context, data, propname):
        from .naming import anim_query_match

        items = getattr(data, propname)
        show = self.bitflag_filter_item
        scene = getattr(context, "scene", None)
        query = ""
        if scene is not None:
            query = (getattr(scene, "apex_prop_query", "") or "").strip()
        if not query:
            closed = {item.kind for item in items if item.is_header and item.collapsed}
            flags = []
            for item in items:
                if item.is_header or item.kind not in closed:
                    flags.append(show)
                else:
                    flags.append(0)
            return flags, []
        hits = []
        kinds = set()
        for item in items:
            if getattr(item, "is_header", False) or not item.path:
                hits.append(False)
                continue
            hit = anim_query_match(query, item.name, Path(item.path).stem, item.kind)
            hits.append(hit)
            if hit:
                kinds.add(item.kind)
        flags = []
        for item, hit in zip(items, hits):
            if getattr(item, "is_header", False) and item.kind in kinds:
                flags.append(show)
            elif hit:
                flags.append(show)
            else:
                flags.append(0)
        return flags, []


class APEX_OT_pick_prop_folder(bpy.types.Operator):
    bl_idname = "apexaddon.pick_prop_folder"
    bl_label = "Choose Prop Folder"
    bl_options = {"REGISTER"}
    directory: StringProperty(subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        folder = existing_dir(self.directory)
        if folder is None:
            self.report({"ERROR"}, "Folder not found")
            return {"CANCELLED"}
        context.scene.apex_prop_dir = str(folder)
        count = fill_prop_list(context.scene, folder)
        _FILLED[_scene_key(context.scene)] = str(folder)
        self.report({"INFO"}, f"{count} props")
        return {"FINISHED"}


class APEX_OT_attach_prop(bpy.types.Operator):
    bl_idname = "apexaddon.attach_prop"
    bl_label = "Attach Prop"
    bl_description = "Import this gun and place its socket bone on ja_c_propGun"
    bl_options = {"REGISTER", "UNDO"}
    filepath: StringProperty(subtype="FILE_PATH")
    index: IntProperty(default=-1, options={"HIDDEN"})

    def execute(self, context):
        if not self.filepath:
            items = getattr(context.scene, "apex_prop_items", None)
            idx = int(getattr(context.scene, "apex_prop_index", 0) or 0)
            if items and 0 <= idx < len(items):
                self.filepath = items[idx].path
        if not self.filepath:
            self.report({"ERROR"}, "Pick a gun first")
            return {"CANCELLED"}
        if self.index >= 0:
            try:
                context.scene.apex_prop_index = self.index
            except Exception:
                pass
        try:
            _weapon, gun_bone, socket, matched = attach_prop(context, self.filepath)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        label = prop_label(Path(self.filepath))
        if matched:
            self.report({"INFO"}, f"Attached {label} ({gun_bone} on {socket})")
        else:
            self.report(
                {"WARNING"},
                f"Attached {label} using {gun_bone}. The gun has no {SOCKET_BONE} bone.",
            )
        return {"FINISHED"}


prop_classes = (
    APEX_PG_prop_item,
    APEX_UL_props,
    APEX_OT_toggle_prop_group,
    APEX_OT_pick_prop_folder,
    APEX_OT_attach_prop,
)


_FILLED: dict[str, str] = {}


def _scene_key(scene) -> str:
    return str(getattr(scene, "name", "") or id(scene))


def prop_list_ready(scene, folder: str) -> bool:
    return bool(folder) and _FILLED.get(_scene_key(scene)) == str(folder)


def _update_prop_dir(self, _context):
    try:
        folder = str(getattr(self, "apex_prop_dir", "") or "")
        fill_prop_list(self, folder)
        _FILLED[_scene_key(self)] = folder
    except Exception:
        pass


_PROP_SYNC = False


def sync_prop_folders() -> None:
    """Use the preference only when the scene folder is still empty. Never lock it."""
    from .prefs import prop_folder_pref

    folder = prop_folder_pref()
    scenes = list(getattr(bpy.data, "scenes", []) or [])
    for scene in scenes:
        try:
            current = str(getattr(scene, "apex_prop_dir", "") or "")
            if not current and folder is not None:
                scene.apex_prop_dir = str(folder)
                continue
            if not current:
                _FILLED[_scene_key(scene)] = ""
                continue
            if not prop_list_ready(scene, current):
                fill_prop_list(scene, current)
                _FILLED[_scene_key(scene)] = current
        except Exception:
            continue


def queue_prop_sync() -> None:
    global _PROP_SYNC
    if _PROP_SYNC:
        return
    _PROP_SYNC = True

    def _go():
        global _PROP_SYNC
        _PROP_SYNC = False
        try:
            sync_prop_folders()
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_go, first_interval=0.2)
    except Exception:
        _PROP_SYNC = False


def register_scene_props() -> None:
    bpy.types.Scene.apex_prop_dir = StringProperty(
        name="Prop folder",
        description="Guns and heirlooms (.cast). Preference fills this when it is empty",
        subtype="DIR_PATH",
        default="",
        update=_update_prop_dir,
    )
    bpy.types.Scene.apex_prop_items = CollectionProperty(type=APEX_PG_prop_item)
    bpy.types.Scene.apex_prop_index = IntProperty(name="Prop", default=0)
    bpy.types.Scene.apex_prop_query = StringProperty(
        name="Search",
        description="Find a gun or heirloom. Reversed text matches too",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )
    bpy.types.Scene.apex_prop_collapsed = StringProperty(
        name="Collapsed prop groups",
        default="",
        options={"HIDDEN"},
    )
    queue_prop_sync()
