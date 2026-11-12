#!/usr/bin/env python3
"""Import/unit smoke without Blender GUI.

Loads naming helpers (and package pieces that do not need a live bpy UI)
and asserts a few stable behaviors used by shade/import paths.
"""
from __future__ import annotations

import re
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
    from apex_auto_shader.prefs import SHADER_ITEMS
    assert all(item[0] != "object" for item in SHADER_ITEMS)

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
    mesh, variant = naming.split_mesh_variant("wraith_epicp_v23_voidsinister")
    assert mesh == "wraith_epicp_v23_voidsinister", (mesh, variant)
    assert "wraith_base" not in naming.cast_search_prefixes("wraith_epicp_v23_voidsinister")
    assert "wraith_epic_v23_voidsinister" in naming.cast_search_prefixes("wraith_epicp_v23_voidsinister")

    assert naming.finisher_display_name("medium_overdrive_execution_lgnd_knee_wheel", "axle") == (
        "Face First"
    )
    assert naming.finisher_display_name("medium_alter_execution_tail_whip", "alter") == "Tail End"
    assert naming.finisher_display_name("medium_wraith_execution_ninja", "wraith") == (
        "Existential Crisis"
    )
    assert naming.clip_display_name("AIM_alter_idle", "alter", "idle") == "AIM"
    assert naming.clip_display_name("AIM_alter_crouch_idle", "alter", "idle") == "Crouch"
    assert naming.clip_display_name("alter_AIM_sprint", "alter", "ingame") == "Sprint"
    assert naming.clip_display_name("newcastle_melee_01", "newcastle", "ingame") == "Melee_01"
    assert naming.clip_display_name("alter_confirmation_select", "alter", "select") == "Confirmation"
    lobby = naming.clip_display_name("alter_lobby_refresh_ready01_idle_0", "alter", "select")
    assert lobby == "Refresh Ready01 Idle_0", lobby
    assert "alter" not in lobby.lower() and "lobby" not in lobby.lower()
    intro = naming.clip_display_name("alter_lobby_refresh_pose01_intro_0", "alter", "select")
    assert intro == "Refresh Pose01_0", intro
    assert naming.action_subgroup("AIM_newcastle_crouch_pistol_0", "ingame") == ("crouch", "Crouch")
    assert naming.action_subgroup("AIM_alter_idle", "idle") == ("aim", "AIM")
    from apex_auto_shader.prop import pick_socket_bone, pick_weapon_bone

    class _Bone:
        def __init__(self, name, parent=None):
            self.name = name
            self.parent = parent

    gun = [_Bone("def_c_root"), _Bone("ja_c_propGun", parent=True), _Bone("def_c_trigger")]
    assert pick_socket_bone(gun) == "ja_c_propGun"
    assert pick_weapon_bone(gun) == "ja_c_propGun"
    loose = [_Bone("wpn_r301_root")]
    assert pick_weapon_bone(loose) == "wpn_r301_root"
    assert pick_socket_bone(loose) == ""
    from apex_auto_shader.anim.const import ANIM_PLAY_MIN_BYTES

    assert ANIM_PLAY_MIN_BYTES == 200 * 1024
    assert naming.plain_folder_legend("Jump") == ""
    assert naming.plain_folder_legend("Land") == ""
    assert naming.plain_folder_legend("Lower") == ""
    assert naming.is_skin_legend(naming.plain_folder_legend("Wraith"))
    assert naming.plain_folder_legend("Wraith") == "wraith"
    from apex_auto_shader.prop import is_prop_main_mesh

    assert is_prop_main_mesh("body_0_car_base_main")
    assert is_prop_main_mesh("sight_front_1_car_base_main")
    assert not is_prop_main_mesh("sight_hcog_1_hcog_r2")
    assert not is_prop_main_mesh("lasersight_sml_1_laser_sight")
    from apex_auto_shader.prop import find_prop_texture_folder, is_ref_prop, prop_kind, prop_label, prop_texture_files, prop_texture_match
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "v18_kunai"
        tex = root / "heirloom_wraith_v18_kunai_w"
        tex.mkdir(parents=True)
        (tex / "throwing_knife_col.png").write_bytes(b"x")
        (tex / "throwing_knife_cav.png").write_bytes(b"x")
        cast = root / "heirloom_wraith_v18_kunai_w_LOD0.cast"
        cast.write_bytes(b"x")
        assert prop_kind(cast) == "heirloom"
        assert find_prop_texture_folder(cast) == tex
        names = {path.name for path in prop_texture_files(tex, cast.name)}
        assert names == {"throwing_knife_col.png", "throwing_knife_cav.png"}
        match = prop_texture_match(tex, cast.name)
        assert match is not None
        assert {tex.slot for tex in match.textures} == {"albedo", "cavity"}
        weird = Path(tmp) / "box"
        maps = weird / "textures_here"
        maps.mkdir(parents=True)
        (maps / "knife_col.png").write_bytes(b"x")
        other = weird / "unrelated_LOD0.cast"
        other.write_bytes(b"x")
        assert find_prop_texture_folder(other) == maps
        assert prop_kind(other) == "gun"
    assert prop_label(Path("heirloom_wraith_v18_kunai_w_LOD0.cast"), "heirloom") == "wraith v18 kunai w"
    assert "heirloom" not in prop_label(Path("heirloom_wraith_v18_kunai.cast"), "heirloom").lower()
    assert prop_label(Path("car_base_ref_0_w_LOD0.cast"), "gun") == "car base w"
    assert is_ref_prop(Path("wraith_ref_0.cast"))
    assert naming.anim_query_match("eldi_retla", "AIM_alter_idle")
    bases = naming.bases_with_extra_index(["pose_0", "pose_1", "only_0"])
    assert naming.hide_lone_zero("only_0", bases)
    assert not naming.hide_lone_zero("pose_0", bases)
    assert not naming.hide_lone_zero("pose_1", bases)
    from apex_auto_shader.anim import _bases_that_keep_zero, _clip_row_label

    class _Clip:
        def __init__(self, name, path, group, legend):
            self.name = name
            self.path = path
            self.group = group
            self.legend = legend
            self.is_header = False

    lone = _Clip("x", "AIM_alter_idle_0.cast", "alter:idle", "alter")
    assert _clip_row_label(lone, set()) == "AIM"
    assert _bases_that_keep_zero(["AIM_0", "AIM_1"]) == {"AIM"}
    assert _clip_row_label(lone, {"AIM"}) == "AIM_0"
    from apex_auto_shader.panel import _order_find_rows, _rarity_rank

    skins = [
        ("Wraith", "Zebra", "", "Common", True),
        ("Wraith", "Alpha", "", "Legendary", True),
        ("Ash", "Beta", "", "Epic", True),
    ]
    ordered = _order_find_rows(list(skins), "rarity", False)
    assert [row[1] for row in ordered] == ["Alpha", "Beta", "Zebra"]
    assert _rarity_rank("Legendary Recolor") < _rarity_rank("Common")
    import tempfile
    from apex_auto_shader.naming.tex import scan_recolor_stack

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "wraith_base"
        rec = base.parent / "wraith_base_rc01"
        base.mkdir()
        rec.mkdir()
        (base / "body_0_wraith_base_col.png").write_bytes(b"base")
        (rec / "body_0_wraith_base_rc01_col.png").write_bytes(b"recolor")
        match = scan_recolor_stack(base, "wraith_base", apply_recolor=True, recolor_code="rc01")
        albedo = [tex.path for tex in match.textures if tex.slot == "albedo"]
        assert albedo and "rc01" in albedo[0].replace("\\", "/"), albedo
    from apex_auto_shader.shade.utils import hold_rig_visibility, rig_visibility_held

    assert not rig_visibility_held()
    hold_rig_visibility(True)
    assert rig_visibility_held()
    hold_rig_visibility(False)
    assert not rig_visibility_held()
    assert naming.anim_query_match("crouch aim", "AIM_alter_crouch_idle")
    assert not naming.anim_query_match("wraith", "AIM_alter_idle")

    rows = pack.load_index()
    assert len(rows) >= 2652, len(rows)
    legends = {lg for lg, _n, _e in rows}
    assert "Axle" in legends
    assert "Fade" not in legends
    assert "_unlisted" not in legends
    assert pack.unreleased_needles() == ()
    restless = pack.search_index("Restless Spirit", "Alter")
    assert restless and restless[0][1] == "Restless Spirit", restless
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
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "pilot_light_wraith_cyber_ninja"
        folder.mkdir()
        cast = folder / "pilot_light_wraith_cyber_ninja_LOD0.cast"
        cast.write_bytes(b"wraith_lgnd_v19_voidwalker_body_col")
        (folder / "wraith_lgnd_v19_voidwalker_body_col.png").write_bytes(b"")
        pack.walk_model_index(root)
        cyber = pack.search_index("cyber")
        assert any(name == "Voidwalker" for _lg, name, _e in cyber), cyber
        ninja = pack.search_index("cyber_ninja")
        assert any(name == "Voidwalker" for _lg, name, _e in ninja), ninja
        assert pack.search_index("Voidwalker")[0][1] == "Voidwalker"
        linked = pack.casts_for_skin("wraith_lgnd_v19_voidwalker", [str(cast)])
        assert linked and "cyber_ninja" in linked[0].replace("\\", "/"), linked
        alone = root / "codename"
        alone.mkdir()
        hidden = alone / "pilot_light_wraith_cyber_ninja_LOD0.cast"
        hidden.write_bytes(b"xx wraith_lgnd_v19_voidwalker_body_albedoTexture.png \x00")
        pack.walk_model_index(alone)
        named = pack.search_index("cyber_ninja")
        assert any(name == "Voidwalker" for _lg, name, _e in named), named
        linked = pack.casts_for_skin("wraith_lgnd_v19_voidwalker", [str(hidden)])
        assert linked and hidden.name in Path(linked[0]).name, linked
        assert "Voidwalker" in pack.suggest_names("cyber"), pack.suggest_names("cyber")
        assert "Voidwalker" in pack.suggest_names("cyb"), pack.suggest_names("cyb")
        assert "Voidwalker" in pack.suggest_names("nin"), pack.suggest_names("nin")
        from apex_auto_shader.anim.files import is_ignored_clip
        assert is_ignored_clip("radoll_0")
        assert is_ignored_clip("wraith_radoll_0.cast")
        assert is_ignored_clip("ref_0")
        assert is_ignored_clip("pathfinder_ref_0")
        assert not is_ignored_clip("wraith_emote_wave")
        empty = root / "missing"
        empty.mkdir()
        pack.walk_model_index(empty)
    base, code = naming.split_recolor_prefix("alter_lgnd_v23_fashionfatale_rc02")
    assert base == "alter_lgnd_v23_fashionfatale" and code == "rc02"
    assert naming.split_recolor_prefix("bloodhound_lgnd_v19_plaguedoctor_rt01rc01")[1] == "rt01rc01"
    cosmetics = PKG_DIR / "asset" / "cosmetics"
    assert (cosmetics / "banner_poses_by_legend.json").is_file()
    assert (cosmetics / "character_emotes_by_legend.json").is_file()
    assert (cosmetics / "character_executions_by_legend.json").is_file()
    assert (cosmetics / "itemflav_clips.json").is_file()

    assert naming.base_prefix_from_pilot("pilot_light_wattson_LOD0.cast") == "wattson_base"
    assert naming.texture_prefix_from_source("pilot_medium_pathfinder") == "pathfinder_base"
    assert naming.prefixes_compatible(
        "pathfinder_lgnd_v24_anniversary_body_col.png", "pathfinder_lgnd_v24_prowear"
    ) is False
    assert naming.prefixes_compatible(
        "pathfinder_mythic_v24_pilot_body_col.png", "pathfinder_lgnd_v24_prowear"
    ) is False
    assert naming.prefixes_compatible(
        "pathfinder_lgnd_v24_prowear_body_col.png", "pathfinder_lgnd_v24_prowear"
    ) is True
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name in (
            "wattson_base_gear_ao.png",
            "wattson_base_gear_asd.png",
            "wattson_base_gear_cav.png",
            "wattson_base_gear_col.png",
            "pathfinder_lgnd_v24_prowear_body_col.png",
            "pathfinder_lgnd_v24_prowear_body_ao.png",
            "pathfinder_lgnd_v24_anniversary_body_col.png",
            "pathfinder_mythic_v24_pilot_body_col.png",
        ):
            (folder / name).write_bytes(b"x")
        wattson = naming.scan_folder(folder, naming.base_prefix_from_pilot("pilot_light_wattson"))
        assert naming.guess_bodypart(["body_0_wattson_base_gear"], wattson.bodyparts()) == "gear"
        prowear = naming.scan_folder(folder, "pathfinder_lgnd_v24_prowear")
        assert prowear.bodyparts() == ["body"], prowear.bodyparts()
        assert (
            naming.guess_bodypart(
                ["body_0_pathfinder_lgnd_v24_prowear_body.001"], prowear.bodyparts()
            )
            == "body"
        )
        assert naming.skin_prefix("body_0_pathfinder_lgnd_v20_boosted_body") == (
            "pathfinder_lgnd_v20_boosted"
        )
        assert naming.skin_prefix("pathfinder_v20_bp_LOD0.cast") == "pathfinder_v20_bp"
        assert naming.season_prefix_aliases(
            "pathfinder_v20_bp",
            ["body_0_pathfinder_lgnd_v20_boosted_body"],
        )[0] == "pathfinder_lgnd_v20_boosted"
        assert naming.season_prefix_aliases(
            "pathfinder_v19_pacer",
            ["body_0_pathfinder_lgnd_v19_pacer_gear"],
        )[0] == "pathfinder_lgnd_v19_pacer"
        v21 = naming.season_prefix_aliases(
            "pathfinder_v21_arenas",
            ["body_0_pathfinder_v21_arenas_body"],
        )
        assert v21[0] == "pathfinder_lgnd_v21_arenas", v21
        assert naming.season_prefix_aliases("pathfinder_lgnd_v22_magicgoth", [])[0] == (
            "pathfinder_lgnd_v22_magicgoth"
        )
        assert naming.pilot_slot_model("pilot_heavy_pathfinder_legendary_01") == (
            "pathfinder",
            "legendary",
        )
        assert naming.pilot_slot_model("pilot_light_wraith_legendary_03") == (
            "wraith",
            "legendary",
        )
        assert naming.pilot_slot_model("pilot_medium_bangalore_epic_02") == (
            "bangalore",
            "epic",
        )
        assert naming.texture_set_prefix("pathfinder_lgnd_v19_pacer_body_col.png") == (
            "pathfinder_lgnd_v19_pacer"
        )
        assert naming.texture_set_prefix("wraith_lgnd_v19_voidwalker_rt01_body_col.png") == (
            "wraith_lgnd_v19_voidwalker"
        )
        assert naming.prefixes_for_pilot_model(
            "pilot_heavy_pathfinder_legendary_01",
            [
                "pathfinder_lgnd_v19_pacer_body_col.png",
                "pathfinder_lgnd_v19_pacer_body_ao.png",
                "pathfinder_lgnd_v19_pacer_rt01_body_col.png",
            ],
        ) == ["pathfinder_lgnd_v19_pacer"]
        assert naming.prefixes_for_pilot_model(
            "pilot_light_wraith_legendary_02",
            [
                "wraith_lgnd_v19_voidwalker_gear_col.png",
                "wraith_lgnd_v19_voidwalker_body_col.png",
            ],
        ) == ["wraith_lgnd_v19_voidwalker"]
        assert naming.prefixes_for_pilot_model(
            "pilot_medium_bangalore_legendary_04",
            ["bangalore_lgnd_v19_overdrive_body_col.png"],
        ) == ["bangalore_lgnd_v19_overdrive"]
        assert naming.texture_set_prefix("pathfinder_lgnd_v24_prowear_emotes_col.png") == (
            "pathfinder_lgnd_v24_prowear"
        )
        assert naming.texture_set_prefix(
            "pathfinder_lgnd_v24_onesieelite_vfx_lines_col.png"
        ) == "pathfinder_lgnd_v24_onesieelite"
        assert naming.skin_prefix("body_0_pathfinder_lgnd_v24_prowear_emotes") == (
            "pathfinder_lgnd_v24_prowear"
        )
        assert naming.parse_skin_identity("pathfinder_lgnd_v24_prowear_emotes").skin == "prowear"
        assert naming.skin_prefix("body_0_pathfinder_lgnd_v24_prowear_jumpkit") == (
            "pathfinder_lgnd_v24_prowear"
        )
        assert naming.texture_set_prefix(
            "pathfinder_lgnd_v24_prowear_emotes_frightened_col.png"
        ) == "pathfinder_lgnd_v24_prowear"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_jumpkit"], ["body", "gear"]
        ) == "gear"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_gauntlet"], ["body", "grapple"]
        ) == "grapple"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_grapple"], ["gauntlet", "body"]
        ) == "gauntlet"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_emotes_frightened"],
            ["body", "emotes_frightened"],
        ) == "emotes_frightened"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_shield"], ["body", "shield"]
        ) == "shield"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_fur"], ["body", "fur"]
        ) == "fur"
        assert naming.skin_prefix("body_0_pathfinder_lgnd_v24_prowear_zipline") == (
            "pathfinder_lgnd_v24_prowear"
        )
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_zipline"], ["body", "head", "gear"]
        ) == "gear"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear"], ["body", "head", "gear"]
        ) == "body"
        assert naming.guess_bodypart(
            ["head_0_pathfinder_lgnd_v24_prowear"],
            ["onesieelite_head", "prowear_head", "body"],
        ) == "prowear_head"
        assert naming.guess_bodypart(
            ["body_0_pathfinder_lgnd_v24_prowear_head"], ["body", "head", "gear", "zipline"]
        ) == "head"
        assert naming.prefixes_compatible(
            "pathfinder_mythic_v24_pilot_body_col.png",
            "pathfinder_lgnd_v24_prowear",
        ) is False
        assert naming.candidate_matches_mesh(
            "body_0_pathfinder_lgnd_v24_prowear_head",
            "pathfinder_mythic_v24_pilot",
        ) is False
        assert naming.candidate_matches_mesh(
            "body_0_pathfinder_lgnd_v24_prowear_head",
            "pathfinder_lgnd_v24_prowear",
        ) is True
        assert naming.skin_prefix("body_0_8533931396491904913") == ""
        assert naming.part_hash_kind("body_0_9444831493659426347.001") == "head"
        assert naming.part_hash_kind("body_0_10849430867501589620") == "hair"
        assert naming.eye_hash_kind("body_0_16564475196701862357.002") == "eyecornea"
        assert naming.is_numeric_filler_mesh("body_0_8533931396491904913") is False
        assert naming.is_numeric_filler_mesh("body_0_999") is True
        assert naming.candidate_matches_mesh(
            "body_0_8533931396491904913",
            "wraith_lgnd_v19_voidwalker",
        ) is True
        assert naming.guess_bodypart(
            ["body_0_8533931396491904913"],
            ["body", "head", "hair", "gear"],
        ) == "gear"
        assert naming.guess_bodypart(
            ["wraith_lgnd_v19_voidwalker_body", "body_0_9444831493659426347"],
            ["body", "head", "hair", "gear"],
        ) == "head"
        assert naming.guess_bodypart(
            ["wraith_lgnd_v19_voidwalker_body", "body_0_10849430867501589620"],
            ["body", "head", "hair", "gear"],
        ) == "hair"
        assert naming.guess_bodypart(
            ["wraith_lgnd_v19_voidwalker_body", "body_0_8533931396491904913"],
            ["body", "gear", "head"],
        ) == "gear"
        assert naming.preferred_skin_prefix(
            "wraith_lgnd_v19_voidwalker",
            "pilot_light_wraith_cyber_ninja_LOD0.cast",
        ) == "wraith_lgnd_v19_voidwalker"
        void_files = [
            "wraith_base_body_col.png",
            "wraith_base_hair_col.png",
            "wraith_lgnd_v19_voidwalker_body_col.png",
            "wraith_lgnd_v19_voidwalker_helmet_col.png",
            "wraith_lgnd_v19_voidwalker_hair_col.png",
            "wraith_lgnd_v19_voidwalker_gear_col.png",
        ]
        assert naming.prefixes_for_legend_codename(
            "pilot_light_wraith_cyber_ninja", void_files
        ) == ["wraith_lgnd_v19_voidwalker"]
        assert naming.prefixes_for_legend_codename(
            "pilot_light_wraith_cyber_ninja",
            void_files + ["wraith_lgnd_v20_other_body_col.png"],
        ) == []
        assert naming.prefer_non_base_sets(
            ["wraith_base", "wraith_lgnd_v19_voidwalker"],
            "body_0_10849430867501589620",
        ) == ["wraith_lgnd_v19_voidwalker", "wraith_base"]
        assert naming.guess_bodypart(
            ["body_0_9444831493659426347"],
            ["body", "head"],
        ) == "head"
        assert naming.guess_bodypart(
            ["body_0_10849430867501589620"],
            ["hair", "body"],
        ) == "hair"
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v19_voidwalker_helmet"],
            ["body", "head", "gear"],
        ) == "head"
        assert naming.guess_bodypart(
            [
                "body_0_wraith_lgnd_v19_voidwalker_body",
                "body_0_wraith_lgnd_v19_voidwalker_helmet",
            ],
            ["body", "head", "helmet", "gear"],
        ) == "helmet"
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v24_proyoungbpelite_suit"],
            ["body", "gear"],
        ) == "gear"
        assert naming.fallback_bodypart(
            "body_0_wraith_lgnd_v23_resdopb_suit",
            ["body", "gauntlet", "hair02", "head"],
        ) == "suit"
        assert naming.fallback_bodypart(
            "body_0_8533931396491904913",
            ["body", "head", "hair"],
        ) is None
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v24_proyoungbpelite_stubinahair"],
            ["hair02", "body"],
        ) == "hair02"
        assert naming.texture_set_prefix(
            "wraith_lgnd_v24_cosmicmerc_stubinhair_col.png"
        ) == "wraith_lgnd_v24_cosmicmerc"
        assert naming.texture_set_prefix(
            "wraith_lgnd_v24_proyoungbpelite_stubinahair_col.png"
        ) == "wraith_lgnd_v24_proyoungbpelite"
        stub = naming.parse_texture_name(
            "wraith_lgnd_v24_cosmicmerc_stubinhair_col.png",
            "wraith_lgnd_v24_cosmicmerc",
        )
        assert stub is not None and stub.bodypart == "stubinhair" and stub.slot == "albedo"
        assert naming.skin_prefix(
            "body_0_wraith_lgnd_v24_cosmicmerc_stubinhair"
        ) == "wraith_lgnd_v24_cosmicmerc"
        assert naming.parse_skin_identity(
            "wraith_lgnd_v24_cosmicmerc_stubinhair_col.png"
        ).skin == "cosmicmerc"
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v24_cosmicmerc_stubinhair"],
            ["stubinhair", "hair", "body", "head"],
        ) == "stubinhair"
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v24_cosmicmerc_stubinhair"],
            ["hair02", "body"],
        ) == "hair02"
        hair_col = naming.parse_texture_name(
            "wraith_lgnd_v24_cosmicmerc_hair_col.png",
            "wraith_lgnd_v24_cosmicmerc",
        )
        stub_nml = naming.parse_texture_name(
            "wraith_lgnd_v24_cosmicmerc_stubinhair_nml.png",
            "wraith_lgnd_v24_cosmicmerc",
        )
        picked = naming.prefer_textures([stub, hair_col, stub_nml], "stubinhair")
        by_slot = {tex.slot: tex.bodypart for tex in picked}
        assert by_slot.get("albedo") == "stubinhair", by_slot
        assert by_slot.get("normal") == "stubinhair", by_slot
        assert naming.base_hair02_to_hide(
            [
                "body_0_wraith_base_hair02",
                "body_0_wraith_lgnd_v24_cosmicmerc_hair02",
                "body_0_10849430867501589620",
            ]
        ) == ["body_0_wraith_base_hair02"]
        assert naming.base_hair02_to_hide(["body_0_wraith_base_hair02"]) == []
        assert naming.base_hair02_to_hide(
            [
                "body_0_wraith_lgnd_v24_cosmicmerc_hair02",
                "body_0_10849430867501589620",
            ]
        ) == []
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v24_proyoungbpelite_lens"],
            ["gear", "body", "lens"],
        ) == "lens"
        assert naming.related_bodyparts("lens", ["gear", "lens", "kit"]) == ["lens"]
        assert naming.texture_set_prefix(
            "wraith_lgnd_v24_proyoungbpelite_vfx_scarf_col.png"
        ) == "wraith_lgnd_v24_proyoungbpelite"
        scarf = naming.parse_texture_name(
            "wraith_lgnd_v24_proyoungbpelite_vfx_scarf_albedoTexture.png",
            "wraith_lgnd_v24_proyoungbpelite",
        )
        assert scarf is not None and scarf.bodypart == "vfx_scarf" and scarf.slot == "albedo"
        plain_vfx = naming.parse_texture_name(
            "wraith_lgnd_v24_proyoungbpelite_vfx_col.png",
            "wraith_lgnd_v24_proyoungbpelite",
        )
        assert plain_vfx is not None and plain_vfx.bodypart == "vfx" and plain_vfx.slot == "albedo"
        assert naming.guess_bodypart(
            ["body_0_wraith_lgnd_v24_proyoungbpelite_vfx_scarf"],
            ["vfx", "vfx_scarf", "body"],
        ) == "vfx_scarf"
        assert naming.dominant_mesh_prefix(
            [
                "body_0_8533931396491904913",
                "body_0_wraith_lgnd_v19_voidwalker_helmet",
                "body_0_wraith_base_hair",
            ]
        ) == "wraith_lgnd_v19_voidwalker"
        numbered = naming.mesh_texture_prefixes(
            "pilot_light_wraith_cyber_ninja_LOD0",
            "body_0_8533931396491904913",
            ["wraith_lgnd_v19_voidwalker"],
            "wraith_lgnd_v19_voidwalker",
        )
        assert numbered[0] == "wraith_lgnd_v19_voidwalker"
        assert naming.candidate_matches_mesh(
            "body_0_8533931396491904913",
            numbered[0],
        )
        assert naming.mesh_requests_head("head_0_pathfinder_lgnd_v24_prowear")
        assert naming.detect_target_level(
            "octane_lgnd_v22_thrillseeker",
            ["octane_mythic_v22_thrillseeker_body_col_level03.png"],
        ) == ""
        assert naming.variant_priority("level03", "") < 0
        assert naming.skin_prefix("body_0_octane_lgnd_v22_thrillseeker_body_upper") == (
            "octane_lgnd_v22_thrillseeker"
        )
        assert naming.texture_set_prefix(
            "octane_lgnd_v22_thrillseeker_body_lower_col.png"
        ) == "octane_lgnd_v22_thrillseeker"
        assert naming.guess_bodypart(
            ["body_0_octane_lgnd_v22_thrillseeker_body_upper"],
            ["body", "gear"],
        ) == "body"
        assert naming.guess_bodypart(
            ["body_0_octane_lgnd_v22_thrillseeker_body_lower"],
            ["body_lower", "body"],
        ) == "body_lower"
        arenas = naming.season_prefix_aliases(
            "pathfinder_v21_arenas",
            ["body_0_pathfinder_lgnd_v21_thrillseeker_body"],
        )
        assert arenas[0] == "pathfinder_lgnd_v21_thrillseeker"
        assert all("mythic" not in item for item in naming.season_prefix_aliases("pathfinder_v20_bp"))
        assert all("mythic" not in item for item in naming.season_prefix_aliases("pathfinder_v20_death"))
        assert naming.prefixes_for_short_season(
            "pathfinder_v21_arenas_w_LOD0",
            [
                "pathfinder_lgnd_v21_thrillseeker_body_col.png",
                "pathfinder_mythic_v21_thrillseeker_body_col.png",
                "pathfinder_lgnd_v20_detective_body_col.png",
            ],
            ["body_0_pathfinder_lgnd_v21_thrillseeker_body"],
        ) == ["pathfinder_lgnd_v21_thrillseeker"]
        bp_order = naming.mesh_texture_prefixes(
            "pathfinder_v20_bp",
            "body_0_pathfinder_v20_bp_body",
            ["pathfinder_mythic_v20_bp", "pathfinder_lgnd_v20_boosted"],
            "pathfinder_lgnd_v20_boosted",
        )
        assert bp_order[0] == "pathfinder_lgnd_v20_boosted"
        assert "pathfinder_mythic_v20_bp" not in bp_order
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exported_files" / "mdl" / "humans" / "class" / "heavy").mkdir(parents=True)
            (root / "exported_files" / "mdl" / "techart" / "mshop" / "characters" / "legends").mkdir(parents=True)
            seed = root / "exported_files" / "mdl" / "humans" / "class" / "heavy" / "pilot_heavy_pathfinder_w_LOD0.cast"
            seed.write_text("", encoding="utf-8")
            hit = naming.suggest_rsx_model_dir([seed])
            assert hit.replace("\\", "/").endswith("exported_files/mdl"), hit
            skin = root / "skin"
            wide = root / "legendary"
            other = wide / "v20_other"
            mine = wide / "v19_voidwalker"
            skin.mkdir()
            other.mkdir(parents=True)
            mine.mkdir(parents=True)
            (skin / "wraith_lgnd_v19_voidwalker_body_col.png").write_bytes(b"")
            (other / "wraith_lgnd_v20_other_body_col.png").write_bytes(b"")
            (mine / "wraith_lgnd_v19_voidwalker_body_col.png").write_bytes(b"")
            naming.push_texture_cache()
            try:
                listed = naming.list_texture_files(skin)
                assert len(listed) == 1, listed
                again = naming.list_texture_files(skin)
                assert again == listed
                focused = naming.list_texture_files(wide, ("voidwalker",))
                assert len(focused) == 1 and "voidwalker" in focused[0].name, focused
            finally:
                naming.pop_texture_cache()
        legend, rarity, label = naming.character_bucket("pilot_heavy_pathfinder_legendary_01")
        assert (legend, rarity) == ("Pathfinder", "Legendary"), (legend, rarity, label)
        legend, rarity, _label = naming.character_bucket("pilot_light_wattson")
        assert (legend, rarity) == ("Wattson", "Original"), (legend, rarity)
        legend, rarity, skin = naming.character_bucket("heavy_pathfinder_lgnd_v20_boosted_w_LOD0")
        assert legend == "Pathfinder" and rarity == "Legendary" and skin == "boosted", (legend, rarity, skin)
        legend, rarity, skin = naming.character_bucket("pathfinder_lgnd_v21_thrillseeker")
        assert legend == "Pathfinder" and skin == "thrillseeker", (legend, rarity, skin)
        v24 = ["pathfinder_lgnd_v24_onesieelite", "pathfinder_lgnd_v24_prowear"]
        assert naming.mesh_texture_prefixes(
            "pathfinder_lgnd_v24_prowear",
            "body_0_pathfinder_lgnd_v24_prowear_emotes",
            v24,
        )[0] == "pathfinder_lgnd_v24_prowear"
        sets = [
            "pathfinder_lgnd_v19_pacer",
            "pathfinder_lgnd_v22_magicgoth",
            "pathfinder_lgnd_v20_boosted",
        ]
        assert naming.mesh_texture_prefixes(
            "pilot_heavy_pathfinder_legendary_01",
            "body_0_pathfinder_lgnd_v22_magicgoth_body",
            sets,
            discovered="pathfinder_lgnd_v19_pacer",
        )[0] == "pathfinder_lgnd_v22_magicgoth"
        assert naming.mesh_texture_prefixes(
            "pilot_heavy_pathfinder_legendary_01",
            "body_0_pathfinder_lgnd_v19_pacer_gear",
            sets,
            discovered="pathfinder_lgnd_v19_pacer",
        )[0] == "pathfinder_lgnd_v19_pacer"
        assert naming.mesh_texture_prefixes(
            "pathfinder_v20_bp",
            "body_0_pathfinder_lgnd_v20_boosted_body",
            sets,
        )[0] == "pathfinder_lgnd_v20_boosted"
        boosted = naming.scan_folder(folder, "pathfinder_lgnd_v20_boosted")
        assert boosted.bodyparts() == [], boosted.bodyparts()
        (folder / "pathfinder_lgnd_v20_boosted_body_col.png").write_bytes(b"x")
        (folder / "pathfinder_lgnd_v20_boosted_body_ao.png").write_bytes(b"x")
        short = naming.scan_folder(folder, "pathfinder_v20_bp")
        long = naming.scan_folder(folder, naming.skin_prefix("body_0_pathfinder_lgnd_v20_boosted_body"))
        assert short.bodyparts() == [], short.bodyparts()
        assert long.bodyparts() == ["body"], long.bodyparts()


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
    assert [row[0] for row in anim._layout_pin_channels((2.0, 3.0, 4.0))] == [
        "scale",
        "scale",
        "scale",
    ]

    class _LocCurve:
        def __init__(self, path):
            self.data_path = path

    class _LocCurves(list):
        def remove(self, curve):
            list.remove(self, curve)

    class _LocAction:
        def __init__(self):
            self.fcurves = _LocCurves(
                [
                    _LocCurve("location"),
                    _LocCurve("delta_location"),
                    _LocCurve("scale"),
                    _LocCurve('pose.bones["def_c_hips"].location'),
                ]
            )
            self.layers = []
            self.slots = []
            self.props = {}

        def get(self, key, default=None):
            return self.props.get(key, default)

        def __setitem__(self, key, value):
            self.props[key] = value

    loc_action = _LocAction()
    loc_obj = types.SimpleNamespace(animation_data=types.SimpleNamespace(action=loc_action))
    anim._strip_location_keys(loc_obj)
    loc_paths = [curve.data_path for curve in loc_action.fcurves]
    assert loc_paths == ["scale", 'pose.bones["def_c_hips"].location'], loc_paths
    assert loc_action.get("apex_loc_free") is True

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
    assert hasattr(naming, "is_eye_material")
    assert hasattr(naming, "is_glass_family")
    assert hasattr(naming, "is_transparent_family")
    assert hasattr(naming, "scan_object_folder")
    assert hasattr(naming, "techart_legend_texture_candidates")
    assert hasattr(naming, "parse_object_texture_name")
    assert hasattr(anim, "resolve_shade_objects")
    assert hasattr(anim, "apply_light_boost")
    assert hasattr(anim, "sync_closeup_dof")
    assert hasattr(anim, "apply_camera_preset")
    from apex_auto_shader.node_adder import SHADER_ADDERS
    from apex_auto_shader.blender_compat import material_meshes, resolve_armature

    assert "cinematic" in SHADER_ADDERS
    assert callable(material_meshes) and callable(resolve_armature)

    _test_object_and_techart()
    _test_cosmetics_and_index()

    assert (PKG_DIR / "asset" / "wraith" / "ncache.bin").is_file()
    assert (PKG_DIR / "asset" / "Apex Shader.blend").is_file() or (
        PKG_DIR / "asset" / "Apex_Shader_Plus1.blend"
    ).is_file()
    assert not (ROOT / "skins.json").exists(), "plaintext skins.json must not exist"
    assert not (PKG_DIR / "skins.json").exists(), "plaintext skins.json must not exist"

    ver = apex_auto_shader.bl_info["version"]
    assert ver == (2, 2, 0), ver
    from apex_auto_shader import config

    assert config.ADDON_VERSION == ver
    assert config.ADDON_VERSION_STR == "2.2.0"
    manifest = (PKG_DIR / "blender_manifest.toml").read_text(encoding="utf-8")
    found = re.search(r'(?m)^version\s*=\s*"([^"]+)"', manifest)
    assert found and found.group(1) == "2.2.0", manifest
    panel_src = (PKG_DIR / "panel.py").read_text(encoding="utf-8")
    assert "apexaddon.uninstall" not in panel_src
    from apex_auto_shader.install import other_copies
    from apex_auto_shader.menu import classes as menu_classes

    menu_ids = {getattr(cls, "bl_idname", "") for cls in menu_classes}
    assert "apexaddon.install_zip" in menu_ids
    assert "apexaddon.uninstall" in menu_ids
    assert "apexaddon.drop_old_copy" in menu_ids
    here = Path("/tmp/aas-current")
    old = Path("/tmp/aas-old")
    here.mkdir(exist_ok=True)
    old.mkdir(exist_ok=True)
    dupes = other_copies(
        [{"path": str(here), "version": "2.1.0"}, {"path": str(old), "version": "2.0.1"}],
        current=here,
    )
    assert len(dupes) == 1 and dupes[0]["version"] == "2.0.1"

    from apex_auto_shader.prefs import (
        ApexAutoShaderPreferences,
        anim_folder_pref,
        model_folder_pref,
        path_is_under,
    )
    from apex_auto_shader.anim.character import limit_to_model_folder
    from apex_auto_shader import panel as apex_panel
    from apex_auto_shader.shade.utils import hide_rig, rig_is_hidden, set_rig_hidden, show_rig

    anns = ApexAutoShaderPreferences.__annotations__
    assert "model_dir" in anns and "anim_dir" in anns
    assert "post_shade_hide_rig" in anns
    assert path_is_under("/tmp/aas-models/skin/a.cast", "/tmp/aas-models")
    assert path_is_under("/tmp/aas-models", "/tmp/aas-models")
    assert not path_is_under("/tmp/aas-anims/clip.cast", "/tmp/aas-models")
    sample = [Path("/tmp/aas-models/skin/a.cast")]
    assert model_folder_pref() is None and anim_folder_pref() is None
    assert limit_to_model_folder(sample) == sample
    assert callable(show_rig) and callable(set_rig_hidden) and callable(rig_is_hidden)
    assert callable(hide_rig)
    assert hasattr(apex_panel, "APEX_OT_toggle_bones")
    assert "APEX_OT_toggle_bones" in {cls.__name__ for cls in apex_panel.panel_classes}
    assert "Only the Animation folder" not in panel_src
    assert "Limited to the Model folder" not in panel_src

    import tempfile

    from apex_auto_shader.anim import files as anim_files
    from apex_auto_shader.naming import legend_from_anim_path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "2_Animation"
        alter = root / "Alter" / "pilot"
        newc = root / "Newcastle" / "pilot_heavy_newcastle"
        inner = newc / "anims_pilot_heavy_newcastle"
        maggie = root / "Mad Maggie"
        dummy = root / "Dummy"
        for folder in (alter, inner, maggie, dummy):
            folder.mkdir(parents=True)
        for i in range(4):
            (alter / f"AIM_alter_idle_{i}.cast").write_bytes(b"x" * 300)
        (newc / "AIM_newcastle_crouch_pistol_0.cast").write_bytes(b"x" * 300)
        (inner / "newcastle_emote_dance.cast").write_bytes(b"x" * 300)
        (maggie / "foo_bar.cast").write_bytes(b"x" * 300)
        (dummy / "idle_wait.cast").write_bytes(b"x" * 300)
        old_cap = anim_files._PER_DIR_CAP
        anim_files._PER_DIR_CAP = 1
        try:
            found = dict(anim_files.list_animation_files(root))
        finally:
            anim_files._PER_DIR_CAP = old_cap
        assert "AIM_newcastle_crouch_pistol_0" in found
        assert "newcastle_emote_dance" in found
        assert "foo_bar" in found
        assert "idle_wait" in found
        assert len([name for name in found if name.startswith("AIM_alter_idle_")]) == 1
        assert legend_from_anim_path(inner / "newcastle_emote_dance.cast", root) == "newcastle"
        assert legend_from_anim_path(maggie / "foo_bar.cast", root) == "madmaggie"
        assert legend_from_anim_path(dummy / "idle_wait.cast", root) == ""
        jump = root / "Jump"
        jump.mkdir()
        assert legend_from_anim_path(jump / "idle_wait.cast", root) == ""
        picked = anim_files.picked_anim_dirs(str(root), ["Newcastle", "Alter"], lambda text: text)
        assert {path.name for path in picked} == {"Newcastle", "Alter"}
        assert anim_files.picked_anim_dirs(str(root), [], lambda text: text) == [root]

    warm = anim.kelvin_to_rgb(2700)
    white = anim.kelvin_to_rgb(6500)
    assert warm[0] > warm[2], warm
    assert min(white) > 0.85, white
    assert hasattr(anim, "apply_light_kelvin") and hasattr(anim, "apply_composition_guides")

    from apex_auto_shader import pack as skin_pack

    casts = [
        "/m/wraith_lgnd_v19_voidwalker_w_LOD0.cast",
        "/m/wraith_base_w_LOD0.cast",
        "/m/bloodhound_base_w_LOD0.cast",
        "/m/pilot_light_wraith_base_w_LOD0.cast",
    ]
    corrupted = skin_pack.rank_cast_for_prefix("wraith_epicp_v23_voidsinister", casts)
    assert corrupted == "", corrupted
    no_lod = skin_pack.rank_cast_for_prefix(
        "wraith_epicp_v23_voidsinister",
        ["/m/wraith_epic_v23_voidsinister.cast"],
    )
    assert no_lod.endswith("wraith_epic_v23_voidsinister.cast"), no_lod
    airship = skin_pack.files_present_indexed(
        (),
        (),
        ("wraith_airship_assassin",),
        "wraith_lgnd_v19_quarantine_rt02",
        "Airship Assassin",
        "Wraith",
    )
    assert airship, "airship name on disk"
    assert skin_pack.files_present_indexed(
        ("wraith_v20_heist",),
        (),
        (),
        "wraith_v20_heist",
        "Hellcat",
        "Wraith",
    )
    assert skin_pack.files_present_indexed(
        ("wraith_v20_heist",),
        (),
        (),
        "wraith_v20_heist",
        "Void Prowler",
        "Wraith",
    )
    assert not skin_pack.files_present_indexed(
        ("wraith_lgnd_v19_quarantine",),
        (),
        ("wraith_lgnd_v19_quarantine_body_col",),
        "wraith_lgnd_v19_quarantine_rt02",
        "Airship Assassin",
        "Wraith",
    )
    depths = skin_pack.rank_cast_for_prefix("wraith_lgnd_v19_quarantine_rc01", casts[:2])
    assert depths == "", depths
    void_rc = skin_pack.rank_cast_for_prefix("wraith_lgnd_v19_voidwalker_rc01", casts)
    assert void_rc.endswith("voidwalker_w_LOD0.cast"), void_rc
    own = skin_pack.rank_cast_for_prefix(
        "wraith_epicp_v23_voidsinister",
        casts + ["/m/wraith_epicp_v23_voidsinister_w_LOD0.cast"],
    )
    assert own.endswith("voidsinister_w_LOD0.cast"), own
    pilot = skin_pack.rank_cast_for_prefix(
        "wraith_epicp_v23_voidsinister",
        ["/m/pilot_light_wraith_base_w_LOD0.cast"],
    )
    assert pilot == "", pilot
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        export = Path(tmp) / "exported_files"
        mats = export / "materials" / "noise"
        klass = export / "mdl" / "humans" / "class" / "light"
        legends = export / "mdl" / "techart" / "mshop" / "characters" / "legends" / "wraith"
        mats.mkdir(parents=True)
        klass.mkdir(parents=True)
        legends.mkdir(parents=True)
        for i in range(40):
            (mats / f"noise_{i}.png").write_bytes(b"x")
        (mats / "extra_weapon_w_LOD0.cast").write_bytes(b"x")
        (klass / "wraith_v20_heist_w_LOD0.cast").write_bytes(b"x")
        (legends / "wraith_lgnd_v21_shop_w_LOD0.cast").write_bytes(b"x")
        found_casts, _blobs, _tex, _cut, paths = skin_pack.walk_model_index(export, limit=8)
        assert "wraith_v20_heist" in found_casts, found_casts
        assert "extra_weapon" in found_casts, found_casts
        assert "wraith_lgnd_v21_shop" in found_casts, found_casts
        assert any(path.endswith("wraith_v20_heist_w_LOD0.cast") for path in paths)
    assert skin_pack.prefix_for("Wraith", "Void Prowler") == "wraith_v20_heist"
    assert skin_pack.prefix_for("Wraith", "Hellcat") == "wraith_v20_heist"
    assert skin_pack.prefix_for("Wraith", "Punk Prowler") == "wraith_lgnd_v20_heist_rt02"
    assert skin_pack.prefix_for("Wraith", "Nanite Skirmisher") == "wraith_lgnd_v26_evocon"
    assert skin_pack.files_present_indexed(
        ("wraith_v20_heist",),
        (),
        (),
        "wraith_lgnd_v20_boosted",
        "Void Prowler",
        "Wraith",
    )
    assert not skin_pack.files_present_indexed(
        ("wraith_v20_heist",),
        (),
        (),
        "wraith_lgnd_v20_boosted_rt01",
        "Hellcat",
        "Wraith",
    )
    assert skin_pack.files_present_indexed(
        (),
        (),
        ("wraith_lgnd_v20_boosted_rt01_body_col",),
        "wraith_lgnd_v20_boosted_rt01",
        "Hellcat",
        "Wraith",
    )
    heist = skin_pack.rank_cast_for_prefix(
        "wraith_lgnd_v20_boosted_rt01",
        ["/m/light/wraith_v20_heist_w_LOD0.cast"],
    )
    assert heist.endswith("wraith_v20_heist_w_LOD0.cast"), heist
    from apex_auto_shader.naming.tex import cycle_recolor_code, scan_recolor_stack

    assert cycle_recolor_code(["rt01", "rt02"], "") == "rt01"
    assert cycle_recolor_code(["rt01", "rt02"], "rt01") == "rt02"
    assert cycle_recolor_code(["rt01", "rt02"], "rt02") == ""

    with tempfile.TemporaryDirectory() as tmp2:
        base = Path(tmp2) / "exported_files"
        wrong = base / "mdl" / "techart" / "mshop" / "characters" / "legends" / "wraith"
        art = base / "texture" / "art" / "mshop" / "characters" / "legends" / "wraith"
        wrong.mkdir(parents=True)
        art.mkdir(parents=True)
        (art / "wraith_lgnd_v20_boosted_rt01_body_col.png").write_bytes(b"recolor")
        match = scan_recolor_stack(
            wrong, "wraith_lgnd_v20_boosted", apply_recolor=True, recolor_code="rt01"
        )
        albedo = [tex.path for tex in match.textures if tex.slot == "albedo"]
        assert albedo and "boosted_rt01" in albedo[0].replace("\\", "/"), albedo

    print("smoke_import: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke_import: FAIL: {exc}", file=sys.stderr)
        raise
