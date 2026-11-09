#!/usr/bin/env python3
"""IDENTITY-SYSTEM: does the Remix layer carry every identity's materials? (docs/identity-system.md 2.4)

    python3 tools/identity_remix_check.py <models dir> <mod dir> [--only player|peds|cars] [--json out.json]

For the models an identity record can name (the manifest's "pedestrian" = the player, every avatar
in "pedestrians" and "ped_types", every car in "cars.by_model"), each texture its mesh draws with is
hashed the way the runtime keys it (XXH3-64 of the uploaded texels, tools/remix_materials.py), and
looked up in <mod>/mod.usda:

  prim      a material prim for the hash exists (else Remix draws the game texture with the legacy
            material: coloured, but no normal / roughness: below the bar for an identity model)
  albedo    the prim's diffuse_texture file exists in the layer (a prim without its file renders
            the albedo as flat white-grey: the clay look)
  colour    the albedo is not a flat grey (std over opaque texels >= 6, or it matches the source)
  match     the albedo's mean colour is within 20 RGB of the texture the record draws with

The player's textures are checked first and reported on their own. Exit status: number of player
failures * 100 + other failures (capped at 250). Needs numpy, Pillow, xxhash.
"""
import argparse, json, os, re, sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm  # noqa: E402


def mesh_textures(models, name):
    p = os.path.join(models, name + ".mesh")
    if not os.path.exists(p):
        return []
    return sorted({t.decode() for t in re.findall(rb"[\w\-]+\.tga", open(p, "rb").read())})


def prim_block(usda, h):
    i = usda.find(f'"mat_{h}"')
    if i < 0:
        return None
    j = usda.find('over "mat_', i + 10)
    return usda[i:j if j > 0 else i + 4000]


def check_texture(models, mod, usda, tex):
    out = {"texture": tex}
    path = os.path.join(models, tex)
    if not os.path.exists(path):
        out["error"] = "texture file missing"; return out
    bgra = rm.read_tga(path)
    out["hash"] = h = rm.remix_hash(bgra)
    src = rm.to_rgba(bgra)
    # A split pair (x.tga + x_paint.tga) has one whole material for both prims
    # (tools/remix_model_materials.py): its albedo is the paint half where it is opaque, else the rest.
    other = tex[:-10] + ".tga" if tex.endswith("_paint.tga") else tex[:-4] + "_paint.tga"
    if os.path.exists(os.path.join(models, other)):
        o = rm.to_rgba(rm.read_tga(os.path.join(models, other)))
        if o.shape == src.shape:
            paint, rest = (src, o) if tex.endswith("_paint.tga") else (o, src)
            src = np.where((paint[..., 3] >= 128)[..., None], paint, rest).copy()
            src[..., 3] = np.maximum(paint[..., 3], rest[..., 3])
            out["pair"] = True
    src = src.reshape(-1, 4).astype(float)
    opaque = src[src[:, 3] >= 128][:, :3]
    out["src_mean"] = [round(v) for v in (opaque.mean(0) if len(opaque) else src[:, :3].mean(0))]
    blk = prim_block(usda, h)
    out["prim"] = blk is not None
    if blk is None:
        return out
    m = re.search(r"diffuse_texture = @([^@]+)@", blk)
    out["albedo_file"] = m.group(1) if m else None
    if not m:
        out["albedo"] = False; return out
    f = os.path.join(mod, m.group(1))
    out["albedo"] = os.path.exists(f)
    if not out["albedo"]:
        return out
    try:
        a = np.asarray(Image.open(f).convert("RGBA")).reshape(-1, 4).astype(float)
    except Exception as e:  # a DDS Pillow cannot read
        out["albedo_read"] = str(e); return out
    ao = a[a[:, 3] >= 128][:, :3] if (a[:, 3] >= 128).any() else a[:, :3]
    out["albedo_mean"] = [round(v) for v in ao.mean(0)]
    out["albedo_std"] = round(float(ao.std(0).mean()), 1)
    out["colour"] = bool(out["albedo_std"] >= 6 or np.abs(ao.mean(0) - np.array(out["src_mean"])).max() < 20)
    out["match"] = bool(np.abs(ao.mean(0) - np.array(out["src_mean"])).max() < 20)
    return out


def verdict(r):
    if "error" in r:
        return "FAIL", r["error"]
    if not r["prim"]:
        return "WARN", "no prim: legacy material (game texture, no PBR)"
    if not r.get("albedo"):
        return "FAIL", f"prim without its albedo file {r.get('albedo_file')}: flat grey under Remix"
    if "albedo_read" in r:
        return "WARN", "albedo not readable here: " + r["albedo_read"]
    if not r["colour"]:
        return "FAIL", f"albedo flat grey (std {r['albedo_std']})"
    if not r["match"]:
        return "FAIL", f"albedo mean {r['albedo_mean']} vs the texture drawn {r['src_mean']}: a stale prim"
    return "ok", f"prim, albedo {r['albedo_mean']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models"); ap.add_argument("mod")
    ap.add_argument("--only", choices=["player", "peds", "cars"], default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    man = json.load(open(os.path.join(a.models, "manifest.json")))
    usda = open(os.path.join(a.mod, "mod.usda"), encoding="utf-8").read()
    hero = man.get("pedestrian")
    groups = {"player": [hero] if hero else []}
    peds = set(man.get("pedestrians", []))
    for t in man.get("ped_types", []):
        peds.update(t.get("models", []))
    peds.discard(hero)
    groups["peds"] = sorted(peds)
    groups["cars"] = sorted(set(man.get("cars", {}).get("by_model", {}).values()))
    results, fails = {}, {"player": 0, "other": 0}
    for g, names in groups.items():
        if a.only and g != a.only:
            continue
        print(f"## {g} ({len(names)} models)")
        for n in names:
            for tex in mesh_textures(a.models, n):
                r = check_texture(a.models, a.mod, usda, tex)
                v, why = verdict(r)
                results.setdefault(g, []).append({"model": n, **r, "verdict": v, "why": why})
                if v == "FAIL":
                    fails["player" if g == "player" else "other"] += 1
                if v != "ok" or g == "player":
                    print(f"{v:4} {n:34} {tex:44} {r.get('hash', '-')}: {why}")
        n_ok = sum(1 for r in results.get(g, []) if r["verdict"] == "ok")
        print(f"   {g}: {n_ok} of {len(results.get(g, []))} textures ok")
    if a.json:
        json.dump(results, open(a.json, "w"), indent=1)
    sys.exit(min(250, fails["player"] * 100 + fails["other"]))


if __name__ == "__main__":
    main()
