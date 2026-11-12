# Bundled shader files

These `.blend` files are node-group libraries. The add-on appends a group on first shade.

| File | Shader | Node group name | Author | Notes |
|---|---|---|---|---|
| `se_Apex Shader Plus.blend` | se Apex Shader Plus | `Apex Shader+ [APPEND]` | se / community | Default |
| `Apex_Shader_Plus1.blend` | Apex Shader+ | `Apex Shader+` | ovlack | Plus 1 |
| `Apex Shader.blend` | Cores Apex Shader | `Cores Apex Shader` | CoReArtZz | Community classic |

Do **not** rename the node groups. `node_adder.py` looks up those exact names and socket labels.

## se Apex Shader Plus

Default. The node group is exactly `Apex Shader+ [APPEND]`.

Scatter color goes to Scatter Thickness (Radius), the image alpha to Scatter Thickness Alpha. Subsurface is set to 1 when a scatter map is linked, because the file default 0 turns SSS off. Opacity uses the image alpha on `Alpha (Opacity Multiply)`. There is no EHL input. Subsurface Color, Glossiness Controller and Bump Strength stay at the file defaults.

Color spaces match the other shaders: Non-Color for AO, cavity, gloss, normal, scatter, alpha and spec-dir. sRGB for albedo, emission and specular.

## Updating a blend

1. Replace the file in this folder.
2. Confirm the node group name still matches the table.
3. Shade a body/head/hair mesh and check albedo, normal, gloss, AO, ehl, opacity.
