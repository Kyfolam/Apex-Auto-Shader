# Bundled shader files

These `.blend` files are node-group libraries. The add-on appends a group on first shade.

| File | Shader | Node group name | Author | Notes |
|---|---|---|---|---|
| `Apex Shader.blend` | Cores Apex Shader | `Cores Apex Shader` | CoReArtZz | Community default, many tutorials |
| `Apex_Shader_Plus1.blend` | Apex Shader+ | `Apex Shader+` | ovlack | Better skin/guns in many cases; our default |

Do **not** rename the node groups. `node_adder.py` looks up those exact names and socket labels.

## Newer “Shader Plus”?

[rroarings/apex-info](https://github.com/rroarings/apex-info) (formerly ovlack/apex-info) ships `se_Apex Shader Plus.blend` with node group `Apex_Shader`. That is a **different** tree (sockets and name). Swapping it in would break Auto-Shade until every input is remapped and retested on Blender 5.1.

We keep **Plus 1** as the wired default. A future optional third shader can be added once sockets are documented.

## Updating a blend

1. Replace the file in this folder.
2. Confirm the node group name still matches the table.
3. Shade a body/head/hair mesh and check albedo, normal, gloss, AO, ehl, opacity.
