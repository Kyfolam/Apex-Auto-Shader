# Bundled shader files

These `.blend` files are node-group libraries. The add-on appends a group on first shade.

| File | Shader | Node group name | Author | Notes |
|---|---|---|---|---|
| `se_Apex Shader Plus.blend` | se Apex Shader Plus | `Apex Shader+` | se / community | Default. Sockets differ from Plus 1 |
| `Apex_Shader_Plus1.blend` | Apex Shader+ | `Apex Shader+` | ovlack | Plus 1, still available |
| `Apex Shader.blend` | Cores Apex Shader | `Cores Apex Shader` | CoReArtZz | Community classic, many tutorials |

Do **not** rename the node groups. `node_adder.py` looks up those exact names and socket labels.

## se Apex Shader Plus

`se_Apex Shader Plus.blend` is bundled as an extra option and the addon default.

Inspected group inputs: Albedo, Subsurface / Scatter Thickness, Specular, Glossiness, Anis-Spec Dir, Emission, Alpha (Opacity Multiply), Cavity, Normal Map.

There is no dedicated AO socket (AO is multiplied with cavity inside the graph). Plus 1 remains selectable for the older wiring (`AO (Ambient Occlussion)`, `SSS (Subsurface Scattering)`, `Anis-SpecDir`).

Place the `.blend` next to this README (same filename). If only `se_Apex Shader Plus.blend.b64` is present, the add-on decodes it on first shade.

## Updating a blend

1. Replace the file in this folder.
2. Confirm the node group name still matches the table.
3. Shade a body/head/hair mesh and check albedo, normal, gloss, AO, ehl, opacity.
