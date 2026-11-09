# Release archives v1.6 (9 Nov 2026, RELEASE-PACK)

Packed offline with `tools/pack_release.py --stage stage --rev 8297aab` from the live
`stage/` (cut by `restage.sh` from committed HEAD `8297aab`, stage check ok: 2104 model
files, 2652 classic HD tiles plus the photo and roads subsets). Layouts: `docs/HANDOVER.md`
section 0. Archives are not in git.

## What changed since v1.5 (8 Nov)

| Archive | Change |
|---|---|
| `textures_hd_dds.zip` | Now carries FIX-WORLD-3's photo subset (2285 tiles) and `roads` (60) besides wil/bil/ste (846/930/876), plus the tiles repainted on 9 Nov. v1.5 shipped no textures archive (v1.4 set, 7 Nov, was the last). |
| `gta2dx9_models_people.zip` | The zoned avatars (801210a): 362 files (v1.5: 219). |
| `gta2dx9-x86-linux-built.zip` | DLLs/ini/reg from the stage built at `8297aab`; `BUILD.txt` records that commit and SHA-256s; the committed `linux/` tree at that commit. |

## Inventory

| Archive | Files | Bytes |
|---|---|---|
| `textures_hd_dds.zip` | 4997 | 509,540,152 |
| `gta2dx9_models_people.zip` | 362 | 234,620,293 |
| `gta2dx9-x86-linux-built.zip` | 493 | 5,532,586 |

## Verified

- `zip -T` clean on all three.
- Every entry's CRC-32 compared with the file in `stage/` (textures: 4997 of 4997 equal;
  people: 362 of 362; the DLL/ini/reg entries equal). The zip's tile list equals the
  stage's tile list in both directions; every `human_*` file in the stage's models folder
  is in the people zip. This is stronger than the requested three-file spot check.
- Not verified: a fresh-clone unpack and a game run from these archives.

## Skipped

- **Cars**: VEHICLE-ART-4 was still running (authored bodies still changing; it repacks at
  its end). The v1.5 cars zip is stale against the authored bodies (063, 013, 068, 036, 008,
  056), round-8 regenerations, wrecks (af3585f) and the 068/084/hot-dog manifest mapping.
- **Remix**: not repacked (REMIX-MATERIALS is rebuilding that layer); the 7 Nov
  `remix_mod_gta2hd.zip` is stale against the current HD tiles.
