from __future__ import annotations

from pathlib import Path

from . import config
from .blender_compat import find_socket, link, set_alpha_clip
from .log import existing_file, log
from .node_adder import NodeAdder, _link_named, _tex, fetchNodeGroupFromCacheOrFile


def _set_input_default(cas_node_group, names, value) -> None:
    sock = find_socket(cas_node_group, *names)
    if sock is None:
        return
    try:
        sock.default_value = value
    except Exception:
        pass


def _ensure_se_blend() -> None:
    raw = Path(config.PLUS_SE_APEX_SHADER_BLENDER_FILE)
    if existing_file(raw) is not None:
        return
    b64_path = raw.with_name(raw.name + ".b64")
    if not b64_path.is_file():
        return
    try:
        import base64

        raw.write_bytes(base64.b64decode("".join(b64_path.read_text(encoding="ascii").split())))
    except Exception as exc:
        log.warning("Could not decode %s: %s", b64_path.name, exc)


class PlusSENodeAdder(NodeAdder):
    """se_Apex Shader Plus — group name Apex Shader+ with remapped sockets."""

    @staticmethod
    def _addAlbedo(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        _link_named(mat, img_node, cas_node_group, ("Albedo",))

    @staticmethod
    def _addNormal(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Normal Map", "Normal"))

    @staticmethod
    def _addAO(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        if not _link_named(
            mat,
            img_node,
            cas_node_group,
            ("AO (Ambient Occlussion)", "AO", "Ambient Occlusion"),
        ):
            mat.node_tree.nodes.remove(img_node)

    @staticmethod
    def _addGlossy(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(mat, img_node, cas_node_group, ("Glossiness", "Glossy"))

    @staticmethod
    def _addEmissive(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        _link_named(mat, img_node, cas_node_group, ("Emission", "Emission Color"))
        _set_input_default(cas_node_group, ("Emission Strength",), 1.0)

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
        img_node = _tex(mat, img_path, location)
        for names in (
            ("Scatter Thickness (Radius)", "SSS (Subsurface Scattering)"),
            ("Subsurface Color",),
        ):
            sock = find_socket(cas_node_group, *names)
            if sock is not None:
                link(mat.node_tree, img_node.outputs["Color"], sock)
        sock = find_socket(cas_node_group, "Scatter Thickness Alpha", "SSS Alpha")
        if sock is not None:
            link(mat.node_tree, img_node.outputs["Alpha"], sock)
        _set_input_default(cas_node_group, ("Subsurface", "SSS Strength"), 0.2)

    @staticmethod
    def _addAnisoSpecDir(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        _link_named(
            mat,
            img_node,
            cas_node_group,
            ("Anis-Spec Dir", "Anis-SpecDir", "Anisotropic", "Anisotropy"),
        )

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
        _ensure_se_blend()
        return fetchNodeGroupFromCacheOrFile(
            "PlusSENodeAdder_cache",
            config.PLUS_SE_APEX_SHADER_BLENDER_FILE,
            "Apex Shader+",
        )
