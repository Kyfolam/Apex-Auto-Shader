# Cosmetics catalogs

Localized names for animation lists. No Banner Frames. Skin index stays in `asset/wraith/ncache.bin`.

| File | Used for |
|---|---|
| `banner_poses_by_legend.json` | Banner pose display names (gcard stances). Common/Rare = static, Epic+ = animated |
| `character_emotes_by_legend.json` | Ground emote display names |
| `character_executions_by_legend.json` | Finisher display names |
| `itemflav_clips.json` | CAST clip stems, lighting-rig clips, `horizontalFOV`, 4-spot `light0–3` |

A `gcard_stance` JSON has more than clip names. Needed for holocards:

- `stillAnimSeq` / `movingAnimSeq`
- `lightingRigStillAnimSeq` / `lightingRigMovingAnimSeq`
- `horizontalFOV`
- `light0–3_brightness`, `_distance`, `_cone`, `_innercone`, `_halfbrightfrac`, `_pbrfalloff`, `_castshadows`

All 458 stances currently ship with a 4-spot `lights` array. Refresh with:

```
python scripts/ingest_itemflav.py path/to/itemflav_extract.json
```

`gcard_frame` files (`light0_col`, exposure) tint the card chrome — they are not stances and are not applied here.

`overdrive` is indexed as **Axle**. Rebuild names from collector dumps with `scripts/rebuild_catalogs.py`.
