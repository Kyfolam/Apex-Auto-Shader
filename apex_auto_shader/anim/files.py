from __future__ import annotations

import os
from pathlib import Path

from .const import ANIM_MIN_BYTES, ANIM_PLAY_MIN_BYTES, ANIM_SUFFIXES


_IGNORED_CLIPS = frozenset({"radoll_0", "ref_0"})
_SKIP_DIRS = {"__pycache__", ".git", ".svn", ".hg"}
# One directory full of AIM clips must not hide sibling folders.
_PER_DIR_CAP = 30000


def is_ignored_clip(name: str) -> bool:
    """Ragdoll and bind-pose clips are never listed or loaded."""
    stem = Path(str(name or "")).stem.lower()
    if not stem or stem in _IGNORED_CLIPS:
        return stem in _IGNORED_CLIPS
    if stem.endswith("_radoll_0") or stem.endswith("_ref_0"):
        return True
    return "radoll" in stem.split("_")


def _hidden(*parts) -> bool:
    """True when a path or clip name matches a packed Unlisted token."""
    try:
        from ..pack import is_unreleased
        return is_unreleased(*parts)
    except Exception:
        return False


def _keep_anim(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in ANIM_SUFFIXES:
        return False
    # Match the clip, not the whole Windows path. A parent like
    # "1_Apex Blender" must not hide every file under it.
    if _hidden(path.stem, path.parent.name):
        return False
    if is_ignored_clip(path.stem):
        return False
    try:
        if path.stat().st_size < ANIM_MIN_BYTES:
            return False
    except OSError:
        return False
    return True


def clip_should_autoplay(path: str | Path) -> bool:
    """False for clips under 200KB. They stay in the list, but do not start playing."""
    try:
        return Path(path).stat().st_size >= ANIM_PLAY_MIN_BYTES
    except OSError:
        return True


def list_animation_files(folder: str | Path) -> list[tuple[str, str]]:
    """Every .cast under folder, including nested legend folders.

    Walks each directory on its own. A global sorted scan used to fill the
    cap with the first legend (or the loose AIM files) and never reach the
    later folders or ``anims_*`` subfolders.
    """
    root = Path(folder)
    if not root.is_dir():
        return []
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            (name for name in dirnames if not name.startswith(".") and name not in _SKIP_DIRS),
            key=str.lower,
        )
        added = 0
        for name in sorted(filenames, key=str.lower):
            path = Path(dirpath) / name
            if not _keep_anim(path):
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            items.append((path.stem, key))
            added += 1
            if added >= _PER_DIR_CAP:
                break
    return items


def picked_anim_dirs(directory: str, names: list[str], abspath) -> list[Path]:
    """Folders the file browser actually selected.

    Blender often leaves ``directory`` as the parent and puts the highlighted
    folder in ``files``. Scanning only ``directory`` then misses the folder
    the user clicked, or scans one level too high.
    """
    text = directory or ""
    root = None
    if text:
        try:
            root = Path(abspath(text))
        except Exception:
            root = Path(text)
    picked: list[Path] = []
    for name in names:
        if not name or name in {".", ".."}:
            continue
        path = (root / name) if root is not None else Path(name)
        if path.is_dir():
            picked.append(path)
    if picked:
        return picked
    if root is not None and root.is_dir():
        return [root]
    return []
