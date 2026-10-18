# Apex Auto Shader

Blender **5.2** addon that auto-shades Apex Legends **CAST** models. Release **2.1.0**.

Requires the [CAST importer](https://github.com/dtzxporter/cast).

Companion: [Optic Enhancer 1.0.0](https://github.com/Kyfolam/Optic-Enhancer) (install this addon first).

---

## Install

1. Install and enable the CAST importer
2. Download the latest **Release** zip of this addon
3. **Edit → Preferences → Get Extensions → Install from Disk**
4. Enable **Apex Auto Shader**

`bl_info`, `config.ADDON_VERSION` and `blender_manifest.toml` are all **2.1.0**.

---

## How to use

<img width="236" height="101" alt="image" src="https://github.com/user-attachments/assets/53ca0948-5457-43b5-aaf6-d9906ec68ad0" />

### Import CAST Model(s)

Either you select the Folder where the Apex Legends Models are located in, then EVERY LOD0 Model is getting imported.
Or select the CAST model directly (multiple selection possible).

### Find Skins

Select the Folder of your exported files. The closer you are at the source, the faster the search is.
Then the Skins are listed which can be found and which not. You can search by Legends.
In the Search-Tab you can look for a specific Skin.

### Apply Shader

The shader dropdown follows the preference until you pick one for the scene. **Apply Shader** shades the selection with that choice.

---

## Features

- **Shaders** — se Apex Shader Plus (default), Apex Shader+ (ovlack), Cores (CoReArtZz), **Cinematic** (hard light, ink edge, cool rim), Object shader for props
- **Animations** — banner poses, ground emotes, drop emotes, finishers (with victim legend/skin)
- **Studio** — camera, 9:16 / 16:9, light boost, close-up depth of field, lock camera, showcase framing
- **Find Skins** — every skin in the packed list. Nothing is hidden right now (no unlisted tokens).

---

## Preferences

<img width="983" height="349" alt="image" src="https://github.com/user-attachments/assets/123ddf23-1dea-4382-baa5-e8541e679b18" />

Preferences live next to the addon in Blender's extension settings. The default shader applies to scenes you have not picked a shader for yet.

---

## Optic Enhancer

Optional look pack. It does not shade on its own. Install **Apex Auto Shader 2.1.0** first, then Optic Enhancer. It wraps `shade_selected` and adds crease, wear, mythic glow, portrait, studio-light controls and a Blender 5.2 lookdev pass.

---

## 2.1.0

- Cinematic shader
- Scene shader follows the preference until the dropdown or Choose Shader menu is used
- Animation folders: every matching class folder, not only the first hit
- Studio light boost and close-up DOF on the host (Optic Enhancer reuses them and does not stack a second multiplier)
- Default emotes No Sweat / Bring It / Cut Throat resolve from clip aliases (`pushups`, `bringit`, `cutthroat`)

Shaders: se Apex Shader Plus (default), ovlack (Apex Shader+ / Plus 1), CoReArtZz (Cores), Cinematic.
Thanks to YOROTSUKI for helping with the Skinlist
