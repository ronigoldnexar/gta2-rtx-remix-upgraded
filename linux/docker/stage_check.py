#!/usr/bin/env python3
"""Static health check of a stage folder before it may reach the play page.
Usage: stage_check.py <stage_dir> [<repo_dir>]   exit 0 = healthy, 1 = refuse (reasons on stdout)."""
import json, os, sys
stage = sys.argv[1]; repo = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(stage.rstrip('/')))
bad = []
def need(path, what):
    if not os.path.exists(path): bad.append(f"missing {what}: {path}")
for f in ('gta2dx9.dll', 'd3ddll.dll', 'gta2dx9_vid.dll', 'gta2dx9.ini'):
    need(os.path.join(stage, f), f)
dll = os.path.join(stage, 'gta2dx9.dll')
if os.path.exists(dll) and os.path.getsize(dll) < 2_000_000: bad.append(f"gta2dx9.dll suspiciously small: {os.path.getsize(dll)} bytes")
models = os.path.join(stage, 'gta2dx9_models'); man = os.path.join(models, 'manifest.json')
need(man, 'models manifest')
if os.path.exists(man):
    m = json.load(open(man))
    names = {f[:-5] for f in os.listdir(models) if f.endswith('.mesh')}
    cars = m.get('cars', {}).get('by_model', {})
    miss = [n for n in cars.values() if n not in names]
    if miss: bad.append(f"{len(miss)} car models in the manifest have no .mesh in the stage: {miss[:5]}")
    peds = m.get('pedestrians', [])
    miss = [n for n in peds if n not in names]
    if miss: bad.append(f"{len(miss)} avatars in the manifest have no .mesh in the stage: {miss[:5]}")
    for n in set(m.get('props', {}).values()):
        if n not in names: bad.append(f"prop model {n} has no .mesh")
    # every mesh must have at least one texture beside it (avatars and cars always do)
    tex = {f.rsplit('_', 1)[0] for f in os.listdir(models) if f.endswith(('.tga', '.dds'))}
    naked = [n for n in list(cars.values()) + list(peds) if n in names and n not in tex and not any(t.startswith(n) for t in tex)]
    if naked: bad.append(f"{len(naked)} models have a mesh but no texture (would draw untextured): {naked[:5]}")
    n = len(os.listdir(models))
    if n < 1500: bad.append(f"models folder has only {n} files (expected ~1900)")
    # compare with the repo's assets/models when available: the stage must not be a subset
    src = os.path.join(repo, 'assets', 'models')
    if os.path.isdir(src):
        s = set(os.listdir(src)); t = set(os.listdir(models))
        if len(s - t) > 0: bad.append(f"{len(s - t)} files in assets/models are not in the stage (e.g. {sorted(s - t)[:3]})")
hd = os.path.join(stage, 'gta2dx9_textures_hd')
if os.path.isdir(hd):
    for d in ('wil', 'ste', 'bil'):
        p = os.path.join(hd, d)
        if not os.path.isdir(p) or len(os.listdir(p)) < 500: bad.append(f"HD tiles for {d} missing or incomplete")
else:
    bad.append("no gta2dx9_textures_hd folder")
if bad:
    print("STAGE CHECK FAILED for", stage); [print(" -", b) for b in bad]; sys.exit(1)
print(f"stage check ok: {stage} ({len(os.listdir(models))} model files, {sum(len(os.listdir(os.path.join(hd, d))) for d in ('wil','ste','bil'))} HD tiles)")
