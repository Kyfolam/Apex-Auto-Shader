# Apex Auto Shader

Blender **5.2** addon that auto-shades Apex Legends **CAST** models.

Requires the [CAST importer](https://github.com/dtzxporter/cast).

Additional Add-On: [Optic Enhancer 1.0.0](https://github.com/Kyfolam/Optic-Enhancer) (requires this Apex Auto Shader).

---

## Install

1. Install and enable the [CAST importer](https://github.com/dtzxporter/cast)
2. Download the latest [Release](https://github.com/Kyfolam/Apex-Auto-Shader/releases/tag/v2.1.0) zip
3. **Edit → Preferences → Get Extensions → Install from Disk** and select the downloaded zip 
4. Enable **Apex Auto Shader** if it did not automatically do that

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

- **Shaders** — se Apex Shader Plus (default), Apex Shader+ (ovlack), Cores (CoReArtZz), **Cinematic** (experimental for getting shading of Apex Legends Cinematics)
- **Animations** — banner poses, ground emotes, skydive emotes, finishers (with victim legend/skin)
- **Studio** — camera, 9:16 / 16:9, light boost, close-up depth of field, lock camera, showcase framing
- **Find Skins** — every skin in the packed list. Unreleased Skins won't show up in list.

---

## Preferences

<img width="983" height="349" alt="image" src="https://github.com/user-attachments/assets/123ddf23-1dea-4382-baa5-e8541e679b18" />

Preferences live next to the addon in Blender's extension settings. The default shader applies to scenes you have not picked a shader for yet.

---

## 2.1.0

- Cinematic shader (experimental)
- Scene shader follows the preference until the dropdown or Choose Shader menu is used
- Studio light boost and close-up DOF on the host
- Automatically deletes and replaces the old version with the newest

Shaders: se Apex Shader Plus (default), ovlack (Apex Shader+ / Plus 1), CoReArtZz (Cores), Cinematic.
Thanks to YOROTSUKI for helping with the Skinlist
