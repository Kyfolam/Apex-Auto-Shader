from __future__ import annotations

from pathlib import Path

import bpy

from . import config
from .log import existing_file, log
from .blender_compat import (
    find_socket,
    id_alive,
    link,
    new_tex_image,
    set_alpha_clip,
    socket,
)
from .naming import NONCOLOR_SLOTS, canonical_slot

# detail / transmittance maps are listed in SKIP_SLOTS: neither Cores nor Plus
# node groups expose matching sockets (inspected Apex Shader.blend / Apex_Shader_Plus1.blend).
#
# Emission is ilm-only. ehl must never fall back onto Emission / Emissive sockets
# (shade, import, skinfinder, recolor, upgrade all go through addImageTexture).
_EHL_SOCKETS = ("EHL", "Ehl")

shader_cache: dict = {}


def fetchNodeGroupFromCacheOrFile(name: str, blend_fpath, contain_name: str):
    path = existing_file(blend_fpath)
    if path is None:
        raise RuntimeError(
            f'Shader file missing: {blend_fpath}. Reinstall Apex Auto Shader.'
        )

    cached = shader_cache.get(name)
    if id_alive(cached):
        log.info("Using cached node group %s", name)
        return cached
    if name in shader_cache:
        log.info("Shader cache invalid, re-import %s", name)
        shader_cache.pop(name, None)

    log.info("Import node group from %s", path.name)
    with bpy.data.libraries.load(str(path)) as (data_from, data_to):
        data_to.node_groups = data_from.node_groups

    groups = [group for group in data_to.node_groups if group is not None]
    exact = next((group for group in groups if group.name == contain_name), None)
    if exact is not None:
        shader_cache[name] = exact
        return exact
    for group in groups:
        if contain_name in group.name:
            shader_cache[name] = group
            return group
    available = [group.name for group in groups]
    raise RuntimeError(
        f'No "{contain_name}" node tree in {path.name}. Found: {", ".join(available) or "(none)"}.'
    )


class NodeAdder:
    method: dict = {}

    @staticmethod
    def getShaderNodeGroup():
        raise NotImplementedError()

    @classmethod
    def addImageTexture(cls, img_path, mat, cas_node_group, location=(0.0, 0.0)):
        slot = canonical_slot(Path(img_path).stem[Path(img_path).stem.rindex("_") + 1 :])
        if slot == "ehl":
            return bool(cls._addEhl(img_path, mat, cas_node_group, location))
        if slot is None or slot not in cls.method:
            return False
        if slot == "emissive":
            cls.method["emissive"](img_path, mat, cas_node_group, location)
            return True
        cls.method[slot](img_path, mat, cas_node_group, location)
        return True

    @staticmethod
    def _addEhl(img_path, mat, cas_node_group, location):
        sock = find_socket(cas_node_group, *_EHL_SOCKETS)
        if sock is None:
            return False
        img_node = _tex(mat, img_path, location)
        return link(mat.node_tree, img_node.outputs["Color"], sock)


def _tex(mat, img_path, location, noncolor=False):
    # Non-Color: ao, cavity, gloss, normal, scatter, opacity, aniso.
    # sRGB: albedo, emissive, spec, ehl.
    slot = None
    stem = Path(img_path).stem
    if "_" in stem:
        slot = canonical_slot(stem[stem.rindex("_") + 1 :])
    if slot in NONCOLOR_SLOTS:
        noncolor = True
    elif slot in {"albedo", "emissive", "spec", "ehl"}:
        noncolor = False
    return new_tex_image(mat.node_tree.nodes, img_path, location, noncolor=noncolor)


def _link_named(mat, img_node, cas_node_group, names):
    sock = find_socket(cas_node_group, *names)
    if sock is None:
        return False
    return link(mat.node_tree, img_node.outputs["Color"], sock)


def _link_float(mat, img_node, cas_node_group, names):
    sock = find_socket(cas_node_group, *names)
    if sock is None:
        return False
    return link(mat.node_tree, img_node.outputs["Alpha"], sock)


class CoresNodeAdder(NodeAdder):
    @staticmethod
    def _addAlbedo(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Albedo"))

    @staticmethod
    def _addNormal(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Normal"))

    @staticmethod
    def _addAO(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "AO"))

    @staticmethod
    def _addGlossy(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Glossy"))

    @staticmethod
    def _addEmissive(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Emission"))
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Emission Color"))

    @staticmethod
    def _addCavity(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Cavity"))

    @staticmethod
    def _addSpec(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Specular"))

    @staticmethod
    def _addSubsurface(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Subsurface"))
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Subsurface Color"))

    @staticmethod
    def _addOpacityMultiply(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        nodes = mat.node_tree.nodes
        transparent_node = nodes.new(type="ShaderNodeBsdfTransparent")
        transparent_node.location = (200, 200)
        mix_shader_node = nodes.new(type="ShaderNodeMixShader")
        mix_shader_node.inputs[0].default_value = 1
        mix_shader_node.location = (400, 200)
        output_node = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
        link(mat.node_tree, img_node.outputs["Alpha"], mix_shader_node.inputs[0])
        link(mat.node_tree, transparent_node.outputs[0], mix_shader_node.inputs[1])
        link(mat.node_tree, cas_node_group.outputs[0], mix_shader_node.inputs[2])
        link(mat.node_tree, mix_shader_node.outputs[0], output_node.inputs["Surface"])
        set_alpha_clip(mat)

    @staticmethod
    def _addAniso(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(
            mat,
            img_node,
            cas_node_group,
            ("Anis-SpecDir", "Anis-Spec Dir", "Anisotropic", "Anisotropy"),
        )

    @staticmethod
    def _addEhl(img_path, mat, cas_node_group, location):
        return NodeAdder._addEhl(img_path, mat, cas_node_group, location)

    method = {
        "albedo": _addAlbedo,
        "ao": _addAO,
        "cavity": _addCavity,
        "emissive": _addEmissive,
        "gloss": _addGlossy,
        "normal": _addNormal,
        "spec": _addSpec,
        "opacity": _addOpacityMultiply,
        "scatter": _addSubsurface,
        "aniso": _addAniso,
        "ehl": _addEhl,
    }

    @staticmethod
    def getShaderNodeGroup():
        return fetchNodeGroupFromCacheOrFile(
            "CoresApexShader_cache",
            config.CORE_APEX_SHADER_BLENDER_FILE,
            "Cores Apex Shader",
        )


class PlusNodeAdder(NodeAdder):
    @staticmethod
    def _addAlbedo(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Albedo"))

    @staticmethod
    def _addNormal(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Normal Map"))

    @staticmethod
    def _addAO(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(
            mat.node_tree,
            img_node.outputs["Color"],
            socket(cas_node_group, "AO (Ambient Occlussion)"),
        )

    @staticmethod
    def _addGlossy(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Glossiness"))

    @staticmethod
    def _addEmissive(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Emission"))

    @staticmethod
    def _addCavity(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Cavity"))

    @staticmethod
    def _addSpec(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Specular"))

    @staticmethod
    def _addSubsurface(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(
            mat.node_tree,
            img_node.outputs["Color"],
            socket(cas_node_group, "SSS (Subsurface Scattering)"),
        )
        link(mat.node_tree, img_node.outputs["Alpha"], socket(cas_node_group, "SSS Alpha"))
        try:
            cas_node_group.inputs["SSS Strength"].default_value = 0.5
        except Exception:
            pass

    @staticmethod
    def _addAnisoSpecDir(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Anis-SpecDir"))

    @staticmethod
    def _addOpacityMultiply(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        sock = find_socket(
            cas_node_group,
            "Alpha (Opacity Multiply)",
            "Alpha//OpacityMult",
            "Opacity Multiply",
            "Alpha",
        )
        link(mat.node_tree, img_node.outputs["Alpha"], sock)
        set_alpha_clip(mat)

    @staticmethod
    def _addEhl(img_path, mat, cas_node_group, location):
        return NodeAdder._addEhl(img_path, mat, cas_node_group, location)

    method = {
        "albedo": _addAlbedo,
        "ao": _addAO,
        "cavity": _addCavity,
        "emissive": _addEmissive,
        "gloss": _addGlossy,
        "normal": _addNormal,
        "spec": _addSpec,
        "opacity": _addOpacityMultiply,
        "scatter": _addSubsurface,
        "aniso": _addAnisoSpecDir,
        "ehl": _addEhl,
    }

    @staticmethod
    def getShaderNodeGroup():
        return fetchNodeGroupFromCacheOrFile(
            "PlusNodeAdder_cache",
            config.PLUS_APEX_SHADER_BLENDER_FILE,
            "Apex Shader+",
        )


class ObjectNodeAdder(PlusNodeAdder):
    """Apex Shader+ wired with folder-local object/prop texture matching."""


class PlusSENodeAdder(NodeAdder):
    """se_Apex Shader Plus. Group name is exactly ``Apex Shader+ [APPEND]``."""

    @staticmethod
    def _addAlbedo(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        _link_named(mat, img_node, cas_node_group, ("Albedo",))

    @staticmethod
    def _addNormal(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Normal Map",))

    @staticmethod
    def _addAO(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Ambient Occlusion",))

    @staticmethod
    def _addGlossy(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Glossiness",))

    @staticmethod
    def _addEmissive(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        _link_named(mat, img_node, cas_node_group, ("Emission",))

    @staticmethod
    def _addCavity(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Cavity",))

    @staticmethod
    def _addSpec(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        _link_named(mat, img_node, cas_node_group, ("Specular",))

    @staticmethod
    def _addSubsurface(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Scatter Thickness (Radius)",))
        _link_float(mat, img_node, cas_node_group, ("Scatter Thickness Alpha",))
        # File default is 0, and the group does Subsurface * (1 - alpha).
        sock = find_socket(cas_node_group, "Subsurface")
        if sock is not None and not getattr(sock, "is_linked", False):
            try:
                sock.default_value = 1.0
            except Exception:
                pass

    @staticmethod
    def _addAnisoSpecDir(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Anis-Spec Dir",))

    @staticmethod
    def _addOpacityMultiply(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_float(mat, img_node, cas_node_group, ("Alpha (Opacity Multiply)",))
        set_alpha_clip(mat)

    @staticmethod
    def _addEhl(img_path, mat, cas_node_group, location):
        return False

    method = {
        "albedo": _addAlbedo,
        "ao": _addAO,
        "cavity": _addCavity,
        "emissive": _addEmissive,
        "gloss": _addGlossy,
        "normal": _addNormal,
        "spec": _addSpec,
        "opacity": _addOpacityMultiply,
        "scatter": _addSubsurface,
        "aniso": _addAnisoSpecDir,
        "ehl": _addEhl,
    }

    @staticmethod
    def getShaderNodeGroup():
        return fetchNodeGroupFromCacheOrFile(
            "PlusSENodeAdder_cache",
            config.PLUS_SE_APEX_SHADER_BLENDER_FILE,
            "Apex Shader+ [APPEND]",
        )


# Filled after CinematicNodeAdder is imported. Object stays Plus wiring
# with folder-local matching; it is not PlusNodeAdder itself.
SHADER_ADDERS = {
    "plus_se": PlusSENodeAdder,
    "cores": CoresNodeAdder,
    "plus": PlusNodeAdder,
    "object": ObjectNodeAdder,
}

# Registration default of Scene.apex_shader. Until the user picks a shader
# in the dropdown or the Choose Shader menu, the addon preference wins,
# even if the scene still holds the factory value or an older key.
_FACTORY_SHADER = "plus_se"
_syncing_shader = False


def shader_key_for(node_adder_cls) -> str:
    for key, cls in SHADER_ADDERS.items():
        if cls is node_adder_cls:
            return key
    return _FACTORY_SHADER


def _shader_keys() -> list[str]:
    from .prefs import SHADER_ITEMS

    return [item[0] for item in SHADER_ITEMS]


def _preferred_shader() -> str:
    from .prefs import default_shader

    key = default_shader()
    return key if key in SHADER_ADDERS else _FACTORY_SHADER


def shader_user_set(scene) -> bool:
    """True only after the dropdown or Choose Shader menu writes the value."""
    if scene is None:
        return False
    try:
        if bool(scene.get("apex_shader_user_set", False)):
            return True
    except Exception:
        pass
    return bool(getattr(scene, "apex_shader_user_set", False))


def _stored_shader_index(scene) -> int:
    keys = _shader_keys()
    try:
        raw = scene.get("apex_shader", 0)
    except Exception:
        raw = 0
    if isinstance(raw, str):
        return keys.index(raw) if raw in keys else 0
    try:
        idx = int(raw)
    except (TypeError, ValueError):
        return 0
    if idx < 0 or idx >= len(keys):
        return 0
    return idx


def apex_shader_get(self):
    """Unread scenes show the preference, not a stale scene enum."""
    keys = _shader_keys()
    if not shader_user_set(self):
        key = _preferred_shader()
        return keys.index(key) if key in keys else 0
    return _stored_shader_index(self)


def apex_shader_set(self, value):
    """UI and menu writes mark the scene as chosen. Preference sync does not."""
    keys = _shader_keys()
    if isinstance(value, str):
        idx = keys.index(value) if value in keys else 0
    else:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            idx = 0
        if idx < 0 or idx >= len(keys):
            idx = 0
    try:
        self["apex_shader"] = idx
    except Exception:
        return
    if _syncing_shader:
        return
    try:
        self["apex_shader_user_set"] = True
    except Exception:
        pass
    try:
        self.apex_shader_user_set = True
    except Exception:
        pass


def _assign_shader(scene, key: str) -> None:
    global _syncing_shader
    if scene is None or key not in SHADER_ADDERS:
        return
    keys = _shader_keys()
    try:
        raw = scene.get("apex_shader", None)
    except Exception:
        raw = None
    if isinstance(raw, str) and raw == key:
        return
    if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw < len(keys) and keys[raw] == key:
        return
    _syncing_shader = True
    try:
        scene.apex_shader = key
    except Exception:
        pass
    finally:
        _syncing_shader = False


def on_apex_shader_update(self, _context):
    """Dropdown / menu writes are explicit. Preference sync is not."""
    global _syncing_shader
    if _syncing_shader:
        return
    try:
        self["apex_shader_user_set"] = True
    except Exception:
        pass
    try:
        self.apex_shader_user_set = True
    except Exception:
        pass


def current_shader_key(scene=None) -> str:
    """Dropdown wins after the user picks one. Otherwise the preference."""
    scene = scene or getattr(bpy.context, "scene", None)
    pref = _preferred_shader()
    if scene is None:
        return pref
    if not shader_user_set(scene):
        _assign_shader(scene, pref)
        return pref
    keys = _shader_keys()
    idx = _stored_shader_index(scene)
    raw = keys[idx] if 0 <= idx < len(keys) else ""
    if raw not in SHADER_ADDERS:
        try:
            shown = str(getattr(scene, "apex_shader", "") or "")
        except Exception:
            shown = ""
        raw = shown
    return raw if raw in SHADER_ADDERS else pref


def sync_unset_scenes() -> None:
    """Push the preference into scenes the user has not picked a shader for."""
    pref = _preferred_shader()
    try:
        scenes = list(bpy.data.scenes)
    except Exception:
        scenes = []
    for scene in scenes:
        if shader_user_set(scene):
            continue
        _assign_shader(scene, pref)


def is_object_shader(scene=None, node_adder_cls=None) -> bool:
    if node_adder_cls is ObjectNodeAdder:
        return True
    return current_shader_key(scene) == "object"


def current_node_adder(scene=None):
    return SHADER_ADDERS.get(current_shader_key(scene), PlusSENodeAdder)

