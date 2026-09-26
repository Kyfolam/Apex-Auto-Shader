from __future__ import annotations

PREFIX_TOKEN_COUNT = 4
MIN_OBJECT_PREFIX_TOKENS = 3

# Legion / RSX: legend PNGs live here first
TECHART_LEGENDS_PARTS = ("mdl", "techart", "mshop", "characters", "legends")

IMAGE_SUFFIXES = {".png", ".dds", ".tga", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".bmp"}
IMAGE_SUFFIX_RANK = {
    ".png": 5,
    ".tga": 4,
    ".jpg": 3,
    ".jpeg": 3,
    ".tif": 2,
    ".tiff": 2,
    ".exr": 2,
    ".bmp": 1,
    ".dds": 0,
}
SKIP_DIR_NAMES = {"__pycache__", ".git", ".svn", ".hg"}

RECOLOR_CODES = (
    "rt01",
    "rt02",
    "rt03",
    "rt04",
    "rt05",
    "rt06",
    "rt07",
    "rt08",
    "rt09",
    "rc01",
    "rc02",
    "rc03",
)
LEVEL_CODES = ("level01", "level02", "level03")
# detail/transmittance have no matching group sockets; skip instead of orphan aliases.
SKIP_SLOTS = frozenset({"mask", "msk", "ehm", "detail", "transmittance"})

ANIM_GROUP_ORDER = (
    ("idle", "Idle"),
    ("pose", "Bannerpose"),
    ("emote", "Emote"),
    ("finisher_solo", "Finisher Solo"),
    ("finisher_full", "Finisher Full"),
    ("select", "Select / Lobby"),
    ("ingame", "In-game"),
    ("other", "Other"),
)

WEIGHT_CLASSES = ("light", "medium", "heavy")

# Bundled graph stamps (keep aligned with the .blend node groups)
PLUS_GRAPH_STAMP = "ovlack"

LEGEND_SLUGS: dict[str, str] = {
    "shared": "Shared",
    "alter": "Alter",
    "ash": "Ash",
    "axle": "Axle",
    "overdrive": "Axle",
    "ballistic": "Ballistic",
    "bangalore": "Bangalore",
    "bang": "Bangalore",
    "bloodhound": "Bloodhound",
    "bh": "Bloodhound",
    "catalyst": "Catalyst",
    "caustic": "Caustic",
    "conduit": "Conduit",
    "crypto": "Crypto",
    "fuse": "Fuse",
    "gibraltar": "Gibraltar",
    "gibby": "Gibraltar",
    "horizon": "Horizon",
    "nova": "Horizon",
    "lifeline": "Lifeline",
    "support": "Lifeline",
    "loba": "Loba",
    "madmaggie": "Mad Maggie",
    "maggie": "Mad Maggie",
    "mirage": "Mirage",
    "holo": "Mirage",
    "newcastle": "Newcastle",
    "octane": "Octane",
    "stim": "Octane",
    "pathfinder": "Pathfinder",
    "rampart": "Rampart",
    "revenant": "Revenant",
    "rev": "Revenant",
    "seer": "Seer",
    "pariah": "Seer",
    "sparrow": "Sparrow",
    "valkyrie": "Valkyrie",
    "valk": "Valkyrie",
    "vantage": "Vantage",
    "wattson": "Wattson",
    "wraith": "Wraith",
}

CANON_LEGENDS = (
    "alter",
    "ash",
    "axle",
    "ballistic",
    "bangalore",
    "bloodhound",
    "catalyst",
    "caustic",
    "conduit",
    "crypto",
    "fuse",
    "gibraltar",
    "horizon",
    "lifeline",
    "loba",
    "madmaggie",
    "mirage",
    "newcastle",
    "octane",
    "pathfinder",
    "rampart",
    "revenant",
    "seer",
    "sparrow",
    "valkyrie",
    "vantage",
    "wattson",
    "wraith",
)

SLOT_ALIASES: dict[str, str] = {
    "col": "albedo",
    "color": "albedo",
    "colour": "albedo",
    "alb": "albedo",
    "albedo": "albedo",
    "albedotexture": "albedo",
    "diffuse": "albedo",
    "dif": "albedo",
    "diff": "albedo",
    "ao": "ao",
    "aotexture": "ao",
    "occ": "ao",
    "ambientocclusion": "ao",
    "cav": "cavity",
    "cavity": "cavity",
    "cavitytexture": "cavity",
    "ilm": "emissive",
    "illum": "emissive",
    "illumination": "emissive",
    "emissive": "emissive",
    "emissivetexture": "emissive",
    "emit": "emissive",
    "ems": "emissive",
    "emi": "emissive",
    # Skin VFX overlays (Legion PNG exports). Wire like ilm for now.
    "vfx": "emissive",
    "fx": "emissive",
    "vxd": "emissive",
    "vfxtexture": "emissive",
    "fxtexture": "emissive",
    "vxdtexture": "emissive",
    "emissivemultiply": "emissive",
    "emissivemultiplytexture": "emissive",
    "gls": "gloss",
    "gloss": "gloss",
    "glosstexture": "gloss",
    "glossiness": "gloss",
    "glo": "gloss",
    "nml": "normal",
    "nrm": "normal",
    "nor": "normal",
    "norm": "normal",
    "normal": "normal",
    "normaltexture": "normal",
    "spc": "spec",
    "spec": "spec",
    "spectexture": "spec",
    "specular": "spec",
    "spctexture": "spec",
    "opa": "opacity",
    "opacity": "opacity",
    "opacitymultiply": "opacity",
    "opacitymultiplytexture": "opacity",
    "alphamultiply": "opacity",
    "alpha": "opacity",
    "trans": "opacity",
    "thk": "scatter",
    "sss": "scatter",
    "scatter": "scatter",
    "scatterthickness": "scatter",
    "scatterthicknesstexture": "scatter",
    "thickness": "scatter",
    "asa": "aniso",
    "aniso": "aniso",
    "anisospecdir": "aniso",
    "anisospecdirtexture": "aniso",
    "ehl": "ehl",
    "ehltexture": "ehl",
    "ehm": "ehm",
    "ehmtexture": "ehm",
    "det": "detail",
    "detail": "detail",
    "tint": "transmittance",
    "transmittance": "transmittance",
    "transmittancetint": "transmittance",
    "transmittancetinttexture": "transmittance",
}

SLOT_LABELS: dict[str, str] = {
    "albedo": "Albedo / Color",
    "ao": "Ambient Occlusion",
    "cavity": "Cavity",
    "emissive": "Emissive / Illumination / VFX",
    "gloss": "Gloss",
    "normal": "Normal",
    "spec": "Specular",
    "opacity": "Opacity Multiply",
    "scatter": "Scatter Thickness",
    "aniso": "Anisotropic Spec Dir",
    "ehl": "EHL",
    "ehm": "EHM",
    "detail": "Detail",
    "transmittance": "Transmittance Tint",
}

# Data maps stay linear. Albedo, emission and specular stay sRGB (see node_adder._tex).
NONCOLOR_SLOTS = frozenset({
    "ao",
    "cavity",
    "gloss",
    "normal",
    "scatter",
    "opacity",
    "aniso",
})
EXPECTED_SLOTS = ("albedo", "normal", "gloss")
SLOT_SHORT = {
    "albedo": "col",
    "ao": "ao",
    "cavity": "cav",
    "emissive": "ilm",
    "gloss": "gls",
    "normal": "nml",
    "spec": "spc",
    "opacity": "opa",
    "scatter": "sss",
    "aniso": "asa",
    "ehl": "ehl",
    "ehm": "ehm",
}

RARITY_DIR = {
    "base": "base",
    "lgnd": "legendary",
    "legendary": "legendary",
    "mythic": "mythic",
    "prestige": "mythic",
    "iconic": "iconic",
    "icon": "iconic",
    "epic": "epic",
    "epicp": "epic",
    "rare": "rare",
    "common": "common",
}
RARITY_LABELS = {
    "base": "Original",
    "lgnd": "Legendary",
    "legendary": "Legendary",
    "mythic": "Prestige",
    "prestige": "Prestige",
    "iconic": "Iconic",
    "icon": "Iconic",
    "epic": "Epic",
    "epicp": "Epic",
    "rare": "Rare",
    "common": "Common",
}
RARITY_ORDER = ("Prestige", "Iconic", "Legendary", "Epic", "Rare", "Common", "Original", "Other")

# Preview / cores cache mark
CORES_GRAPH_STAMP = "CoReArtZz"
ASSET_REV_MARK = "plus1"

EYE_HASH_MESHES = {
    "16564475196701862357": "eyecornea",
    "17812929278914435647": "eyeshadow",
}

MESH_PARTS = frozenset(
    {
        "body",
        "head",
        "hair",
        "hair02",
        "gear",
        "kit",
        "glass",
        "legs",
        "arms",
        "hand",
        "hands",
        "eye",
        "eyes",
        "eyeshadow",
        "eyecornea",
        "transparent",
        "trans",
        "alpha",
    }
)

# Original / fork authors (about line + cache mix)
SRC_AUTHOR = "Kaiserouo"
FORK_AUTHOR = "Kyfolam"
