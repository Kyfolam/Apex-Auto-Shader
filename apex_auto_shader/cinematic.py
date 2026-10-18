"""Cinematic Shader: illustrated hard light, ink edge, cool rim.

A new ShaderNodeTree named "Cinematic Shader". Not a copy of Apex Shader+
and not a Principled rebuild. Gloss is a narrow graphic band only.
"""
from __future__ import annotations

import bpy

from .blender_compat import find_socket, id_alive, link, set_alpha_clip, socket
from .node_adder import NodeAdder, _tex, shader_cache

GROUP_NAME = "Cinematic Shader"
CACHE_KEY = "CinematicShader_cache"

# Cool dark blue-purple shadow, light cyan rim. Unlinked defaults only.
_SHADOW = (0.16, 0.11, 0.30, 1.0)
_RIM = (0.62, 0.90, 1.0, 1.0)
_ALBEDO = (0.8, 0.8, 0.8, 1.0)
_NORMAL = (0.5, 0.5, 1.0, 1.0)
# Y-up mesh, face toward +Z. Vector points from the surface toward the key.
_KEY = (0.22, 0.78, 0.72)

_REQUIRED = (
    "Albedo",
    "Normal Map",
    "Shadow Color",
    "Shadow Threshold",
    "Outline Strength",
    "Rim Color",
    "Rim Strength",
)


def _engine_name() -> str:
    scene = getattr(bpy.context, "scene", None)
    render = getattr(scene, "render", None) if scene is not None else None
    return str(getattr(render, "engine", "") or "BLENDER_EEVEE")


def _cycles_engine(name: str | None = None) -> bool:
    return "CYCLE" in (name if name is not None else _engine_name()).upper()


def _iface_inputs(tree) -> list[str]:
    iface = getattr(tree, "interface", None)
    if iface is None:
        return []
    names = []
    for item in list(getattr(iface, "items_tree", []) or []):
        if getattr(item, "in_out", "") == "INPUT" and getattr(item, "name", ""):
            names.append(item.name)
    return names


def _clear_interface(tree) -> None:
    iface = getattr(tree, "interface", None)
    if iface is None:
        return
    for item in list(getattr(iface, "items_tree", []) or []):
        try:
            iface.remove(item)
        except Exception:
            pass


def _add_socket(tree, name, socket_type, default=None, min_v=None, max_v=None, output=False):
    iface = tree.interface
    sock = iface.new_socket(
        name=name,
        in_out="OUTPUT" if output else "INPUT",
        socket_type=socket_type,
    )
    if default is not None:
        try:
            sock.default_value = default
        except Exception:
            pass
    if min_v is not None:
        try:
            sock.min_value = min_v
        except Exception:
            pass
    if max_v is not None:
        try:
            sock.max_value = max_v
        except Exception:
            pass
    return sock


def _n(tree, bl_id, name, loc):
    node = tree.nodes.new(bl_id)
    node.name = name
    node.label = name
    node.location = loc
    return node


def _inp(node, *names, index=None):
    # Index wins. Math sockets are both named "Value", so a name lookup
    # would always return the first one.
    if index is not None:
        try:
            return node.inputs[index]
        except (KeyError, TypeError, IndexError):
            pass
    for name in names:
        try:
            sock = node.inputs[name]
        except (KeyError, TypeError, IndexError):
            sock = None
        if sock is not None:
            return sock
    return None


def _out(node, *names, index=0):
    for name in names:
        try:
            sock = node.outputs[name]
        except (KeyError, TypeError, IndexError):
            sock = None
        if sock is not None:
            return sock
    try:
        return node.outputs[index]
    except (KeyError, TypeError, IndexError):
        return None


def _link(tree, a, b):
    if a is None or b is None:
        return False
    try:
        tree.links.new(a, b)
        return True
    except Exception:
        return False


def _math(tree, op, name, loc):
    node = _n(tree, "ShaderNodeMath", name, loc)
    try:
        node.operation = op
    except Exception:
        pass
    return node


def _vec(tree, op, name, loc):
    node = _n(tree, "ShaderNodeVectorMath", name, loc)
    try:
        node.operation = op
    except Exception:
        pass
    return node


def _mix_color(tree, name, loc, blend="MIX"):
    node = _n(tree, "ShaderNodeMix", name, loc)
    try:
        node.data_type = "RGBA"
    except Exception:
        pass
    try:
        node.blend_type = blend
    except Exception:
        pass
    return node


def _luma(tree, color_sock, name, loc):
    sep = _n(tree, "ShaderNodeSeparateColor", name + "Sep", loc)
    add1 = _math(tree, "ADD", name + "Add1", (loc[0] + 160, loc[1]))
    add2 = _math(tree, "ADD", name + "Add2", (loc[0] + 320, loc[1]))
    scale = _math(tree, "MULTIPLY", name + "Luma", (loc[0] + 480, loc[1]))
    try:
        _inp(scale, "Value", index=1).default_value = 0.333333
    except Exception:
        pass
    _link(tree, color_sock, _inp(sep, "Color", index=0))
    _link(tree, _out(sep, "Red", index=0), _inp(add1, "Value", index=0))
    _link(tree, _out(sep, "Green", index=1), _inp(add1, "Value", index=1))
    _link(tree, _out(add1, "Value", index=0), _inp(add2, "Value", index=0))
    _link(tree, _out(sep, "Blue", index=2), _inp(add2, "Value", index=1))
    _link(tree, _out(add2, "Value", index=0), _inp(scale, "Value", index=0))
    return _out(scale, "Value", index=0)


def _hard_mask(tree, value_sock, threshold_sock, name, loc, as_color=True):
    """Greater-than against Shadow Threshold, then a constant ramp.

    The ramp sits after the compare so a fixed stop cannot force the whole
    surface into the lit band before the threshold is applied.
    """
    if as_color:
        luma = _luma(tree, value_sock, name + "Src", loc)
    else:
        luma = value_sock
    gt = _math(tree, "GREATER_THAN", name + "Cmp", (loc[0] + 560, loc[1]))
    try:
        gt.operation = "GREATER_THAN"
    except Exception:
        pass
    _link(tree, luma, _inp(gt, index=0))
    _link(tree, threshold_sock, _inp(gt, index=1))
    ramp = _n(tree, "ShaderNodeValToRGB", name + "Ramp", (loc[0] + 760, loc[1]))
    try:
        ramp.color_ramp.interpolation = "CONSTANT"
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        ramp.color_ramp.elements[1].position = 0.5
        ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    except Exception:
        pass
    _link(tree, _out(gt, "Value", index=0), _inp(ramp, index=0))
    band = _luma(tree, _out(ramp, "Color", index=0), name + "Band", (loc[0] + 980, loc[1]))
    # Named node sync_engine links into the shadow mix.
    final = _math(tree, "MULTIPLY", name, (loc[0] + 1500, loc[1]))
    try:
        _inp(final, index=1).default_value = 1.0
    except Exception:
        pass
    _link(tree, band, _inp(final, index=0))
    return _out(final, "Value", index=0), final


def _rebuild(tree) -> None:
    tree.nodes.clear()
    _clear_interface(tree)
    _add_socket(tree, "Albedo", "NodeSocketColor", _ALBEDO)
    _add_socket(tree, "Normal Map", "NodeSocketColor", _NORMAL)
    _add_socket(tree, "Shadow Color", "NodeSocketColor", _SHADOW)
    _add_socket(tree, "Shadow Threshold", "NodeSocketFloat", 0.45, 0.0, 1.0)
    _add_socket(tree, "Outline Strength", "NodeSocketFloat", 0.6, 0.0, 1.0)
    _add_socket(tree, "Rim Color", "NodeSocketColor", _RIM)
    _add_socket(tree, "Rim Strength", "NodeSocketFloat", 0.35, 0.0, 1.0)
    # Optional. Gloss is not roughness. Spec stays a weak tint. Alpha for hair cards.
    _add_socket(tree, "Glossiness", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0))
    _add_socket(tree, "Specular", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0))
    _add_socket(tree, "Alpha", "NodeSocketFloat", 1.0, 0.0, 1.0)
    _add_socket(tree, "Shader", "NodeSocketShader", output=True)

    gin = _n(tree, "NodeGroupInput", "Group Input", (-1400, 0))
    gout = _n(tree, "NodeGroupOutput", "Group Output", (2200, 0))

    def gin_out(name):
        return _out(gin, name)

    nmap = _n(tree, "ShaderNodeNormalMap", "CIN_NormalMap", (-1100, -280))
    try:
        _inp(nmap, "Strength", index=0).default_value = 1.0
    except Exception:
        pass
    _link(tree, gin_out("Normal Map"), _inp(nmap, "Color", index=1))

    # Cycles-safe hard split: normal · key light, no Shader to RGB.
    dot = _vec(tree, "DOT_PRODUCT", "CIN_KeyDot", (-820, -480))
    try:
        _inp(dot, "Vector", index=1).default_value = _KEY
    except Exception:
        pass
    _link(tree, _out(nmap, "Normal", index=0), _inp(dot, "Vector", index=0))
    span = _n(tree, "ShaderNodeMapRange", "CIN_KeySpan", (-620, -480))
    try:
        _inp(span, "From Min", index=1).default_value = -1.0
        _inp(span, "From Max", index=2).default_value = 1.0
        _inp(span, "To Min", index=3).default_value = 0.0
        _inp(span, "To Max", index=4).default_value = 1.0
    except Exception:
        pass
    _link(tree, _out(dot, "Value", index=1), _inp(span, "Value", index=0))
    _hard_mask(
        tree,
        _out(span, "Result", index=0),
        gin_out("Shadow Threshold"),
        "CIN_CyclesMask",
        (-360, -480),
        as_color=False,
    )

    # Eevee light split. Left unplugged from the output when the engine is Cycles.
    diffuse = _n(tree, "ShaderNodeBsdfDiffuse", "CIN_Diffuse", (-1100, 280))
    try:
        _inp(diffuse, "Color", index=0).default_value = (1.0, 1.0, 1.0, 1.0)
        rough = _inp(diffuse, "Roughness", index=1)
        if rough is not None:
            rough.default_value = 1.0
    except Exception:
        pass
    _link(tree, _out(nmap, "Normal", index=0), _inp(diffuse, "Normal", index=2))
    s2rgb = None
    try:
        s2rgb = _n(tree, "ShaderNodeShaderToRGB", "CIN_ShaderToRGB", (-860, 280))
    except Exception:
        s2rgb = None
    if s2rgb is not None:
        _link(tree, _out(diffuse, "BSDF", index=0), _inp(s2rgb, "Shader", "Color", index=0))
        _hard_mask(
            tree,
            _out(s2rgb, "Color", index=0),
            gin_out("Shadow Threshold"),
            "CIN_EeveeMask",
            (-560, 280),
        )

    shadow_mix = _mix_color(tree, "CIN_ShadowMix", (520, 80))
    # Shadow fill stays the albedo hue. A neutral step only.
    # Multiplying by Shadow Color (blue-purple) is what greyed the face.
    mul = _mix_color(tree, "CIN_ShadowMul", (300, -40), blend="MULTIPLY")
    try:
        fac = _inp(mul, "Factor_Float", "Factor", index=0)
        if fac is not None and not fac.is_linked:
            fac.default_value = 1.0
        _inp(mul, "B_Color", "B", index=7).default_value = (0.88, 0.88, 0.88, 1.0)
    except Exception:
        pass
    _link(tree, gin_out("Albedo"), _inp(mul, "A_Color", "A", index=6))
    # Factor 0 = shadow, factor 1 = flat albedo. Mask is 1 in the light.
    _link(tree, _out(mul, "Result_Color", "Result", index=2), _inp(shadow_mix, "A_Color", "A", index=6))
    _link(tree, gin_out("Albedo"), _inp(shadow_mix, "B_Color", "B", index=7))

    # Cool color is its own graphic shape on top (mix, not multiply).
    # Factor is (1 - light) * 0.22, linked in _sync_engine. Skin still reads as albedo.
    inv = _math(tree, "SUBTRACT", "CIN_ShadowInv", (300, 280))
    try:
        _inp(inv, index=0).default_value = 1.0
    except Exception:
        pass
    cool_fac = _math(tree, "MULTIPLY", "CIN_CoolFac", (520, 280))
    try:
        _inp(cool_fac, index=1).default_value = 0.22
    except Exception:
        pass
    _link(tree, _out(inv, "Value", index=0), _inp(cool_fac, index=0))
    cool = _mix_color(tree, "CIN_CoolShape", (760, 80), blend="MIX")
    _link(tree, _out(cool_fac, "Value", index=0), _inp(cool, "Factor_Float", "Factor", index=0))
    _link(tree, _out(shadow_mix, "Result_Color", "Result", index=2), _inp(cool, "A_Color", "A", index=6))
    _link(tree, gin_out("Shadow Color"), _inp(cool, "B_Color", "B", index=7))

    # Narrow gloss band. Not a roughness / PBR lobe.
    layer = _n(tree, "ShaderNodeLayerWeight", "CIN_Layer", (520, -360))
    try:
        _inp(layer, "Blend", index=0).default_value = 0.35
    except Exception:
        pass
    center = _math(tree, "SUBTRACT", "CIN_BandCenter", (760, -420))
    try:
        _inp(center, "Value", index=1).default_value = 0.22
    except Exception:
        pass
    _link(tree, _out(layer, "Facing", index=0), _inp(center, "Value", index=0))
    absolute = _math(tree, "ABSOLUTE", "CIN_BandAbs", (940, -420))
    _link(tree, _out(center, "Value", index=0), _inp(absolute, "Value", index=0))
    width = _math(tree, "DIVIDE", "CIN_BandWidth", (1120, -420))
    try:
        _inp(width, index=1).default_value = 0.04
    except Exception:
        pass
    _link(tree, _out(absolute, "Value", index=0), _inp(width, "Value", index=0))
    inv = _math(tree, "SUBTRACT", "CIN_BandInv", (1300, -420))
    try:
        _inp(inv, "Value", index=0).default_value = 1.0
    except Exception:
        pass
    _link(tree, _out(width, "Value", index=0), _inp(inv, "Value", index=1))
    clamp = _n(tree, "ShaderNodeClamp", "CIN_BandClamp", (1480, -420))
    _link(tree, _out(inv, "Value", index=0), _inp(clamp, "Value", index=0))
    gloss_luma = _luma(tree, gin_out("Glossiness"), "CIN_Gloss", (1120, -620))
    gloss_mul = _math(tree, "MULTIPLY", "CIN_GlossBand", (1680, -480))
    _link(tree, _out(clamp, "Result", index=0), _inp(gloss_mul, index=0))
    _link(tree, gloss_luma, _inp(gloss_mul, index=1))
    gloss_gain = _math(tree, "MULTIPLY", "CIN_GlossGain", (1860, -480))
    try:
        _inp(gloss_gain, index=1).default_value = 0.2
    except Exception:
        pass
    _link(tree, _out(gloss_mul, "Value", index=0), _inp(gloss_gain, index=0))

    white_mix = _mix_color(tree, "CIN_SpecBand", (980, 40))
    _link(tree, _out(gloss_gain, "Value", index=0), _inp(white_mix, index=0))
    _link(tree, _out(cool, "Result_Color", "Result", index=2), _inp(white_mix, "A_Color", "A", index=6))
    try:
        _inp(white_mix, "B_Color", "B", index=7).default_value = (1.0, 1.0, 1.0, 1.0)
    except Exception:
        pass

    # Spec map is a weak tint on that same band, never a dielectric lobe.
    spec_fac = _math(tree, "MULTIPLY", "CIN_SpecWeak", (980, -180))
    try:
        _inp(spec_fac, "Value", index=1).default_value = 0.22
    except Exception:
        pass
    _link(tree, _out(gloss_gain, "Value", index=0), _inp(spec_fac, index=0))
    spec_mix = _mix_color(tree, "CIN_SpecTint", (1200, -40))
    _link(tree, _out(spec_fac, "Value", index=0), _inp(spec_mix, "Factor_Float", "Factor", index=0))
    _link(tree, _out(white_mix, "Result_Color", "Result", index=2), _inp(spec_mix, "A_Color", "A", index=6))
    _link(tree, gin_out("Specular"), _inp(spec_mix, "B_Color", "B", index=7))

    # Cool rim from facing, then an ink edge that wins at the silhouette.
    rim_mul = _math(tree, "MULTIPLY", "CIN_RimFac", (1200, 260))
    _link(tree, _out(layer, "Fresnel", index=1), _inp(rim_mul, "Value", index=0))
    _link(tree, gin_out("Rim Strength"), _inp(rim_mul, "Value", index=1))
    rim_mix = _mix_color(tree, "CIN_RimMix", (1420, 120))
    _link(tree, _out(rim_mul, "Value", index=0), _inp(rim_mix, "Factor_Float", "Factor", index=0))
    _link(tree, _out(spec_mix, "Result_Color", "Result", index=2), _inp(rim_mix, "A_Color", "A", index=6))
    _link(tree, gin_out("Rim Color"), _inp(rim_mix, "B_Color", "B", index=7))

    edge = _math(tree, "SUBTRACT", "CIN_Edge", (1420, -240))
    try:
        _inp(edge, "Value", index=0).default_value = 1.0
    except Exception:
        pass
    _link(tree, _out(layer, "Facing", index=0), _inp(edge, "Value", index=1))
    power = _math(tree, "POWER", "CIN_EdgePow", (1600, -240))
    try:
        _inp(power, "Value", index=1).default_value = 4.0
    except Exception:
        pass
    _link(tree, _out(edge, "Value", index=0), _inp(power, "Value", index=0))
    ink = _math(tree, "MULTIPLY", "CIN_Ink", (1780, -200))
    _link(tree, _out(power, "Value", index=0), _inp(ink, "Value", index=0))
    _link(tree, gin_out("Outline Strength"), _inp(ink, "Value", index=1))

    geo = _n(tree, "ShaderNodeNewGeometry", "CIN_Geometry", (1600, -40))
    # Backfaces ink by Outline Strength, not solid black. Hair cards are
    # double-sided; a hard 1.0 blacked out the whole hairstyle.
    back_mul = _math(tree, "MULTIPLY", "CIN_BackInk", (1780, -40))
    _link(tree, _out(geo, "Backfacing"), _inp(back_mul, index=0))
    _link(tree, gin_out("Outline Strength"), _inp(back_mul, index=1))
    back = _math(tree, "MAXIMUM", "CIN_Outline", (1960, -80))
    _link(tree, _out(ink, "Value", index=0), _inp(back, index=0))
    _link(tree, _out(back_mul, "Value", index=0), _inp(back, index=1))

    ink_mix = _mix_color(tree, "CIN_InkMix", (1780, 160))
    _link(tree, _out(back, "Value", index=0), _inp(ink_mix, "Factor_Float", "Factor", index=0))
    _link(tree, _out(rim_mix, "Result_Color", "Result", index=2), _inp(ink_mix, "A_Color", "A", index=6))
    try:
        _inp(ink_mix, "B_Color", "B", index=7).default_value = (0.0, 0.0, 0.0, 1.0)
    except Exception:
        pass

    # Flat lit color. Roughness-1 diffuse is only the light probe above.
    emit = _n(tree, "ShaderNodeEmission", "CIN_Emission", (1960, 200))
    try:
        _inp(emit, "Strength", index=1).default_value = 1.0
    except Exception:
        pass
    _link(tree, _out(ink_mix, "Result_Color", "Result", index=2), _inp(emit, "Color", index=0))

    transp = _n(tree, "ShaderNodeBsdfTransparent", "CIN_Transparent", (1960, 40))
    mix_shader = _n(tree, "ShaderNodeMixShader", "CIN_Alpha", (2140, 120))
    _link(tree, gin_out("Alpha"), _inp(mix_shader, "Fac", "Factor", index=0))
    _link(tree, _out(transp, "BSDF", index=0), _inp(mix_shader, "Shader", index=1))
    _link(tree, _out(emit, "Emission", index=0), _inp(mix_shader, "Shader_001", "Shader", index=2))
    _link(tree, _out(mix_shader, "Shader", index=0), _inp(gout, "Shader", index=0))

    tree["apex_cinematic"] = 2
    _sync_engine(tree)


def _sync_engine(tree) -> None:
    """Shader to RGB is Eevee-only. Cycles keeps the normal-dot hard mix."""
    mix = tree.nodes.get("CIN_ShadowMix")
    if mix is None:
        return
    use_cycles = _cycles_engine()
    ee = tree.nodes.get("CIN_EeveeMask")
    cy = tree.nodes.get("CIN_CyclesMask")
    src_node = cy if use_cycles or ee is None else ee
    if src_node is None:
        return
    fac = _inp(mix, "Factor_Float", "Factor", index=0)
    if fac is None:
        return
    for existing in list(getattr(fac, "links", []) or []):
        try:
            tree.links.remove(existing)
        except Exception:
            pass
    _link(tree, _out(src_node, "Value", index=0), fac)
    inv = tree.nodes.get("CIN_ShadowInv")
    if inv is not None:
        sock = _inp(inv, index=1)
        if sock is not None:
            for existing in list(getattr(sock, "links", []) or []):
                try:
                    tree.links.remove(existing)
                except Exception:
                    pass
            _link(tree, _out(src_node, "Value", index=0), sock)
    if use_cycles:
        s2 = tree.nodes.get("CIN_ShaderToRGB")
        if s2 is not None:
            for sock in s2.outputs:
                for existing in list(getattr(sock, "links", []) or []):
                    try:
                        tree.links.remove(existing)
                    except Exception:
                        pass
    try:
        tree["apex_cinematic_engine"] = "cycles" if use_cycles else "eevee"
    except Exception:
        pass


def _complete(tree) -> bool:
    if tree is None or not id_alive(tree):
        return False
    names = set(_iface_inputs(tree))
    if not set(_REQUIRED).issubset(names):
        return False
    if tree.nodes.get("CIN_ShadowMix") is None or tree.nodes.get("CIN_Emission") is None:
        return False
    if tree.nodes.get("CIN_CoolShape") is None:
        return False
    try:
        if int(tree.get("apex_cinematic", 0)) < 2:
            return False
    except Exception:
        return False
    return True


def ensure_cinematic_group():
    tree = bpy.data.node_groups.get(GROUP_NAME)
    if tree is not None and not id_alive(tree):
        tree = None
    if tree is None:
        tree = bpy.data.node_groups.new(GROUP_NAME, "ShaderNodeTree")
    if not _complete(tree):
        _rebuild(tree)
    else:
        _sync_engine(tree)
    shader_cache[CACHE_KEY] = tree
    return tree



_CARD_ALPHA = ("hair", "lash", "brow", "card", "glass")


def _uses_card_alpha(mat) -> bool:
    name = (getattr(mat, "name", "") or "").lower()
    return any(tok in name for tok in _CARD_ALPHA)


def _force_opaque(mat) -> None:
    for attr, value in (
        ("blend_method", "OPAQUE"),
        ("surface_render_method", "DITHERED"),
        ("use_transparency", False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except Exception:
                pass


class CinematicNodeAdder(NodeAdder):
    """Illustrated cinematic pass. Albedo and normal link; gloss is not roughness."""

    @staticmethod
    def _addAlbedo(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Albedo"))
        # Hair cards keep the albedo alpha. Do not treat that as an AO multiply.
        if _uses_card_alpha(mat):
            alpha = find_socket(cas_node_group, "Alpha")
            if alpha is not None and not getattr(alpha, "is_linked", False):
                link(mat.node_tree, img_node.outputs.get("Alpha"), alpha)
                set_alpha_clip(mat)
                try:
                    mat.use_backface_culling = False
                except Exception:
                    pass
        else:
            _force_opaque(mat)

    @staticmethod
    def _addNormal(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location, noncolor=True)
        link(mat.node_tree, img_node.outputs["Color"], socket(cas_node_group, "Normal Map"))

    @staticmethod
    def _addGlossy(img_path, mat, cas_node_group, location):
        # Narrow stylized band inside the group. Never a soft roughness highlight.
        img_node = _tex(mat, img_path, location, noncolor=True)
        alpha = find_socket(cas_node_group, "Glossiness")
        if alpha is None:
            return False
        return link(mat.node_tree, img_node.outputs["Color"], alpha)

    @staticmethod
    def _addSpec(img_path, mat, cas_node_group, location):
        img_node = _tex(mat, img_path, location)
        sock = find_socket(cas_node_group, "Specular")
        if sock is None:
            return False
        return link(mat.node_tree, img_node.outputs["Color"], sock)

    @staticmethod
    def _addOpacityMultiply(img_path, mat, cas_node_group, location):
        # Body, cloth, and metal stay opaque. Opacity maps there read as thin skin.
        if not _uses_card_alpha(mat):
            _force_opaque(mat)
            return False
        img_node = _tex(mat, img_path, location, noncolor=True)
        sock = find_socket(cas_node_group, "Alpha")
        if sock is None:
            return False
        ok = link(mat.node_tree, img_node.outputs["Color"], sock)
        set_alpha_clip(mat)
        try:
            mat.use_backface_culling = False
        except Exception:
            pass
        return ok

    # AO, cavity, and emissive are intentionally absent: no extra AO multiply
    # on the albedo, and no soft PBR cavity darkening.
    method = {
        "albedo": _addAlbedo,
        "gloss": _addGlossy,
        "normal": _addNormal,
        "spec": _addSpec,
        "opacity": _addOpacityMultiply,
    }

    @staticmethod
    def getShaderNodeGroup():
        cached = shader_cache.get(CACHE_KEY)
        if _complete(cached):
            _sync_engine(cached)
            return cached
        return ensure_cinematic_group()


# Register after this module finished loading so the node_adder import cycle
# does not run while either module is half-initialized.
from . import node_adder as _node_adder

_node_adder.CinematicNodeAdder = CinematicNodeAdder
_node_adder.SHADER_ADDERS["cinematic"] = CinematicNodeAdder
