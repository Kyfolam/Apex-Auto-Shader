from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent
ASSET_DIR = ADDON_DIR / "asset"
WRAITH_EYE_DIR = ASSET_DIR / "wraith"

CORE_APEX_SHADER_BLENDER_FILE = str(ASSET_DIR / "Apex Shader.blend")
PLUS_APEX_SHADER_BLENDER_FILE = str(ASSET_DIR / "Apex_Shader_Plus1.blend")
PLUS_SE_APEX_SHADER_BLENDER_FILE = str(ASSET_DIR / "se_Apex Shader Plus.blend")

ADDON_VERSION = (2, 0, 1)
ADDON_VERSION_STR = "2.0.1"
UPDATE_API = "https://api.github.com/repos/Kyfolam/Apex-Auto-Shader/releases/latest"
UPDATE_TAGS = "https://api.github.com/repos/Kyfolam/Apex-Auto-Shader/tags"
UPDATE_PAGE = "https://github.com/Kyfolam/Apex-Auto-Shader"
