# Apex Auto Shader

Blender **5.2** addon that auto-shades Apex Legends **CAST** models.

Requires the [CAST importer](https://github.com/dtzxporter/cast).

---

## Install

1. Install and enable the CAST importer.
2. Download the latest **Release** zip of this addon.
3. **Edit → Preferences → Get Extensions → Install from Disk**
4. Enable **Apex Auto Shader**, then restart Blender.

Zip the `apex_auto_shader` folder if you build it yourself. Do not use GitHub → Code → Download ZIP.

---

## How to use

### Import

**N-Panel → Apex Shader → Import CAST Model** and pick a `.cast` file.

Textures next to the file are wired automatically. The model is scaled and shaded with Apex Shader+.

<!-- Add docs/import.png -->

### Import all from folder

Pick the folder instead of a single file. Every LOD0 model in that folder is imported.

<!-- Add docs/import-folder.png -->

### Import selected through Skinlist

**Find Skins** — type a name or pick a legend, then import the match from your model folder.

<!-- Add docs/find-skins.png -->

---

## Features

- **Animations** — banner poses, emotes (ground / drop), finishers
- **Studio** — camera, lights, showcase framing

---

## Additional feature: Optic Enhancer

Optional companion addon for crease, wear, mythic glow and portrait shading.

Install Apex Auto Shader first, then [Optic Enhancer](https://github.com/Kyfolam/Optic-Enhancer).

---

Shaders: CoReArtZz (Cores), ovlack (Apex Shader+).  
Started from [Kaiserouo](https://github.com/Kaiserouo/Apex-Legends-Titanfall-Auto-Shader-Blender-Addon).
