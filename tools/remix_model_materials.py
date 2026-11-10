#!/usr/bin/env python3
"""Remix materials for every 3D model texture: cars, props, code objects, avatars.

The renderer uploads every model texture (assets/models/*.tga, 32-bit) as a
single-level A8R8G8B8 managed texture, rows top-down, so Remix names it by the
same XXH3-64 of the BGRA texels as the 64 px world tiles. This writes one
AperturePBR_Opacity prim per such texture into <mod>/mod.usda (replacing only the
prims it wrote before; tile and sign prims are kept) with full PBR maps from
tools/remix_model_pbr.py: albedo (BC3), normal (octahedral BC5, DirectX
orientation), roughness and metallic (BC4, or a constant where the map is flat)
and an emissive mask (BC3) where something glows. See remix_model_pbr.py for how
each map is made and docs/remix-materials.md ("Model PBR maps") for what was
checked.

Split pairs. The importer splits a car's baked texture into `<name>_N.tga` (all
but the paint) and `<name>_N_paint.tga` (the paint, tinted per car at draw time),
and an avatar's body texture into skin and clothing the same way; the renderer
draws the mesh twice, once per half, each alpha-tested at 128. Under Remix the
second of two draws with the same geometry and transform is taken as a duplicate
of the first (seen 8 Nov: cars in pieces), so both prims of a pair carry one
opaque material for the whole surface: the halves merged, the paint texels with
the clear coat (cars) or the cloth (avatars), the rest per texel. Whichever draw
the runtime keeps, the whole model is drawn, once.

    remix_model_materials.py assets/models <mod dir> [--src ../assets-src] [--jobs 4]
        [--paint-roughness 0.12] [--paint-metallic 0.05] [--pattern REGEX] [--preview DIR] [--report JSON]

--src: the source assets the importer read (assets-src, outside the repo): their
normal / roughness / metallic maps and material factors are used where they exist;
without it every map is derived from the albedo. Run it after remix_materials.py /
remix_emissive.py, which rewrite the whole layer (linux/docker/build_remix_mod.sh
does). Existing files are unlinked before being rewritten, so a mod folder whose
textures are hard links to another one's is safe to build into.
"""
import argparse, json, os, re, sys, time
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm
import remix_model_pbr as pbr

PRIM_HEAD = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Opacity.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Opacity"
                custom asset inputs:diffuse_texture = @./textures/{h}.a.rtex.dds@ (
                    colorSpace = "sRGB"
                )
'''
NORMAL = '''                custom asset inputs:normalmap_texture = @./textures/{h}.n.rtex.dds@ (
                    colorSpace = "raw"
                )
'''
TEX = '''                custom asset inputs:{inp} = @./textures/{h}.{s}.rtex.dds@ (
                    colorSpace = "raw"
                )
'''
CONST = '''                custom float inputs:{inp} = {v:.3f}
'''
EMISSIVE = '''                custom asset inputs:emissive_mask_texture = @./textures/{h}.e.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom bool inputs:enable_emission = 1
                custom float inputs:emissive_intensity = {intensity}
'''
TAIL = '''                custom bool inputs:use_legacy_alpha_state = {legacy_alpha}
                token outputs:out
            }}
        }}
'''
PRIM = re.compile(r' {8}over "mat_([0-9A-F]{16})"\n {8}\{\n.*?\n {8}\}\n', re.S)
# FIX-REMIX-MATERIALS-5: a carkit body's translucent glass (tools/vehicle_art/glass_translucent.py writes
# <car>_glass.tga, alpha ~0.45, drawn blended). Under Remix a low-alpha blended quad is path traced as a dark
# smear (memory: blend colour x alpha), and an opaque prim would black the cab out: the glass is a thin-walled
# translucent dielectric instead, its transmittance the texel colour over the alpha (dark tinted cab glass that
# reflects the sky and shows the cab behind it). The same for a prop's translucent "__glass" companion (alpha ~0.15).
GLASS_RE = re.compile(r"^\d{3}_.*_glass\.tga$|__glass_\d+\.tga$")   # car glass; a prop's "<name>__glass" panes (bus shelter, phone booth)
GLASS = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Translucent.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Translucent"
                custom color3f inputs:transmittance_color = ({r:.3f}, {g:.3f}, {b:.3f})
                custom float inputs:transmittance_measurement_distance = 1
                custom bool inputs:thin_walled = 1
                custom float inputs:thin_wall_thickness = 1
                custom float inputs:ior_constant = 1.5
                token outputs:out
            }}
        }}
'''

# FIX-REMIX-GLASS (prx6, prxq): the renderer's own car-glass textures under Remix (dll/src/car_glass.cpp
# RemixTextures / FixedTexture): the panes cut out of every generated body and the cabin behind them are
# drawn with three 256x256 textures of fixed content, so three fixed hashes. No model file names them, so
# the per-texture loop never wrote their prims and the shipped layer had none: Remix drew the panes as its
# default opaque matte material over the pane texture's pale blue-white (flat chalk-white cards by day,
# cream blobs under a street lamp at night) and the cabin as grey-brown legacy surfaces. Keep the colours
# here in step with RemixTextures(); the hash is computed from them as the DLL computes it.
FLEET_TEXTURES = (("pane", 0x50B4C2C8), ("cabin trim", 0xFF2E2A27), ("cabin headliner", 0xFF6E6862))
# The pane: tinted thin-walled glass (smooth: AperturePBR_Translucent has no roughness, the reflection is
# the IOR 1.5 Fresnel). Transmittance per pass ~0.55 at 1 unit of the thin wall: a street-legal dark tint,
# so a cabin lit only through its glass reads dark at night and the sky/street reflection carries the pane.
FLEET_GLASS = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Translucent.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Translucent"
                custom color3f inputs:transmittance_color = ({r:.3f}, {g:.3f}, {b:.3f})
                custom float inputs:transmittance_measurement_distance = 1
                custom bool inputs:thin_walled = 1
                custom float inputs:thin_wall_thickness = 1
                custom float inputs:ior_constant = 1.5
                token outputs:out
            }}
        }}
'''
# The cabin: matte, its colour from the legacy texture (no albedo map: the fixed texture IS the colour),
# trim and seats a dark fabric, the headliner a lighter cloth.
FLEET_MATTE = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Opacity.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Opacity"
                custom float inputs:metallic_constant = 0
                custom float inputs:reflection_roughness_constant = {rough:.2f}
                custom bool inputs:use_legacy_alpha_state = 0
                token outputs:out
            }}
        }}
'''
FLEET_GLASS_T = (0.55, 0.58, 0.60)


def fixed_texture_hash(argb, n=256):
    """XXH3-64 of car_glass.cpp FixedTexture(argb): BGRA texels, a 2-bit ordered ripple on the base colour."""
    import xxhash
    y, x = np.mgrid[0:n, 0:n]
    d = ((x * 7 + y * 13) & 3).astype(np.uint32)
    px = np.empty((n, n, 4), np.uint8)
    px[..., 0] = ((argb & 0xFF) + d) & 0xFF
    px[..., 1] = (((argb >> 8) & 0xFF) + d) & 0xFF
    px[..., 2] = (((argb >> 16) & 0xFF) + d) & 0xFF
    px[..., 3] = (argb >> 24) & 0xFF
    return "%016X" % xxhash.xxh3_64_intdigest(px.tobytes())


def fleet_entries():
    out = []
    for what, argb in FLEET_TEXTURES:
        h = fixed_texture_hash(argb)
        if what == "pane":
            prim = FLEET_GLASS.format(h=h, r=FLEET_GLASS_T[0], g=FLEET_GLASS_T[1], b=FLEET_GLASS_T[2])
        else:
            prim = FLEET_MATTE.format(h=h, rough=0.80 if what == "cabin trim" else 0.90)
        out.append({"hash": h, "file": f"(renderer) car glass {what}", "prim": prim, "sizes": {}, "kind": "fleet_glass",
                    "source": "car_glass.cpp", "stats": {"argb": "%08X" % argb}, "gain": 0.0, "size": [256, 256]})
    return out


def read_mesh(path):
    """(texture, vertices[n, 8]: position, normal, uv; indices) per mesh of a GMSH file
    (tools/import_assets.py writes them); node transforms are ignored (the car models
    are one node at the origin, +z along the length)."""
    import struct
    d = open(path, "rb").read(); p = 4
    _, nn, nm, _, _ = struct.unpack_from("<IIIII", d, p); p += 20
    p += nn * (32 + 4 + 12 + 16 + 12 + 4)
    out = []
    for _ in range(nm):
        nv, ni = struct.unpack_from("<II", d, p); p += 8
        tex = d[p:p + 64].split(b"\0")[0].decode(); p += 64
        skin, = struct.unpack_from("<i", d, p); p += 4
        v = np.frombuffer(d, np.float32, nv * 8, p).reshape(nv, 8); p += nv * 32
        if skin >= 0: p += nv * 24
        idx = np.frombuffer(d, np.uint32, ni, p).reshape(-1, 3); p += ni * 4
        out.append((tex, v, idx))
    return out


def end_masks(models_dir, names):
    """Per texture: the texels the car's two ends use (REMIX-3). A lamp is red at the
    nose or the tail; the red stripes, crosses and doors of a livery are along the
    flanks. A triangle counts when its centre lies within 14 % of the length from either
    end and it faces that way (|normal z| > 0.35); rasterised in UV space and grown by
    two texels. Textures no mesh names are missing from the result."""
    tris = {}
    for m in names:
        try: meshes = read_mesh(os.path.join(models_dir, m))
        except Exception: continue
        for tex, v, idx in meshes:
            if len(idx): tris.setdefault(tex, []).append((v, idx))
    masks = {}
    for tex, parts in tris.items():
        path = os.path.join(models_dir, tex)
        if not os.path.exists(path): continue
        with Image.open(path) as im: w, h = im.size
        mask = np.zeros((h, w), bool)
        zs = np.concatenate([v[:, 2] for v, _ in parts]); z0, z1 = float(zs.min()), float(zs.max())
        L = max(z1 - z0, 1e-6)
        for v, idx in parts:
            P = v[idx][:, :, :3]; UV = v[idx][:, :, 6:8]
            c = P.mean(1)[:, 2]
            n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); nl = np.linalg.norm(n, axis=1) + 1e-12
            at_end = ((c - z0 < 0.14 * L) | (z1 - c < 0.14 * L)) & (np.abs(n[:, 2]) / nl > 0.35)
            for uv in UV[at_end]:
                x = uv[:, 0] * w; y = uv[:, 1] * h
                xa, xb = int(max(np.floor(x.min()), 0)), int(min(np.ceil(x.max()), w - 1))
                ya, yb = int(max(np.floor(y.min()), 0)), int(min(np.ceil(y.max()), h - 1))
                if xb < xa or yb < ya: continue
                gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
                d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
                if abs(d) < 1e-9: continue
                a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
                b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
                inside = (a >= -0.02) & (b >= -0.02) & (1 - a - b >= -0.02)
                mask[ya:yb + 1, xa:xb + 1] |= inside
        for _ in range(2):
            g = mask.copy(); g[1:] |= mask[:-1]; g[:-1] |= mask[1:]; g[:, 1:] |= mask[:, :-1]; g[:, :-1] |= mask[:, 1:]; mask = g
        masks[tex] = mask
    return masks



def _raster_line(acc, a, b, val, w, h):
    """adds val along the UV segment a-b (v down the image) into acc, one sample per half texel"""
    x0, y0 = a[0] * w, a[1] * h; x1, y1 = b[0] * w, b[1] * h
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    t = np.linspace(0.0, 1.0, n + 1)
    xs = np.clip((x0 + (x1 - x0) * t).astype(int), 0, w - 1); ys = np.clip((y0 + (y1 - y0) * t).astype(int), 0, h - 1)
    acc[ys, xs] = np.maximum(acc[ys, xs], val)


def crease_maps(models_dir, names, pattern=r"_paint\.tga$"):
    """FIX-REMIX-CARS-1: per carkit paint texture, (groove 0..1, roughness offset) from the mesh's own folds.
    Vertices are welded by position; an edge between two faces bends by their dihedral angle, concave when the
    second face's centre lies in front of the first face's plane. Concave folds of CREASE_MIN_DEG..CREASE_FULL_DEG
    and more become a groove (and SEAM_ROUGH more roughness on its floor), convex ones a smoother rim
    (CONVEX_ROUGH). Rasterised into UV space, so only for a texture whose layout does not overlap itself on one
    side of the car (a mirrored left/right pair is fine: the car is symmetric); textures that fail are left out."""
    out = {}
    for m in names:
        try: meshes = read_mesh(os.path.join(models_dir, m))
        except Exception: continue
        for tex, v, idx in meshes:
            if not re.search(pattern, tex) or not len(idx) or not pbr.authored_part(tex[:-10] + ".tga"): continue
            path = os.path.join(models_dir, tex)
            if not os.path.exists(path): continue
            with Image.open(path) as im: w, h = im.size
            P = v[:, :3].astype(np.float64); UV = v[:, 6:8]
            Pf = P[idx]; cen = Pf.mean(1)
            # overlap check on one side of the car
            side = cen[:, 0] < -1e-4
            cnt = np.zeros((h, w), np.int16)
            for uv in UV[idx[side]]:
                msk = np.zeros((h, w), bool); x = uv[:, 0] * w; y = uv[:, 1] * h
                xa, xb = int(max(np.floor(x.min()), 0)), int(min(np.ceil(x.max()), w - 1))
                ya, yb = int(max(np.floor(y.min()), 0)), int(min(np.ceil(y.max()), h - 1))
                if xb < xa or yb < ya: continue
                gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
                d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
                if abs(d) < 1e-12: continue
                a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
                b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
                cnt[ya:yb + 1, xa:xb + 1] += (a > 0) & (b > 0) & (1 - a - b > 0)
            cov = int((cnt > 0).sum())
            if not cov or (cnt > 1).sum() > 0.02 * cov:
                print(f"  crease bake skipped for {tex}: UV overlap {(cnt > 1).sum()} of {cov} texels", flush=True); continue
            wid = np.unique(np.round(P / 1e-4).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
            nrm = np.cross(Pf[:, 1] - Pf[:, 0], Pf[:, 2] - Pf[:, 0]); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
            edges = {}
            for fi, (a0, b0, c0) in enumerate(idx):
                for i, j in ((a0, b0), (b0, c0), (c0, a0)):
                    edges.setdefault((min(wid[i], wid[j]), max(wid[i], wid[j])), []).append((fi, i, j))
            groove = np.zeros((h, w), np.float32); rim = np.zeros((h, w), np.float32)
            for lst in edges.values():
                if len(lst) != 2: continue
                (f1, i1, j1), (f2, i2, j2) = lst
                ang = float(np.degrees(np.arccos(np.clip(nrm[f1] @ nrm[f2], -1, 1))))
                if ang < pbr.CREASE_MIN_DEG: continue
                t = min((ang - pbr.CREASE_MIN_DEG) / (pbr.CREASE_FULL_DEG - pbr.CREASE_MIN_DEG), 1.0)
                acc = groove if nrm[f1] @ (cen[f2] - cen[f1]) > 0 else rim
                for i, j in ((i1, j1), (i2, j2)): _raster_line(acc, UV[i], UV[j], t, w, h)
            k = max(min(h, w), 16) / 512.0
            g = pbr.gauss(groove, pbr.SEAM_WIDTH * max(k, 0.5)); g = np.clip(g / max(float(g.max()), 1e-3) * 2.0, 0, 1) if g.max() > 0 else g
            r = pbr.gauss(rim, 1.5 * max(k, 0.5)); r = np.clip(r / max(float(r.max()), 1e-3) * 2.0, 0, 1) if r.max() > 0 else r
            out[tex] = (g.astype(np.float32), (pbr.CONVEX_ROUGH * r).astype(np.float32))
    return out


def fresh(path):
    """unlink before writing: never write through a hard link into another mod folder"""
    if os.path.lexists(path): os.remove(path)
    return path

def write_unit(job):
    """Maps, DDS files and prims for one unit (a split pair or a lone texture)."""
    rest, paint, models, tex, preview = job
    G = _G
    bgr_r = rm.read_tga(os.path.join(models, rest)) if rest else None
    bgr_p = rm.read_tga(os.path.join(models, paint)) if paint else None
    base = rest or paint[:-10] + ".tga"
    spec = G["specs"].get(base) or G["specs"].get(paint or "")
    is_car = bool(re.match(r"\d{3}_", base))
    if rest and paint and bgr_r.shape == bgr_p.shape:
        r, pt = rm.to_rgba(bgr_r), rm.to_rgba(bgr_p)
        is_paint = pt[..., 3] >= 128
        albedo = np.where(is_paint[..., None], pt, r).copy()
        union = np.maximum(r[..., 3], pt[..., 3])
        work = albedo.copy(); work[..., 3] = union
        albedo[..., 3] = 255
        mp = pbr.texture_maps(base, work, spec, G["ends"].get(rest), paint_mask=is_paint, is_car=is_car)
        targets = [(rest, bgr_r), (paint, bgr_p)]; legacy, kind = 0, "pair"
    elif paint and not rest:
        albedo = rm.to_rgba(bgr_p)
        mp = pbr.texture_maps(paint, albedo, spec, None, is_car=is_car, crease=G["crease"].get(paint))
        targets = [(paint, bgr_p)]; legacy, kind = 1, "paint"
    else:
        albedo = rm.to_rgba(bgr_r)
        mp = pbr.texture_maps(rest, albedo, spec, G["ends"].get(rest), is_car=is_car)
        targets = [(rest, bgr_r)]; legacy, kind = 1, "lone"
    if kind == "lone" and GLASS_RE.search(rest):
        px = albedo[..., :3].astype(np.float32) / 255.0; al = albedo[..., 3].astype(np.float32) / 255.0
        a = float(al.mean()); c = px.reshape(-1, 3).mean(0)
        t = np.clip((1.0 - a) + a * c, 0.35, 0.92)
        h = rm.remix_hash(bgr_r)
        for s in "anmre":
            q = os.path.join(tex, f"{h}.{s}.rtex.dds")
            if os.path.lexists(q): os.remove(q)
        return [{"hash": h, "file": rest, "prim": GLASS.format(h=h, r=t[0], g=t[1], b=t[2]), "sizes": {}, "kind": "glass",
                 "source": "glass", "stats": {"alpha": round(a, 3)}, "gain": 0.0, "size": list(albedo.shape[:2])}]
    out = []
    for f, b in targets:
        h = rm.remix_hash(b)
        sizes = {}
        p = fresh(os.path.join(tex, f"{h}.a.rtex.dds")); rm.write_albedo(p, albedo); sizes["a"] = os.path.getsize(p)
        body = PRIM_HEAD.format(h=h)
        if mp["normal"] is not None:
            p = fresh(os.path.join(tex, f"{h}.n.rtex.dds")); rm.write_normal(p, mp["normal"]); sizes["n"] = os.path.getsize(p)
            body += NORMAL.format(h=h)
        elif os.path.lexists(os.path.join(tex, f"{h}.n.rtex.dds")): os.remove(os.path.join(tex, f"{h}.n.rtex.dds"))
        for key, s, inp_t, inp_c in (("metal", "m", "metallic_texture", "metallic_constant"),
                                     ("rough", "r", "reflectionroughness_texture", "reflection_roughness_constant")):
            m = mp[key]; vis = albedo[..., 3] >= 128
            vals = m[vis] if vis.any() else m.reshape(-1)
            if float(vals.max() - vals.min()) < 0.02:
                body += CONST.format(inp=inp_c, v=float(np.median(vals)))
                if os.path.lexists(os.path.join(tex, f"{h}.{s}.rtex.dds")): os.remove(os.path.join(tex, f"{h}.{s}.rtex.dds"))
            else:
                p = fresh(os.path.join(tex, f"{h}.{s}.rtex.dds")); rm.write_roughness(p, np.clip(m * 255, 0, 255)); sizes[s] = os.path.getsize(p)
                body += TEX.format(inp=inp_t, h=h, s=s)
        ep = os.path.join(tex, f"{h}.e.rtex.dds")
        if mp["emit"] is not None and int((mp["emit"].max(-1) > 0).sum()) >= 4:
            em = np.concatenate([mp["emit"], np.full(mp["emit"].shape[:2] + (1,), 255, np.uint8)], -1)
            rm.write_albedo(fresh(ep), em); sizes["e"] = os.path.getsize(ep)
            body += EMISSIVE.format(h=h, intensity=round(mp["gain"], 2))
        elif os.path.lexists(ep): os.remove(ep)
        body += TAIL.format(legacy_alpha=legacy)
        out.append({"hash": h, "file": f, "prim": body, "sizes": sizes, "kind": kind, "source": mp["source"],
                    "stats": mp["stats"], "gain": mp["gain"], "size": list(albedo.shape[:2])})
    if preview:
        os.makedirs(preview, exist_ok=True)
        n = mp["normal"] if mp["normal"] is not None else np.dstack([np.zeros(albedo.shape[:2])] * 2 + [np.ones(albedo.shape[:2])])
        cells = [albedo[..., :3], pbr.normal_rgb(n), np.repeat((mp["rough"] * 255).astype(np.uint8)[..., None], 3, -1),
                 np.repeat((mp["metal"] * 255).astype(np.uint8)[..., None], 3, -1),
                 mp["emit"] if mp["emit"] is not None else np.zeros_like(albedo[..., :3]),
                 pbr.shade(albedo, None), pbr.shade(albedo, mp["normal"], mp["rough"], mp["metal"])]
        Image.fromarray(np.concatenate(cells, 1)).save(os.path.join(preview, base[:-4] + "_maps.png"))
    return out


_G = {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("mod")
    ap.add_argument("--src", default=None, help="assets-src (default: <models>/../../../assets-src)")
    ap.add_argument("--paint-roughness", "--roughness", type=float, default=pbr.PAINT_ROUGHNESS)
    ap.add_argument("--paint-metallic", "--metallic", type=float, default=pbr.PAINT_METALLIC)
    ap.add_argument("--pattern", default=r".*\.tga$")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--preview", default=None)
    ap.add_argument("--report", default=None, help="write a JSON list of the prims written (hash, file, maps, sizes)")
    ap.add_argument("--fleet-only", action="store_true", help="only the renderer's car-glass prims (FLEET_TEXTURES), for a scratch layer + remix_layer_merge.py")
    a = ap.parse_args()
    t0 = time.time()
    pbr.PAINT_METALLIC, pbr.PAINT_ROUGHNESS = a.paint_metallic, a.paint_roughness
    src = a.src or os.path.abspath(os.path.join(a.models, "..", "..", "..", "assets-src"))
    tex = os.path.join(a.mod, "textures"); os.makedirs(tex, exist_ok=True)
    usda = os.path.join(a.mod, "mod.usda")
    text = open(usda, encoding="utf-8").read() if os.path.exists(usda) else \
        '#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n    }\n}\n'
    manifest = json.load(open(os.path.join(a.models, "manifest.json")))
    names = [m["name"] for m in manifest.get("models", [])]
    meshes = sorted(n + ".mesh" for n in names if os.path.exists(os.path.join(a.models, n + ".mesh")))
    # Only the textures a manifest model's mesh names (and their paint halves): the
    # importer leaves older parts' textures in the folder when a model changes.
    used, names_tex = set(), {}
    for m in meshes:
        for t in re.findall(rb"[\w\-]+\.tga", open(os.path.join(a.models, m), "rb").read()):
            t = t.decode(); used.add(t); used.add(t[:-4] + "_paint.tga")
            names_tex.setdefault(m, set()).update((t, t[:-4] + "_paint.tga"))
    files = [] if a.fleet_only else sorted(f for f in os.listdir(a.models) if re.match(a.pattern, f) and f in used)
    # only the models behind the selected textures need their sources and end masks
    meshes_sel = [m for m in meshes if names_tex.get(m, set()) & set(files)]
    have = set(files)
    units = []
    for f in files:
        if f.endswith("_paint.tga"):
            if f[:-10] + ".tga" not in have: units.append((None, f))
        else:
            units.append((f, f[:-4] + "_paint.tga" if f[:-4] + "_paint.tga" in have else None))
    _G["specs"] = pbr.source_specs(a.models, src, manifest, only={m[:-5] for m in meshes_sel}) if os.path.isdir(src) else {}
    _G["ends"] = end_masks(a.models, [m for m in meshes_sel if re.match(r"^\d{3}_", m)])
    _G["crease"] = crease_maps(a.models, [m for m in meshes_sel if re.match(r"^\d{3}_", m)])
    # one prim per texel hash: a texture two cars share (013 Minx and 000 Romero's trim) cannot carry either mesh's folds
    for t in list(_G["crease"]):
        h = rm.remix_hash(rm.read_tga(os.path.join(a.models, t)))
        twins = [f for f in files if f != t and f.endswith("_paint.tga") and os.path.getsize(os.path.join(a.models, f)) ==
                 os.path.getsize(os.path.join(a.models, t)) and rm.remix_hash(rm.read_tga(os.path.join(a.models, f))) == h]
        if twins:
            print(f"  crease bake dropped for {t}: same texels as {twins[0]}", flush=True); del _G["crease"][t]
    print(f"{len(units)} units from {len(meshes)} models, source materials for {len(_G['specs'])} textures "
          f"({time.time() - t0:.0f} s)", flush=True)
    jobs = [(r, p, a.models, tex, a.preview) for r, p in units]
    if a.jobs > 1:
        import multiprocessing as mpc
        results = []
        with mpc.get_context("fork").Pool(a.jobs) as pool:
            for i, r in enumerate(pool.imap_unordered(write_unit, jobs, chunksize=2)):
                results.append(r)
                if (i + 1) % 100 == 0: print(f"  {i + 1} / {len(jobs)} units, {time.time() - t0:.0f} s", flush=True)
    else:
        results = [write_unit(j) for j in jobs]
    entries = [e for r in results for e in r] + fleet_entries()
    mine ={e["hash"] for e in entries}
    # Drop every prim this tool wrote before, keep the tiles and signs. Ours: the hashes in
    # <mod>/model_prims.txt (written below), and the older car prims, which had no normal
    # map and a metallic texture or the 0.2 paint constant (tile prims always have one).
    listed = os.path.join(a.mod, "model_prims.txt")
    before = set(open(listed).read().split()) if os.path.exists(listed) else set()
    def ours(h, block):
        return h in mine or h in before or ("normalmap_texture" not in block and
                                            ("metallic_texture" in block or "metallic_constant = 0.2\n" in block))
    kept = [m.group(0) for m in PRIM.finditer(text) if not ours(m.group(1), m.group(0))]
    open(listed, "w").write("\n".join(sorted(mine)) + "\n")
    start = text.index('over "Looks"'); start = text.index("{", start) + 2
    prims, seen = [], set()
    for e in sorted(entries, key=lambda e: e["file"]):
        if e["hash"] in seen: continue
        seen.add(e["hash"]); prims.append(e["prim"])
    text = text[:start] + "\n".join(kept + prims) + "    }\n}\n"
    open(usda, "w", encoding="utf-8", newline="\n").write(text)
    prims_all, refs, problems, _ = rm.validate(a.mod)
    tot = {}
    for e in {e["hash"]: e for e in entries}.values():
        for k, v in e["sizes"].items(): tot[k] = tot.get(k, 0) + v
    kinds = {}
    for e in entries: kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    n_norm = sum(1 for e in {e["hash"]: e for e in entries}.values() if "n" in e["sizes"])
    n_emit = sum(1 for e in {e["hash"]: e for e in entries}.values() if "e" in e["sizes"])
    if a.report:
        json.dump([{k: v for k, v in e.items() if k != "prim"} for e in entries], open(a.report, "w"), indent=0)
    print(f"{len(seen)} model prims ({kinds}); {n_norm} normal maps, {tot.get('m', 0) and sum(1 for e in entries if 'm' in e['sizes'])} "
          f"metallic maps, {sum(1 for e in entries if 'r' in e['sizes'])} roughness maps, {n_emit} emissive; bytes by map "
          f"{ {k: round(v / 1e6, 1) for k, v in tot.items()} } MB, total {sum(tot.values()) / 1e6:.1f} MB; {len(kept)} other prims "
          f"kept, {len(prims_all)} in the layer; {time.time() - t0:.0f} s; validation: {'ok' if not problems else problems[:5]}")


if __name__ == "__main__":
    main()
