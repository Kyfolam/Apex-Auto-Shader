#!/usr/bin/env python3
"""Import/unit smoke without Blender GUI.

Loads naming helpers (and package pieces that do not need a live bpy UI)
and asserts a few stable behaviors used by shade/import paths.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "apex_auto_shader"
PKG = "apex_auto_shader"


def _mock_bpy() -> None:
    if "bpy" in sys.modules:
        return
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(
        Operator=type("Operator", (), {}),
        PropertyGroup=type("PropertyGroup", (), {}),
        UIList=type("UIList", (), {}),
        Object=type("Object", (), {}),
        Collection=type("Collection", (), {}),
        AddonPreferences=type("AddonPreferences", (), {}),
        Scene=type("Scene", (), {}),
        OperatorFileListElement=type("OperatorFileListElement", (), {}),
        Menu=type("Menu", (), {}),
        Panel=type("Panel", (), {}),
        Material=type("Material", (), {}),
        VIEW3D_MT_object_context_menu=types.SimpleNamespace(append=lambda *a, **k: None, remove=lambda *a, **k: None),
        VIEW3D_MT_pose_context_menu=types.SimpleNamespace(append=lambda *a, **k: None, remove=lambda *a, **k: None),
    )
    bpy.props = types.SimpleNamespace(
        BoolProperty=lambda **k: None,
        EnumProperty=lambda **k: None,
        FloatProperty=lambda **k: None,
        StringProperty=lambda **k: None,
        CollectionProperty=lambda **k: None,
        IntProperty=lambda **k: None,
    )
    bpy.context = types.SimpleNamespace(
        preferences=types.SimpleNamespace(addons={}),
        scene=None,
        window_manager=None,
        active_object=None,
        selected_objects=[],
    )
    bpy.data = types.SimpleNamespace(
        objects={}, collections={}, actions={}, cameras={}, lights={}, images={}
    )
    bpy.ops = types.SimpleNamespace()
    bpy.app = types.SimpleNamespace(
        debug=False,
        timers=types.SimpleNamespace(register=lambda *a, **k: None),
        handlers=types.SimpleNamespace(persistent=lambda f: f, load_post=[], depsgraph_update_post=[], frame_change_post=[]),
    )
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = bpy.types
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bpy.app.handlers"] = bpy.app.handlers
    mu = types.ModuleType("mathutils")
    mu.Vector = lambda *a, **k: type("V", (), {"x": 0, "y": 0, "z": 0})()
    mu.Matrix = lambda *a, **k: type("M", (), {"to_quaternion": lambda self: None})()
    mu.Quaternion = lambda *a, **k: type("Q", (), {})()
    sys.modules["mathutils"] = mu


def _test_object_and_techart() -> None:
    import tempfile
    from pathlib import Path

    from apex_auto_shader import naming
    from apex_auto_shader.node_adder import ObjectNodeAdder, PlusNodeAdder, SHADER_ADDERS

    model = "uh_snapback_statue_legend_alter_01_LOD0"
    tex = "uh_snapback_statue_legend_alter_onemat_ao.png"
    assert naming.model_dir_name(model) == "uh_snapback_statue_legend_alter_01"
    assert naming.model_dir_name("body_0_uh_snapback_statue_legend_alter_onemat") == (
        "uh_snapback_statue_legend_alter_onemat"
    )
    assert not naming.is_legend_character_name(model)
    assert naming.is_legend_character_name("wraith_base_w_LOD0")
    parsed = naming.parse_object_texture_name(tex, naming.model_dir_name(model))
    assert parsed is not None, "statue texture should match object prefix"
    assert parsed.slot == "ao", parsed.slot
    assert parsed.bodypart == "onemat", parsed.bodypart
    assert naming.object_prefixes_match(model, tex)
    assert naming.shared_leading_tokens(model, tex)[:5] == [
        "uh",
        "snapback",
        "statue",
        "legend",
        "alter",
    ]
    assert "object" in SHADER_ADDERS
    assert ObjectNodeAdder is not PlusNodeAdder
    assert issubclass(ObjectNodeAdder, PlusNodeAdder)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        statues = root / "mdl" / "uh" / "snapback" / "statues"
        model_dir = statues / "uh_snapback_statue_legend_alter_01"
        sibling = statues / "uh_snapback_statue_legend_wraith_01"
        model_dir.mkdir(parents=True)
        sibling.mkdir(parents=True)
        (model_dir / "uh_snapback_statue_legend_alter_onemat_ao.png").write_bytes(b"x")
        (model_dir / "uh_snapback_statue_legend_alter_onemat_col.png").write_bytes(b"x")
        (sibling / "uh_snapback_statue_legend_wraith_onemat_ao.png").write_bytes(b"x")
        cast = statues / "uh_snapback_statue_legend_alter_01_LOD0.cast"
        cast.write_bytes(b"x")

        hit = naming.scan_object_folder(model_dir, naming.model_dir_name(model))
        slots = sorted(t.slot for t in hit.textures if t.slot)
        assert slots == ["albedo", "ao"], slots
        assert {t.bodypart for t in hit.textures} == {"onemat"}
        bp = naming.guess_bodypart(
            ["body_0_uh_snapback_statue_legend_alter_onemat"],
            hit.bodyparts(),
        )
        assert bp == "onemat", bp

        parent_hit = naming.scan_object_folder(statues, naming.model_dir_name(model))
        names = {Path(t.path).name for t in parent_hit.textures}
        assert "uh_snapback_statue_legend_alter_onemat_ao.png" in names
        assert "uh_snapback_statue_legend_wraith_onemat_ao.png" not in names

        found = naming.find_texture_folder(cast)
        assert found is not None
        assert found.resolve() == model_dir.resolve(), found

        techart = (
            root
            / "mdl"
            / "techart"
            / "mshop"
            / "characters"
            / "legends"
            / "wraith"
            / "wraith_base"
        )
        techart.mkdir(parents=True)
        (techart / "wraith_base_body_col.png").write_bytes(b"x")
        wcast = root / "mdl" / "characters" / "wraith" / "wraith_base_w_LOD0.cast"
        wcast.parent.mkdir(parents=True, exist_ok=True)
        wcast.write_bytes(b"x")
        cands = naming.techart_legend_texture_candidates(wcast)
        assert cands, "techart legend path should be proposed first"
        assert any("techart" in str(p).replace("\\", "/").lower() for p in cands)
        all_cands = naming.texture_folder_candidates(wcast)
        assert str(cands[0]) == str(all_cands[0]), (
            f"techart should be first candidate, got {all_cands[0]}"
        )
        found_w = naming.find_texture_folder(wcast)
        assert found_w is not None
        assert found_w.resolve() == techart.resolve(), found_w


def _test_cosmetics_and_index() -> None:
    from apex_auto_shader import pack
    from apex_auto_shader import naming

    assert naming.legend_display_name("overdrive") == "Axle"
    assert naming.bannerpose_display_name("overdrive_gladcard_rare_09", "axle") == "Bring It On"
    assert naming.bannerpose_display_name("animated_alter_gladcard_epic_05_knockknock", "alter") == (
        "Special Delivery"
    )
    assert naming.pose_subtype("alter_gladcard_rare_07", "alter") == "static"
    assert naming.pose_subtype("alter_gladcard_epic_01_stare", "alter") == "animated"
    assert naming.pose_subtype("animated_alter_gladcard_rare_01", "alter") == "static"
    assert naming.pose_subtype("alter_gladcard_animated_notyou_idle", "alter") == "animated"
    assert naming.pose_subtype("alter_gladcard_animated_notyou", "alter") == "animated"
    assert naming.pose_subtype("animated_alter_gladcard_epic_05_capturemode", "alter") == "capture"
    assert naming.bannerpose_display_name("light_wraith_gladcard_rare_01", "wraith") == "Mind Games"
    assert naming.bannerpose_display_name("mp_alter_gladcard_epic_05", "alter") == "Special Delivery"
    assert naming.bannerpose_display_name("ash_gladcard_s11e01_epic_01", "ash") == "Sliced and Diced"
    assert naming.bannerpose_display_name("ash_gladcard_epic_01", "ash") == "Palm Pilot"
    assert not naming.skip_bannerpose("light_wraith_gladcard_rare_01")
    assert naming.is_banner_clip("ptpov_alter_gladcard_epic_05_knockknock_capturemode")

    assert naming.emote_display_name("gibraltar_ground_emote_haka", "gibraltar") == "Haka"
    assert naming.emote_display_name("gibraltar_ground_emote_kickflip", "gibraltar") == "Kickflip"
    assert naming.emote_display_name("overdrive_ground_emote_motorcycle", "axle") == "Power Loop"
    drop = naming.emote_display_name("alter_freefall_emote_01", "alter")
    assert drop != "Getting Started", drop
    assert "getting started" not in drop.lower()
    assert naming.pose_subtype("animated_alter_gladcard_epic_05_capturemode", "alter") == "capture"
    assert naming.bannerpose_display_name(
        "animated_alter_gladcard_epic_05_knockknock_capturemode", "alter"
    ) == "Special Delivery"
    assert naming.bannerpose_display_name("alter_gladcard_static_crouch", "alter") == "Perfect Balance"
    assert naming.bannerpose_display_name("alter_gladcard_animated_notyou", "alter") == "Next In Line"
    assert naming.bannerpose_display_name("ash_gladcard_animated_ratcrawl", "ash") == "Palm Pilot"
    assert naming.emote_display_name("alter_ground_emote_tailstand", "alter") == "Elevated Applause"
    assert naming.emote_display_name("alter_ground_emote_basic", "alter") == "Getting Started"
    assert naming.emote_display_name("bangalore_ground_emote_pushups", "bangalore") == "No Sweat"
    assert naming.emote_display_name("gibraltar_ground_emote_bringit", "gibraltar") == "Bring It"
    assert naming.emote_display_name("wraith_ground_emote_cutthroat", "wraith") == "Cut Throat"
    assert naming.emote_display_name("bangalore_ground_emote_boxing_start", "bangalore") == (
        "Butterfly Barrage"
    )
    assert naming.emote_display_name("wattson_ground_emote_nessie_drop", "wattson") == "Easter Egg"
    assert naming.emote_subtype("wattson_ground_emote_nessie_drop") == "ground"
    assert naming.finisher_display_name("bangalore_execution_base", "bangalore") == "Recycle"
    assert naming.finisher_display_name("alter_playing_execution_attacker", "alter") == "Dynamic Exit"
    assert naming.finisher_display_name("alter_execution_prestige", "alter") == "Crystal Corruption"
    fov = naming.banner_fov_for("alter_gladcard_static_crouch", "alter")
    assert fov is not None and abs(fov - 6.27) < 0.05, fov
    setup = naming.banner_setup_for("alter_gladcard_static_crouch", "alter")
    assert setup["kind"] == "static", setup
    assert setup["light"] == "alter_gladcard_static_crouch_light", setup
    assert len(setup.get("lights") or []) == 4, setup
    setup = naming.banner_setup_for("alter_gladcard_animated_notyou", "alter")
    assert setup["kind"] == "animated", setup
    assert setup["light"] == "alter_gladcard_animated_notyou_light", setup
    setup = naming.banner_setup_for("alter_gladcard_animated_notyou_idle", "alter")
    assert setup["kind"] == "animated", setup
    assert setup["light"] == "alter_gladcard_animated_notyou_idle_light", setup
    wraith_setup = naming.banner_setup_for("wraith_gladcard_common_sidestep", "wraith")
    assert wraith_setup["kind"] == "static", wraith_setup
    assert len(wraith_setup.get("lights") or []) == 4, wraith_setup
    assert wraith_setup["fov"] is not None
    assert abs(float(wraith_setup["fov"]) - 9.91) < 0.05, wraith_setup
    from apex_auto_shader.naming import cosmetics as _cos

    clips = _cos._load_json("itemflav_clips.json")
    assert clips.get("stats", {}).get("banner") == 458, clips.get("stats")
    assert clips.get("stats", {}).get("bannerLights") == 458, clips.get("stats")
    assert all(len(row.get("lights") or []) == 4 for row in clips["banner"].values())
    alter_l0 = clips["banner"]["alter/epic_01.json"]["lights"][0]["brightness"]
    assert abs(float(alter_l0) - 0.07) < 1e-6, alter_l0
    bang_raw = clips["banner"]["bangalore/epic_01.json"]["lights"][0]
    assert bang_raw.get("brightness") is None, bang_raw
    bang = naming.banner_setup_for("bangalore_gladcard_animated_drill", "bangalore")
    assert bang["kind"] == "animated", bang
    assert bang["lights"][0]["brightness"] == 0.0, bang["lights"][0]
    assert abs(float(bang["lights"][1]["brightness"]) - 2.0) < 1e-6, bang["lights"][1]
    octane = naming.banner_setup_for("octane_gladcard_animated_stimhead", "octane")
    assert octane["kind"] == "animated", octane
    assert len(octane.get("lights") or []) == 4
    assert octane["fov"] is not None
    picked = naming.pick_banner_list_clips(
        [
            ("alter_gladcard_animated_notyou_idle", "/a/notyou_idle.cast"),
            ("alter_gladcard_animated_notyou", "/a/notyou.cast"),
            ("alter_gladcard_animated_notyou_light", "/a/notyou_light.cast"),
            ("alter_gladcard_static_crouch", "/a/crouch.cast"),
            ("alter_gladcard_static_crouch_light", "/a/crouch_light.cast"),
            ("alter_gladcard_epic_01", "/a/epic_01.cast"),
            ("animated_alter_gladcard_epic_05_knockknock_capturemode", "/a/kk_cap.cast"),
            ("alter_gladcard_animated_knockknock", "/a/kk.cast"),
            ("alter_gladcard_animated_knockknock_idle", "/a/kk_idle.cast"),
        ],
        "alter",
    )
    static_names = [n for n, _p in picked["static"]]
    anim_names = [n for n, _p in picked["animated"]]
    cap_names = [n for n, _p in picked["capture"]]
    assert static_names == ["alter_gladcard_static_crouch"], static_names
    assert "alter_gladcard_animated_notyou" in anim_names, anim_names
    assert "alter_gladcard_animated_knockknock" in anim_names, anim_names
    assert all("idle" not in n for n in anim_names), anim_names
    assert all("light" not in n for n in static_names + anim_names + cap_names)
    assert cap_names == ["animated_alter_gladcard_epic_05_knockknock_capturemode"], cap_names
    assert len(anim_names) == 2, anim_names
    mesh, variant = naming.split_mesh_variant("alter_rare_01")
    assert mesh == "alter_base" and variant == "rare_01"
    mesh, variant = naming.split_mesh_variant("alter_epic_01")
    assert mesh == "alter_base" and variant == "epic_01"
    assert "alter_base" in naming.cast_search_prefixes("alter_rare_01")
    mesh, variant = naming.split_mesh_variant("alter_lgnd_v23_fashionfatale_rc02")
    assert mesh == "alter_lgnd_v23_fashionfatale" and variant == "rc02"

    assert naming.finisher_display_name("medium_overdrive_execution_lgnd_knee_wheel", "axle") == (
        "Face First"
    )
    assert naming.finisher_display_name("medium_alter_execution_tail_whip", "alter") == "Tail End"
    assert naming.finisher_display_name("medium_wraith_execution_ninja", "wraith") == (
        "Existential Crisis"
    )

    rows = pack.load_index()
    assert len(rows) >= 2652, len(rows)
    legends = {lg for lg, _n, _e in rows}
    assert "Axle" in legends
    assert "Fade" not in legends
    assert any(name == "Restless Spirit" for _lg, name, _e in rows)
    assert pack.prefix_for("Alter", "Alterior Motive").endswith("rc02")
    assert pack.prefix_for("Alter", "Fashion Fatale").endswith("rc01")
    assert pack.prefix_for("Alter", "Moonlit Menace") == "alter_lgnd_v23_fashionfatale"
    assert pack.prefix_for("Alter", "Wallflower") == "alter_rare_01"
    assert pack.prefix_for("Alter", "Fiber Optics") == "alter_epic_01"
    assert pack.prefix_for("Alter", "Original") == "alter_base"
    assert pack.search_index("wallflower", "Alter")[0][1] == "Wallflower"
    assert any(n == "Fashion Fatale" for _lg, n, _e in pack.search_index("fatale", "Alter"))
    sugs = pack.suggest_names("wall", "Alter")
    assert any("Wallflower" == s for s in sugs), sugs
    base, code = naming.split_recolor_prefix("alter_lgnd_v23_fashionfatale_rc02")
    assert base == "alter_lgnd_v23_fashionfatale" and code == "rc02"
    assert naming.split_recolor_prefix("bloodhound_lgnd_v19_plaguedoctor_rt01rc01")[1] == "rt01rc01"
    cosmetics = PKG_DIR / "asset" / "cosmetics"
    assert (cosmetics / "banner_poses_by_legend.json").is_file()
    assert (cosmetics / "character_emotes_by_legend.json").is_file()
    assert (cosmetics / "character_executions_by_legend.json").is_file()
    assert (cosmetics / "itemflav_clips.json").is_file()


def main() -> int:
    _mock_bpy()
    sys.path.insert(0, str(ROOT))

    import bpy
    import apex_auto_shader
    from apex_auto_shader import anim, naming, shade
    from apex_auto_shader.shade import extras

    assert naming.classify_animation("wraith_emote_dance") == "emote"
    assert naming.classify_animation("mp_sprint_forward") == "ingame"
    assert naming.legend_display_name("wraith") == "Wraith"
    assert naming.is_lod0_cast("wraith_base_w_lod0.cast")
    assert not naming.is_lod0_cast("wraith_base_w_lod1.cast")
    cycled = naming.cycled_level_name("skin_level01_w")
    assert cycled.endswith("level02_w") or "level02" in cycled
    slot = naming.canonical_slot("albedoTexture")
    assert slot, f"canonical_slot(albedoTexture) returned {slot!r}"

    for op in (
        "APEX_OT_add_camera",
        "APEX_OT_set_camera_pov",
        "APEX_OT_camera_preset",
        "APEX_OT_showcase",
        "APEX_OT_import_cast",
    ):
        assert hasattr(anim, op), op
    assert hasattr(anim, "anim_classes") and len(anim.anim_classes) >= 10
    assert hasattr(anim, "apply_camera_pov")
    assert hasattr(anim, "detect_cast_camera_fov")
    assert hasattr(anim, "sync_banner_camera")
    assert hasattr(anim, "_look_at_y_up")
    assert hasattr(anim, "_set_camera_shift")
    assert abs(-0.5 * (anim.PORTRAIT_RES_Y / anim.PORTRAIT_RES_X) - (-8 / 9)) < 1e-9
    stale = types.SimpleNamespace(__name__="sync_banner_camera")
    bpy.app.handlers.frame_change_post.append(stale)
    extras.register_handlers()
    names = [getattr(fn, "__name__", "") for fn in bpy.app.handlers.frame_change_post]
    assert "sync_banner_camera" not in names
    extras.unregister_handlers()
    assert anim._banner_light_energy(0) == 0
    assert anim._banner_light_energy(6.0) == anim._banner_light_energy(1.25)
    assert anim._banner_light_energy(0.2) > 300
    assert anim.MODEL_EULER_DEG == (0.0, 0.0, 0.0)
    assert anim.LAYOUT_UP == (0.0, 1.0, 0.0)
    assert anim.LAYOUT_FORWARD == (0.0, 0.0, 1.0)
    assert "jx_c_pov" in anim.POV_BONES
    assert hasattr(anim, "APEX_OT_set_camera_pov")
    assert hasattr(anim, "_gather_import_casts"), "import CAST helper must be re-exported"
    assert hasattr(anim, "_purge_victim_characters")
    assert hasattr(anim, "_action_fcurves")
    assert hasattr(anim, "_pin_object_layout")
    assert hasattr(anim, "_restore_transform")

    class _TruthyEmpty(list):
        def __bool__(self):
            return True

    class _Bag:
        def __init__(self):
            self.fcurves = ["bag-curve"]

    class _Strip:
        channelbags = [_Bag()]
        channelbag = None

    class _Layer:
        strips = [_Strip()]

    class _Action:
        fcurves = _TruthyEmpty()
        layers = [_Layer()]
        slots = []

    found = anim._action_fcurves(_Action())
    assert "bag-curve" in found, found
    assert hasattr(anim, "resolve_armature")
    assert hasattr(anim, "resolve_shade_objects") or hasattr(anim.character, "resolve_character")

    # Nested packages used by Optic Enhancer host.py aliases
    assert hasattr(anim, "character")
    assert hasattr(naming, "tex")
    assert hasattr(shade, "extras")
    assert hasattr(shade, "utils")
    assert hasattr(shade.utils, "shade_selected")
    assert hasattr(shade.extras, "should_skip_lod")
    assert hasattr(naming.tex, "is_eye_material") or hasattr(naming, "is_eye_material")
    assert hasattr(naming, "scan_object_folder")
    assert hasattr(naming, "techart_legend_texture_candidates")
    assert hasattr(naming, "parse_object_texture_name")

    _test_object_and_techart()
    _test_cosmetics_and_index()

    assert (PKG_DIR / "asset" / "wraith" / "ncache.bin").is_file()
    assert (PKG_DIR / "asset" / "Apex Shader.blend").is_file() or (
        PKG_DIR / "asset" / "Apex_Shader_Plus1.blend"
    ).is_file()
    assert not (ROOT / "skins.json").exists(), "plaintext skins.json must not exist"
    assert not (PKG_DIR / "skins.json").exists(), "plaintext skins.json must not exist"

    assert apex_auto_shader.bl_info["version"] >= (2, 0, 0)

    print("smoke_import: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke_import: FAIL: {exc}", file=sys.stderr)
        raise
