# Apex Auto Shader

Blender **5.2** addon that auto-shades Apex Legends **CAST** models. Release **2.2.0**.

Requires the [CAST importer](https://github.com/dtzxporter/cast).

Companion: [Optic Enhancer 1.1.0](https://github.com/Kyfolam/Optic-Enhancer) (install this addon first).

---

## Install

1. Install and enable the CAST importer
2. Download the latest **Release** zip of this addon
3. **Edit → Preferences → Get Extensions → Install from Disk**
4. Enable **Apex Auto Shader**

OPTIONAL:
In Preference tab, insert your folder paths for smoother workflow.

---

## How to use

<img width="237" height="130" alt="image" src="https://github.com/user-attachments/assets/2404dfa9-8dc6-4d96-998d-0903d9e2b22d" />

### Import CAST Model(s)

Either you select the Folder where the Apex Legends Models are located in, then EVERY LOD0 Model is getting imported.
Or select the CAST model directly (multiple selection possible).
You can also mark favorite skins now.

### Find Skins

Select the Folder of your exported files. The closer you are at the source, the faster the search is.
Then the Skins are listed which can be found and which not. You can search by Legends.
In the Search-Tab you can look for a specific Skin.

### Apply Shader

The shader dropdown follows the preference until you pick one for the scene. **Apply Shader** shades the selection with that choice.

---

## Features

- **Shaders** — se Apex Shader Plus (default), Apex Shader+ (ovlack), Cores (CoReArtZz), **Cinematic** (hard light, ink edge, cool rim), Object shader for props
- **Animations** — banner poses, ground emotes, drop emotes, finishers (with own victim legend/skin if wanted)
- **Studio** — camera, 9:16 / 16:9, light boost, close-up depth of field, lock camera, showcase framing
- **Find Skins** — every skin in the game is listed. Unreleased Skins are not shown but can still be imported manually.

---

## Preferences

<img width="990" height="465" alt="Screenshot 2026-11-12 060848" src="https://github.com/user-attachments/assets/e101dd18-63ba-4e48-a880-ab5295324fa6" />

Preferences live next to the addon in Blender's extension settings. The default shader applies to scenes you have not picked a shader for yet.
Either you select the RSC export Folder directly so it loads all models/animations/props inside
OR you give it the folders directly to speed up things (or you have your own folder system which you wanna use).

---

## Optic Enhancer

Optional look pack. It does not shade on its own. 
Install **Apex Auto Shader 2.2.0** first, then [Optic Enhancer](https://github.com/Kyfolam/Optic-Enhancer). It has it's own functions and adds some options to the tool, more for playing around and for 3D Artists.

---
## 2.2.0

- Skin list updated
- Improved finding skin-logic
- Texturing should work better now
- Find Skin works with ingame name or as it's aliases 
- NEW: add props -> To add guns/heirlooms to the model
- added more options to camera settings like 16:9 vs 9:16, lock model feature, light adjustments
- added Engine selection Eevee vs Cycles

## 2.1.0

- Cinematic shader
- Scene shader follows the preference until the dropdown or Choose Shader menu is used
- Animation folders: every matching class folder, not only the first hit
- Studio light boost and close-up DOF on the host (Optic Enhancer reuses them and does not stack a second multiplier)
- Default emotes No Sweat / Bring It / Cut Throat resolve from clip aliases (`pushups`, `bringit`, `cutthroat`)

Shaders: se Apex Shader Plus (default), ovlack (Apex Shader+ / Plus 1), CoReArtZz (Cores), Cinematic.
Thanks to YOROTSUKI for helping with the Skinlist
