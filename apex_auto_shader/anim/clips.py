from __future__ import annotations

from pathlib import Path

from .const import ANIM_LIST_CAP, ANIM_MIN_BYTES, ANIM_SUFFIXES
from ..blender_compat import ignore_rna
from ..log import existing_dir, log
from ..naming import (
    ANIM_GROUP_ORDER,
    bannerpose_display_name,
    classify_animation,
    emote_display_name,
    emote_subtype,
    find_class_root,
    find_legend_anim_dir,
    finisher_display_name,
    guess_legend_from_anim,
    guess_legend_from_path,
    is_victim_execution,
    legend_display_name,
    parse_execution,
    pick_banner_list_clips,
    skip_bannerpose,
    strip_unique_trailing_index,
)

from .files import _hidden, list_animation_files


def _scan_execution_casts(root: Path) -> list[tuple[str, str]]:
    if root is None or not root.is_dir():
        return []
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".cast":
            continue
        try:
            if path.stat().st_size < ANIM_MIN_BYTES:
                continue
        except OSError:
            continue
        if "execution" not in path.stem.lower() and "finish" not in path.stem.lower():
            continue
        if _hidden(path, path.stem, path.parent.name):
            continue
        found.append((path.stem, str(path)))
    return found


def _pair_finishers(found: list[tuple[str, str]], folder: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    extra = []
    class_root = find_class_root(folder)
    if class_root is not None:
        extra = _scan_execution_casts(class_root)
    pool = list(found) + extra
    attacks: dict[tuple[str, str], tuple[str, str]] = {}
    victims: dict[tuple[str, str], tuple[str, str]] = {}
    for name, path in pool:
        info = parse_execution(name)
        if info is None:
            if classify_animation(name) == "finisher" and not is_victim_execution(name):
                legend = guess_legend_from_anim(name)
                attacks.setdefault((legend, name.lower()), (name, path))
            continue
        key = (info["legend"], info["clip"])
        if info["victim"]:
            victims.setdefault(key, (name, path))
        else:
            attacks.setdefault(key, (name, path))
    solo = []
    seen_solo = set()
    for name, path in found:
        if classify_animation(name) != "finisher":
            continue
        if is_victim_execution(name):
            continue
        if path in seen_solo:
            continue
        seen_solo.add(path)
        solo.append((name, path))
    full = []
    seen_full = set()
    for key in sorted(set(attacks) | set(victims), key=lambda k: (k[0], k[1])):
        atk = attacks.get(key)
        vic = victims.get(key)
        if vic is None and atk is None:
            continue
        attack_path = atk[1] if atk else (vic[1] if vic else "")
        victim_path = vic[1] if vic else ""
        if not victim_path:
            continue
        clip = key[1]
        ident = f"{key[0]}:{clip}:{victim_path}"
        if ident in seen_full:
            continue
        seen_full.add(ident)
        src_name = vic[0] if vic else (atk[0] if atk else "")
        info = parse_execution(src_name) or {}
        display = info.get("clip_raw") or clip or Path(victim_path).stem
        full.append((display, attack_path, victim_path))
    return solo, full


def _add_anim_header(scene, name, group, legend, collapsed, indent):
    header = scene.apex_anim_items.add()
    header.name = name
    header.path = ""
    header.victim_path = ""
    header.is_header = True
    header.is_legend = indent == 0
    header.group = group
    header.legend = legend
    header.collapsed = collapsed
    header.indent = indent
    return header


def _add_anim_clip(scene, name, path, group, legend, indent, victim_path=""):
    item = scene.apex_anim_items.add()
    item.name = name
    item.path = path
    item.victim_path = victim_path
    item.is_header = False
    item.is_legend = False
    item.group = group
    item.legend = legend
    item.collapsed = False
    item.indent = indent
    return item


def _emit_named_clips(scene, clips, group, legend, indent, namer):
    displays = strip_unique_trailing_index([namer(name) for name, _path in clips])
    count = 0
    for (name, path), label in zip(clips, displays):
        _add_anim_clip(scene, label or name, path, group, legend, indent)
        count += 1
    return count


def fill_animation_list(scene, folder: str | Path | None = None, sources=None, expand_legend: str = "") -> int:
    packs: list[tuple[Path, str, list[tuple[str, str]]]] = []
    if sources:
        for raw, hint in sources:
            path = Path(raw)
            if not path.is_dir():
                continue
            packs.append((path, str(hint or ""), list_animation_files(path)))
    elif folder:
        path = Path(folder)
        if path.is_dir():
            hint = guess_legend_from_path(path) or guess_legend_from_anim(path.name)
            packs.append((path, hint, list_animation_files(path)))
    if not packs:
        log.warning("Animation folder missing: %s", folder)
        scene.apex_anim_items.clear()
        return 0

    rows: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    for _folder, hint, files in packs:
        for name, path in files:
            if path in seen_paths:
                continue
            seen_paths.add(path)
            rows.append((name, path, hint))

    def assigned_legend(name: str, hint: str = "") -> str:
        guessed = guess_legend_from_anim(name)
        if guessed:
            return guessed
        return hint or "shared"

    legends: dict[str, dict[str, list]] = {}
    for name, path, hint in rows:
        kind = classify_animation(name)
        if kind == "finisher":
            continue
        if kind == "pose" and skip_bannerpose(name):
            continue
        legend = assigned_legend(name, hint)
        bucket = legends.setdefault(legend, {key: [] for key, _ in ANIM_GROUP_ORDER})
        bucket.setdefault(kind, []).append((name, path))
    for folder_path, hint, files in packs:
        solo, full = _pair_finishers(files, folder_path)
        for name, path in solo:
            legend = assigned_legend(name, hint)
            bucket = legends.setdefault(legend, {key: [] for key, _ in ANIM_GROUP_ORDER})
            bucket.setdefault("finisher_solo", []).append((name, path))
        for clip, attack_path, victim_path in full:
            source = Path(victim_path).stem if victim_path else clip
            info = parse_execution(source)
            legend = info["legend"] if info else assigned_legend(source, hint)
            bucket = legends.setdefault(legend, {key: [] for key, _ in ANIM_GROUP_ORDER})
            bucket.setdefault("finisher_full", []).append((clip, attack_path, victim_path))
    scene.apex_anim_items.clear()
    total = 0
    pose_subs = (("animated", "Animated"), ("static", "Static"), ("capture", "Capture"))
    emote_subs = (("drop", "Drop"), ("ground", "Ground"))
    expand = (expand_legend or "").lower().replace(" ", "")
    multi = (
        sum(1 for groups in legends.values() if any(groups.get(key) for key, _ in ANIM_GROUP_ORDER))
        > 1
    )
    for legend in sorted(legends, key=lambda s: legend_display_name(s).lower()):
        groups = legends[legend]
        nonempty = [key for key, _ in ANIM_GROUP_ORDER if groups.get(key)]
        if not nonempty:
            continue
        legend_key = f"legend:{legend}"
        legend_closed = multi and (not expand or legend != expand)
        _add_anim_header(scene, legend_display_name(legend), legend_key, legend, legend_closed, 0)
        for key, label in ANIM_GROUP_ORDER:
            clips = groups.get(key) or []
            if not clips:
                continue
            type_key = f"{legend}:{key}"
            _add_anim_header(scene, label, type_key, legend, True, 1)
            if key == "pose":
                grouped = pick_banner_list_clips(clips, legend)
                for code, sub_label in pose_subs:
                    sub_clips = grouped.get(code) or []
                    if not sub_clips:
                        continue
                    sub_key = f"{type_key}:{code}"
                    _add_anim_header(scene, sub_label, sub_key, legend, True, 2)
                    total += _emit_named_clips(
                        scene,
                        sub_clips,
                        sub_key,
                        legend,
                        3,
                        lambda n, lg=legend: bannerpose_display_name(n, lg),
                    )
            elif key == "emote":
                leftover = []
                buckets = {code: [] for code, _ in emote_subs}
                for entry in clips:
                    sub = emote_subtype(entry[0])
                    if sub in buckets:
                        buckets[sub].append(entry)
                    else:
                        leftover.append(entry)
                for code, sub_label in emote_subs:
                    sub_clips = buckets[code]
                    if not sub_clips:
                        continue
                    sub_key = f"{type_key}:{code}"
                    _add_anim_header(scene, sub_label, sub_key, legend, True, 2)
                    total += _emit_named_clips(
                        scene,
                        sub_clips,
                        sub_key,
                        legend,
                        3,
                        lambda n, lg=legend: emote_display_name(n, lg),
                    )
                if leftover:
                    total += _emit_named_clips(
                        scene,
                        leftover,
                        type_key,
                        legend,
                        2,
                        lambda n, lg=legend: emote_display_name(n, lg),
                    )
            elif key in {"finisher_solo", "finisher_full"}:
                if key == "finisher_full":
                    names = strip_unique_trailing_index(
                        [finisher_display_name(clip, legend) for clip, _a, _v in clips]
                    )
                    for (clip, attack_path, victim_path), label in zip(clips, names):
                        _add_anim_clip(
                            scene,
                            label or clip,
                            attack_path or victim_path,
                            type_key,
                            legend,
                            2,
                            victim_path,
                        )
                        total += 1
                else:
                    total += _emit_named_clips(
                        scene,
                        clips,
                        type_key,
                        legend,
                        2,
                        lambda n, lg=legend: finisher_display_name(n, lg),
                    )
            else:
                total += _emit_named_clips(
                    scene,
                    clips,
                    type_key,
                    legend,
                    2,
                    lambda n: n,
                )
    scene.apex_anim_index = min(int(getattr(scene, "apex_anim_index", 0) or 0), max(len(scene.apex_anim_items) - 1, 0))
    return total


def _anim_sources_for_scene(context, prefer_cast: str | Path | None = None):
    from ..extras import CHAR_ANIM, CHAR_CAST, CHAR_LEGEND, armature_legend, tagged_armatures
    from ..log import existing_dir

    prefer_legend = ""
    if prefer_cast:
        prefer_legend = guess_legend_from_path(prefer_cast) or guess_legend_from_anim(
            Path(prefer_cast).stem
        )
    arms = list(tagged_armatures(context.scene))
    ordered = []
    if prefer_legend:
        for arm in arms:
            if armature_legend(arm) == prefer_legend or str(arm.get(CHAR_CAST, "")) == str(prefer_cast):
                ordered.append(arm)
        for arm in arms:
            if arm not in ordered:
                ordered.append(arm)
    else:
        ordered = arms
    sources: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for arm in ordered:
        legend = armature_legend(arm)
        stored = arm.get(CHAR_ANIM, "")
        folder = existing_dir(stored) if stored else None
        cast = arm.get(CHAR_CAST, "") or (str(prefer_cast) if prefer_cast else "")
        if folder is None and cast:
            folder = find_legend_anim_dir(cast, legend)
        if folder is None or not folder.is_dir():
            continue
        key = str(folder)
        if key in seen:
            continue
        seen.add(key)
        sources.append((folder, legend))
        try:
            arm[CHAR_ANIM] = str(folder)
            if legend:
                arm[CHAR_LEGEND] = legend
        except (ReferenceError, TypeError):
            pass
    if not sources and prefer_cast:
        folder = find_legend_anim_dir(prefer_cast, prefer_legend)
        if folder is not None and folder.is_dir():
            sources.append((folder, prefer_legend))
    return sources, prefer_legend


def autoload_legend_animations(context, cast_path: str | Path | None) -> int:
    sources, prefer = _anim_sources_for_scene(context, cast_path)
    if not sources:
        log.warning("No animation folder for legend '%s' (%s)", prefer, cast_path)
        return 0
    prefer_folder = sources[0][0]
    try:
        context.scene.apex_anim_dir = str(prefer_folder)
    except (AttributeError, TypeError, RuntimeError) as exc:
        ignore_rna(exc, "autoload anim dir")
    return fill_animation_list(context.scene, sources=sources, expand_legend=prefer)


