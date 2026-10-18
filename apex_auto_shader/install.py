"""Replace an existing install only after the user confirms."""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty

PKG_ID = "apex_auto_shader"
ADDON_NAME = "Apex Auto Shader"

_ASKED = False


def current_dir() -> Path:
    return Path(__file__).resolve().parent


def _version_of(pkg_dir: Path) -> str:
    manifest = pkg_dir / "blender_manifest.toml"
    if manifest.is_file():
        text = manifest.read_text(encoding="utf-8", errors="replace")
        found = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
        if found:
            return found.group(1)
    init = pkg_dir / "__init__.py"
    if init.is_file():
        text = init.read_text(encoding="utf-8", errors="replace")
        found = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', text)
        if found:
            return ".".join(found.groups())
    return ""


def read_zip_manifest(filepath: str) -> dict | None:
    if not filepath:
        return None
    try:
        path = Path(bpy.path.abspath(filepath))
    except Exception:
        path = Path(filepath)
    if not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith("blender_manifest.toml")]
            if not names:
                return None
            names.sort(key=lambda n: (n.count("/"), len(n)))
            raw = zf.read(names[0]).decode("utf-8", errors="replace")
    except Exception:
        return None
    pkg = re.search(r'(?m)^id\s*=\s*"([^"]+)"', raw)
    ver = re.search(r'(?m)^version\s*=\s*"([^"]+)"', raw)
    if not pkg:
        return None
    return {"id": pkg.group(1), "version": ver.group(1) if ver else ""}


def find_installs(pkg_id: str = PKG_ID) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, pkg_dir: Path, repo: str, module: str) -> None:
        if not pkg_dir.is_dir():
            return
        try:
            key = str(pkg_dir.resolve())
        except Exception:
            key = str(pkg_dir)
        if key in seen:
            return
        seen.add(key)
        found.append(
            {
                "kind": kind,
                "repo": repo,
                "path": key,
                "version": _version_of(pkg_dir),
                "module": module,
            }
        )

    prefs = getattr(bpy.context, "preferences", None)
    repos = getattr(getattr(prefs, "extensions", None), "repos", None) or []
    for repo in repos:
        directory = getattr(repo, "directory", "") or ""
        if not directory:
            continue
        repo_id = getattr(repo, "module", "") or "user_default"
        add("extension", Path(directory) / pkg_id, repo_id, f"{repo_id}.{pkg_id}")
    try:
        import addon_utils

        folders = list(addon_utils.paths())
    except Exception:
        folders = []
    for folder in folders:
        add("legacy", Path(folder) / pkg_id, "", pkg_id)
    return found


def other_copies(installs: list[dict] | None = None, current: Path | None = None) -> list[dict]:
    here = (current or current_dir()).resolve()
    rows = installs if installs is not None else find_installs()
    out = []
    for item in rows:
        try:
            path = Path(item["path"]).resolve()
        except Exception:
            continue
        if path != here:
            out.append(item)
    return out


def _remove(item: dict, *, allow_current: bool) -> None:
    path = Path(item["path"]).resolve()
    here = current_dir().resolve()
    if path == here and not allow_current:
        return
    if item.get("kind") == "extension":
        try:
            bpy.ops.extensions.package_uninstall(
                repo=item.get("repo") or "user_default",
                pkg_id=PKG_ID,
            )
        except Exception:
            pass
        if allow_current and path.is_dir() and path != here:
            shutil.rmtree(path, ignore_errors=True)
        elif path != here and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        return
    module = item.get("module") or PKG_ID
    if module != (__package__ or PKG_ID):
        try:
            bpy.ops.preferences.addon_disable(module=module)
        except Exception:
            pass
        try:
            bpy.ops.preferences.addon_remove(module=module)
        except Exception:
            pass
    if path.is_dir() and (allow_current or path != here):
        shutil.rmtree(path, ignore_errors=True)


def _install_files(filepath: str) -> None:
    path = str(Path(bpy.path.abspath(filepath)))
    kwargs = {"filepath": path, "repo": "user_default", "enable_on_install": True}
    try:
        rna = bpy.ops.extensions.package_install_files.get_rna_type()
        names = {prop.identifier for prop in rna.properties}
    except Exception:
        names = set()
    if "overwrite" in names:
        kwargs["overwrite"] = True
    bpy.ops.extensions.package_install_files(**kwargs)


def replace_with_zip(filepath: str) -> None:
    for item in find_installs():
        _remove(item, allow_current=True)
    _install_files(filepath)


def schedule_existing_check() -> None:
    def _poke():
        global _ASKED
        if _ASKED:
            return None
        if not other_copies():
            return None
        _ASKED = True
        try:
            bpy.ops.apexaddon.drop_old_copy("INVOKE_DEFAULT")
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_poke, first_interval=1.0)
    except Exception:
        pass


class APEX_OT_drop_old_copy(bpy.types.Operator):
    bl_idname = "apexaddon.drop_old_copy"
    bl_label = "Bereits installiert"
    bl_description = "Entfernt eine zweite Kopie von Apex Auto Shader"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        self._others = other_copies()
        if not self._others:
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text=f"{ADDON_NAME} ist bereits installiert.", icon="ERROR")
        for item in other_copies():
            ver = item.get("version") or "?"
            col.label(text=f"Alte Kopie {ver}")
        col.separator()
        col.label(text="Alte Kopie entfernen und diese Version behalten?")

    def execute(self, context):
        removed = 0
        for item in other_copies():
            _remove(item, allow_current=False)
            removed += 1
        self.report({"INFO"}, f"{removed} alte Installation entfernt")
        return {"FINISHED"}


class APEX_OT_install_zip(bpy.types.Operator):
    bl_idname = "apexaddon.install_zip"
    bl_label = "Bereits installiert"
    bl_description = (
        "ZIP installieren. Ist die Erweiterung schon da, wird die alte "
        "nach Bestätigung entfernt und durch diese Datei ersetzt"
    )
    bl_options = {"INTERNAL"}

    filepath: StringProperty(subtype="FILE_PATH", options={"HIDDEN"})
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})
    replace: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    line_a: StringProperty(default="", options={"HIDDEN"})
    line_b: StringProperty(default="", options={"HIDDEN"})

    def invoke(self, context, event):
        self.replace = False
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text=self.line_a or f"{ADDON_NAME} ist bereits installiert.", icon="ERROR")
        if self.line_b:
            col.label(text=self.line_b)

    def execute(self, context):
        meta = read_zip_manifest(self.filepath)
        if meta is None or meta.get("id") != PKG_ID:
            self.report({"ERROR"}, "Dieses ZIP ist nicht Apex Auto Shader")
            return {"CANCELLED"}
        existing = find_installs()
        others = other_copies(existing)
        if others and not self.replace:
            have = ", ".join(sorted({item["version"] or "?" for item in others}))
            self.line_a = f"{ADDON_NAME} {have} ist bereits installiert."
            self.line_b = f"Alte Version entfernen und {meta['version']} installieren?"
            self.replace = True
            return context.window_manager.invoke_props_dialog(self, width=480)
        path = self.filepath

        def _swap():
            try:
                replace_with_zip(path)
            except Exception as exc:
                print(f"[Apex Auto Shader] ZIP-Install fehlgeschlagen: {exc}")
            return None

        try:
            bpy.app.timers.register(_swap, first_interval=0.4)
        except Exception:
            _swap()
        self.report({"INFO"}, "Alte Version wird entfernt und das ZIP installiert")
        return {"FINISHED"}
