from __future__ import annotations

from pathlib import Path

from .const import ANIM_LIST_CAP, ANIM_MIN_BYTES, ANIM_SUFFIXES


def _hidden(*parts) -> bool:
    """True when a path or clip name matches a packed Unlisted token."""
    try:
        from ..pack import is_unreleased
        return is_unreleased(*parts)
    except Exception:
        return False


def list_animation_files(folder: str | Path) -> list[tuple[str, str]]:
    root = Path(folder)
    if not root.is_dir():
        return []
    items: list[tuple[str, str]] = []
    seen = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ANIM_SUFFIXES:
            continue
        if _hidden(path, path.stem, path.parent.name):
            continue
        try:
            if path.stat().st_size < ANIM_MIN_BYTES:
                continue
        except OSError:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        items.append((path.stem, key))
        if len(items) >= ANIM_LIST_CAP:
            break
    return items
