# Alter eye textures (bundled as `wraith_base_*`)

These PNGs are the **Alter eye fallback** used by Apex Auto Shader when an Alter / hash-named eye mesh is shaded with Apex Shader+.

Filenames keep the historical `wraith_base_*` prefix for Shader+ graph compatibility. Do not rename them unless you also update the lookup in `utils.py`.

| File | Used for |
|---|---|
| `wraith_base_eyecornea_col.png` | Eyecornea albedo (`*eyecornea*col*` / `*albedo*`) |
| `wraith_base_eyecornea_nml.png` | Eyecornea normal (`*eyecornea*nml*` / `*normal*`) |
| `wraith_base_eyeshadow_col.png` | Eyeshadow albedo (`*eyeshadow*col*` / `*albedo*`) |

## Paths

1. **Bundled maps (preferred for Alter / hash eyes):** `asset/wraith/` → wired into Apex Shader+ (`apply_alter_plus_eye`).
2. **Glass fallback:** if bundled maps are missing or Plus wiring fails → transparent + glass mix (`apply_eye_shader` fallback). Other legends’ eyes typically use this glass path unless maps are present.

Example alternate names the loader also accepts if you replace the files:

- `*eyecornea*albedo*` / `*eyecornea*col*`
- `*eyecornea*normal*` / `*eyecornea*nml*`
- `*eyeshadow*albedo*` / `*eyeshadow*col*`
