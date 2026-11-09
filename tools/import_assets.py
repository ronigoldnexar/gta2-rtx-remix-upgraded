#!/usr/bin/env python3
"""Imports glTF binary (.glb) models into the renderer's own model format.

The renderer must not carry a glTF parser, a PNG decoder or a JSON reader into
a 32-bit game process, so the import happens here, once, and the DLL reads a
flat little-endian file:

    GMSH <u32 version=2> <u32 nodes> <u32 meshes> <u32 animations> <u32 skins>
    node     : name[32] parent(i32) t[3] r[4] s[3] mesh(i32)         (f32 each)
    mesh     : vertices(u32) indices(u32) texture[64] skin(i32)
               vertices: x y z nx ny nz u v (f32 x 8) ...
               if skin >= 0: per vertex joints u16[4] weights f32[4] ...
               indices: u32 ...
    animation: name[32] channels(u32)
               channel: node(i32) path(u32: 0 T 1 R 2 S) keys(u32) times f32[keys] values f32[keys*(3|4|3)]
    skin     : joints(u32) jointNode i32[joints] inverseBind f32[16*joints]

    Version 1 files (no skins, no skin field on meshes) are still read by the DLL.

Textures are written beside it as 32-bit uncompressed TGA (the one format the
renderer already reads), vertically flipped as TGA expects. A manifest maps the
game's objects to models.

    import_assets.py <manifest.json> <out dir>

The manifest lists {"name": ..., "glb": ..., "scale": ...} entries; each glb's
texture is taken from its own images (a material with only a colour factor
gets a 4x4 texture of that colour). Any glb with textures and node-animated
or skinned rigs works.

Cars. The manifest's "cars" object maps the game's vehicles to models:

    "cars": {"by_model": {"0": "romero", "12": "cop_car"},   # the vehicle's model number (CARI order)
             "by_sprite": {"45": "taxi"}}                     # or its car sprite number

The renderer reads each vehicle's model number from the game and looks it up
here; a vehicle neither map names is built from its own sprite at run time
(dll/src/car_bodies.cpp). A car model's painted parts should use a material
named "paint" (or listed in the entry's "paint_materials"): its texture is
written with "_paint" in the name and multiplied by the car's own colour in
the game, so keep the paint light and neutral (near white) in the model.
Models face +z with x across; "forward": "-z" in the entry says otherwise.
Keep a car under 12000 vertices and its textures at 1024 or less.
"""
import json, os, struct, sys

def load_glb(path):
    """A .glb, or a .gltf with its .bin beside it: returns the JSON and the (first) buffer."""
    if path.lower().endswith(".gltf"):
        g = json.load(open(path))
        buf = g["buffers"][0]
        uri = buf.get("uri", "")
        if uri.startswith("data:"):
            import base64
            binary = base64.b64decode(uri.split(",", 1)[1])
        else:
            binary = open(os.path.join(os.path.dirname(path), uri), "rb").read()
        return g, binary
    with open(path, "rb") as f:
        magic, ver, length = struct.unpack("<III", f.read(12))
        assert magic == 0x46546C67, "not a glb"
        chunks = {}
        while f.tell() < length:
            clen, ctype = struct.unpack("<II", f.read(8))
            chunks[ctype] = f.read(clen)
    g = json.loads(chunks[0x4E4F534A])
    binary = chunks.get(0x004E4942, b"")
    return g, binary

def write_tga(im, path, max_size=1024):
    """32-bit uncompressed TGA, bottom-up, no larger than max_size on a side."""
    im = im.convert("RGBA")
    if max(im.size) > max_size:
        f = max_size / max(im.size)
        im = im.resize((max(1, int(im.size[0] * f)), max(1, int(im.size[1] * f))))
    w, h = im.size
    px = im.tobytes()
    rows = [px[y * w * 4:(y + 1) * w * 4] for y in range(h)][::-1]
    out = bytearray()
    for row in rows:
        for i in range(0, len(row), 4):
            out += bytes((row[i + 2], row[i + 1], row[i], row[i + 3]))
    with open(path, "wb") as f:
        f.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(out)

CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

def accessor(g, binary, index):
    a = g["accessors"][index]
    bv = g["bufferViews"][a["bufferView"]]
    fmt, size = CT[a["componentType"]]
    n = NC[a["type"]]
    stride = bv.get("byteStride", size * n)
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    out = []
    for i in range(a["count"]):
        off = base + i * stride
        out.append(struct.unpack_from("<" + fmt * n, binary, off))
    norm = a.get("normalized", False)
    if norm and fmt in "Bb":
        out = [tuple(v / 255.0 for v in t) for t in out]
    if norm and fmt in "Hh":
        out = [tuple(v / 65535.0 for v in t) for t in out]
    return out

_LOCO_CACHE = {}   # (clip glb, reference glb) -> locomotion_meta.tables, unscaled
_HIP_CACHE = {}

def pack_str(s, n):
    b = s.encode("utf-8")[: n - 1]
    return b + b"\0" * (n - len(b))

# ASSET-PEDS: a pedestrian's clothes in two zones the renderer tints apart, the top
# (torso and arms) and the bottom (hips and legs), so a GTA2 ped type's shirt and
# trousers both come out in the sprite's own colours. A body triangle's zone is the
# bone class that carries most of its weight; feet (shoes), head and hands are left
# alone. The clothing texels (not skin, by the classic RGB rule) go to a "_paint" copy
# made neutral grey with its own shading kept (mean PED_ZONE_REF per zone), so the
# tint is simply the wanted colour over PED_ZONE_REF; the original zone colours are
# reported as zone_rgb_t/_b (and the hair's as zone_rgb_h) for an untinted draw.
PED_ZONE_REF = 128.0

def ped_joint_class(name):
    n = (name or "").lower()
    if any(k in n for k in ("foot", "toe", "head", "ponytail", "hair")): return -1
    if any(k in n for k in ("thigh", "calf", "pelvis")): return 1
    if any(k in n for k in ("spine", "neck", "clavicle", "upperarm", "forearm", "hand", "finger")): return 0
    return 1 if n.strip() in ("bip01",) else -1

def ped_tri_zone(skins, joint_class):
    acc = {-1: 0.0, 0: 0.0, 1: 0.0}
    for joints, weights in skins:
        for j, w in zip(joints, weights):
            acc[joint_class.get(j, -1)] += w
    return max(acc, key=acc.get)

def ped_island_zones(idx, skins, joint_class):
    """A zone per vertex from its UV island (the triangles joined by shared vertices: one
    garment piece), the island's zone the area-free majority of its triangles' zones, so a
    shirt's tails or a coat's skirt (weighted to the thighs) stay with the top."""
    parent = list(range(len(skins)))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    tris = [idx[k:k + 3] for k in range(0, len(idx) - 2, 3)]
    for t in tris:
        ra = find(t[0])
        for v in t[1:]:
            rb = find(v)
            if rb != ra: parent[rb] = ra
    votes = {}
    for t in tris:
        z = ped_tri_zone([skins[i] for i in t], joint_class)
        c = votes.setdefault(find(t[0]), {-1: 0, 0: 0, 1: 0}); c[z] += 1
    zone_of = {root: max(c, key=c.get) for root, c in votes.items()}
    return [zone_of.get(find(i), -1) for i in range(len(skins))]

def ped_zone_split(entry, g, binary, tex_by_material, overrides, src_dir, out_dir):
    import numpy as np
    from PIL import Image, ImageDraw
    nodes = g.get("nodes", [])
    joint_class = {}
    for sk in g.get("skins", [])[:1]:
        for k, j in enumerate(sk["joints"]): joint_class[k] = ped_joint_class(nodes[j].get("name", ""))
    tmax = int(entry.get("texture_max", 1024))
    split, rgb = {}, [None, None, None]
    # the avatar's skin tone: the median chromaticity of the face texture's skin texels
    skin_ref = None
    for mi, mat in enumerate(g.get("materials", [])):
        if (mat.get("name") or "").endswith("_head") and mi in tex_by_material:
            try:
                h = np.asarray(Image.open(os.path.join(out_dir, tex_by_material[mi])).convert("RGB")).astype(np.float32)
                hr, hg, hb = h[..., 0], h[..., 1], h[..., 2]
                hm = (hr > 80) & (hg > 35) & (hb > 15) & (hr > hg) & (hr > hb) & (hr - hb > 25)
                if hm.sum() > 64:
                    hs = np.maximum(h.sum(axis=2), 1.0)[hm]
                    skin_ref = np.array([np.median(hr[hm] / hs), np.median(hg[hm] / hs)], np.float32)
            except OSError:
                pass
    for mat_name in entry.get("tint_clothing", []):
        for mi, mat in enumerate(g.get("materials", [])):
            if mat.get("name") != mat_name or mi not in tex_by_material: continue
            tag = tex_by_material[mi]
            src = os.path.join(src_dir, overrides[mat_name]) if mat_name in overrides else os.path.join(out_dir, tag)
            im = Image.open(src).convert("RGBA")
            if max(im.size) > tmax:
                f = tmax / max(im.size); im = im.resize((max(1, int(im.size[0] * f)), max(1, int(im.size[1] * f))))
            W, H = im.size
            # texel zones: the material's triangles drawn in UV space, 1 top, 2 bottom, 3 other
            zmap = Image.new("L", (W, H), 0); dz = ImageDraw.Draw(zmap)
            for m in g.get("meshes", []):
                for prim in m["primitives"]:
                    if prim.get("material", -1) != mi or "JOINTS_0" not in prim["attributes"]: continue
                    uv = accessor(g, binary, prim["attributes"]["TEXCOORD_0"])
                    J = accessor(g, binary, prim["attributes"]["JOINTS_0"]); Wt = accessor(g, binary, prim["attributes"]["WEIGHTS_0"])
                    idx = [i[0] for i in accessor(g, binary, prim["indices"])]
                    vz = ped_island_zones(idx, [(J[i], Wt[i]) for i in range(len(uv))], joint_class)
                    for k in range(0, len(idx) - 2, 3):
                        t = idx[k:k + 3]
                        z = vz[t[0]]
                        val = {0: 1, 1: 2}.get(z, 3)
                        pts = [(uv[i][0] * W, uv[i][1] * H) for i in t]
                        dz.polygon(pts, fill=val, outline=val)
            Z = np.asarray(zmap)
            a = np.asarray(im).astype(np.float32)
            r_, g_, b_ = a[..., 0], a[..., 1], a[..., 2]
            mx = a[..., :3].max(axis=2); mn = a[..., :3].min(axis=2)
            skin = (r_ > 80) & (g_ > 35) & (b_ > 15) & ((mx - mn) > 12) & (np.abs(r_ - g_) > 12) & (r_ > g_) & (r_ > b_) & (r_ - b_ > 25)
            if skin_ref is not None:
                # and near the face's own chromaticity: a red shirt passes the RGB rule, not this
                ssum = np.maximum(a[..., :3].sum(axis=2), 1.0)
                chroma = np.stack([r_ / ssum, g_ / ssum], axis=-1)
                skin &= np.abs(chroma - skin_ref).max(axis=-1) < 0.06
            for keep in entry.get("zone_keep_rgb", []):   # a garment that must not be tinted (a vest's print, a belt)
                skin |= (np.abs(a[..., :3] - np.array(keep[:3], np.float32)).max(axis=2) < keep[3])
            cloth = ~skin & (a[..., 3] > 0) & ((Z == 1) | (Z == 2))
            if cloth.sum() < 0.05 * cloth.size:
                print(f"  ped_zones: {tag}: only {int(cloth.sum())} clothing texels, not split"); continue
            L = 0.299 * r_ + 0.587 * g_ + 0.114 * b_
            grey = np.zeros_like(L)
            for zi, zv in ((0, 1), (1, 2)):
                sel = cloth & (Z == zv)
                if sel.sum() < 64: continue
                lz = L[sel]; top = a[..., :3][sel][lz >= np.median(lz)]
                rgb[zi] = [round(float(v), 1) for v in top.mean(axis=0)]
                # the shading kept, its contrast eased a little so a print or stripe
                # does not dominate a recoloured shirt
                mean = float(lz.mean())
                rel = np.clip(L / max(mean, 4.0), 0.0, 3.0)
                rel = 1.0 + (rel - 1.0) * float(entry.get("zone_contrast", 0.75))
                grey = np.where(sel, np.clip(rel * PED_ZONE_REF, 0, 255), grey)
            paint = np.zeros_like(a); paint[..., 0] = paint[..., 1] = paint[..., 2] = grey
            paint[..., 3] = np.where(cloth, 255, 0)
            rest = a.copy(); rest[..., 3] = np.where(cloth, 0, 255)
            paint_tag = tag[:-4] + "_paint.tga"
            write_tga(Image.fromarray(paint.astype(np.uint8), "RGBA"), os.path.join(out_dir, paint_tag), tmax)
            write_tga(Image.fromarray(rest.astype(np.uint8), "RGBA"), os.path.join(out_dir, tag), tmax)
            split[tag] = paint_tag
            print(f"  ped_zones: {tag}: {int(cloth.sum())} clothing texels (top {int((cloth & (Z == 1)).sum())}, bottom {int((cloth & (Z == 2)).sum())}); top {rgb[0]} bottom {rgb[1]}")
    # the hair: the mean of the opaque texels of the hair-card texture
    for mi, mat in enumerate(g.get("materials", [])):
        if "opacity" in (mat.get("name") or "") and mi in tex_by_material:
            try:
                h = np.asarray(Image.open(os.path.join(out_dir, tex_by_material[mi])).convert("RGBA")).astype(np.float32)
                sel = h[..., 3] > 128
                if sel.sum() > 16: rgb[2] = [round(float(v), 1) for v in h[..., :3][sel].mean(axis=0)]
            except OSError:
                pass
    return split, {"joint_class": joint_class, "rgb": rgb if split else None}

def import_model(entry, src_dir, out_dir):
    g, binary = load_glb(os.path.join(src_dir, entry["glb"]))
    name = entry["name"]
    # Textures: each material's base colour image, written as TGA beside the
    # model (downscaled to 1k at most: the game is a 32-bit process). A model
    # with no material at all gets a flat white.
    from PIL import Image
    import io
    src_glb = os.path.join(src_dir, entry["glb"])
    tex_by_material = {}
    images_by_tag = {}
    def load_image(img_index):
        img = g["images"][img_index]
        if "uri" in img and not img["uri"].startswith("data:"):
            return Image.open(os.path.join(os.path.dirname(src_glb), img["uri"]))
        if "uri" in img:
            import base64
            return Image.open(io.BytesIO(base64.b64decode(img["uri"].split(",", 1)[1])))
        bv = g["bufferViews"][img["bufferView"]]
        off = bv.get("byteOffset", 0)
        return Image.open(io.BytesIO(binary[off: off + bv["byteLength"]]))
    glb_mtime = os.path.getmtime(src_glb)
    def stale(out):
        # A texture written by an earlier import of this model is reused only
        # while the glb is older than it: a regenerated model whose images
        # come in another order (the pay phone, after gen_code_objects.py
        # changed) was otherwise drawn with the old pictures on the new meshes.
        return not os.path.exists(out) or os.path.getmtime(out) < glb_mtime
    def image_tga(img_index):
        tag = f"{name}_{img_index}.tga"
        out = os.path.join(out_dir, tag)
        if tag not in images_by_tag:
            images_by_tag[tag] = load_image(img_index)
        if stale(out):
            write_tga(images_by_tag[tag], out, int(entry.get("texture_max", 1024)))
        return tag
    overrides = entry.get("material_textures", {})
    # A car's paint: materials named here (or whose name says "paint"/"body")
    # get "_paint" in their texture's name, which the renderer multiplies by
    # the car's own colour. Keep such a texture light and neutral.
    paint_names = [n.lower() for n in entry.get("paint_materials", [])]
    def is_paint(mat):
        n = (mat.get("name") or "").lower()
        if paint_names: return n in paint_names
        return n in ("paint", "body", "carpaint", "car_paint") or n.startswith("paint_")
    def solid_tga(mi, mat):
        """a material with only a base colour factor: a 4x4 texture of that colour"""
        f = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        rgba = tuple(max(0, min(255, int(round(c * 255)))) for c in f[:4]) + (255,) * (4 - len(f[:4]))
        tag = f"{name}_m{mi}{'_paint' if is_paint(mat) else ''}.tga"
        out = os.path.join(out_dir, tag)
        if stale(out):
            write_tga(Image.new("RGBA", (4, 4), rgba), out)
        return tag
    for mi, mat in enumerate(g.get("materials", [])):
        pbr = mat.get("pbrMetallicRoughness", {})
        if mat.get("name") in overrides:
            tag = f"{name}_{mat['name']}{'_paint' if is_paint(mat) else ''}.tga"
            out = os.path.join(out_dir, tag)
            if stale(out):
                write_tga(Image.open(os.path.join(src_dir, overrides[mat["name"]])), out, int(entry.get("texture_max", 1024)))
            tex_by_material[mi] = tag
        elif "baseColorTexture" in pbr:
            tex = g["textures"][pbr["baseColorTexture"]["index"]]
            if "source" in tex:
                tag = image_tga(tex["source"])
                if is_paint(mat):
                    # the same picture under a name that marks it as paint
                    paint_tag = tag[:-4] + "_paint.tga"
                    paint_out = os.path.join(out_dir, paint_tag)
                    if not os.path.exists(paint_out):
                        import shutil
                        shutil.copyfile(os.path.join(out_dir, tag), paint_out)
                    tag = paint_tag
                tex_by_material[mi] = tag
        elif "baseColorFactor" in pbr:
            tex_by_material[mi] = solid_tga(mi, mat)
    texture_name = tex_by_material.get(0, "")

    # A baked texture (one picture for the whole car, as image-to-3D makes
    # them) with "paint_split": the texels within a colour distance of the
    # entry's paint_rgb are the paint. They go to a second copy of the texture
    # named _paint (the rest transparent), the original keeps the rest (the
    # paint transparent), and every primitive that uses it is written twice,
    # once with each; alpha-tested, the two draws make the car again, and the
    # renderer's paint tint touches only the _paint half. paint_rgb (the default
    # sprite's paint) is what the game's live paint is measured against.
    split_tags = {}
    if entry.get("paint_split") and entry.get("paint_rgb"):
        ref = [float(c) for c in entry["paint_rgb"]]
        ref_l = max(1.0, sum(ref) / 3)
        ref_c = [c / ref_l for c in ref]
        ref_sat = max(ref) - min(ref)
        tol = float(entry.get("paint_tolerance", 0.24))
        import numpy as np
        for tag, im in list(images_by_tag.items()):
            im = im.convert("RGBA")
            tmax = int(entry.get("texture_max", 1024))
            if max(im.size) > tmax:
                f = tmax / max(im.size)
                im = im.resize((max(1, int(im.size[0] * f)), max(1, int(im.size[1] * f))))
            a = np.asarray(im).astype(np.float32)
            rgb = a[..., :3]
            l = rgb.mean(axis=2)
            # Hue and saturation, which shading leaves alone: the paint is every
            # texel of the paint's hue when the paint has one, else every light
            # neutral texel (a white or grey car; its chrome comes along).
            mx = rgb.max(axis=2); mn = rgb.min(axis=2)
            sat = (mx - mn) / np.maximum(mx, 1.0)
            r_, g__, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
            delta = np.maximum(mx - mn, 1e-6)
            hue = np.where(mx == r_, (g__ - b_) / delta % 6, np.where(mx == g__, (b_ - r_) / delta + 2, (r_ - g__) / delta + 4)) * 60.0
            rm, rn = max(ref), min(ref)
            ref_s = (rm - rn) / max(rm, 1.0)
            rd = max(rm - rn, 1e-6)
            ref_h = ((ref[1] - ref[2]) / rd % 6 if rm == ref[0] else ((ref[2] - ref[0]) / rd + 2 if rm == ref[1] else (ref[0] - ref[1]) / rd + 4)) * 60.0
            hue_tol = float(entry.get("paint_hue_tolerance", 28.0))
            if ref_s >= 0.22:
                dh = np.abs((hue - ref_h + 180.0) % 360.0 - 180.0)
                mask = (sat >= 0.22) & (dh < hue_tol) & (mx > 45)
            else:
                mask = (sat < 0.20) & (mx > 110)
            n = int(mask.sum())
            if n < 0.02 * mask.size:
                print(f"  paint_split: {tag}: only {n} texels near {entry['paint_rgb']}, not split")
                continue
            # paint_rgb stays the default sprite's paint, measured the way the renderer
            # measures the live one: the tint is then live / default, which is 1 for a
            # car in its default paint whatever the texture's own shade, and shifts a
            # repaint's hue by the same ratio the game applied to the sprite. The
            # texture's own paint is only reported.
            lit = l[mask]
            keep = lit >= np.median(lit)
            top = rgb[mask][keep]
            texture_paint = [round(float(v), 1) for v in top.mean(axis=0)]
            paint = a.copy(); paint[..., 3] = np.where(mask, 255, 0)
            rest = a.copy(); rest[..., 3] = np.where(mask, 0, 255)
            paint_tag = tag[:-4] + "_paint.tga"
            write_tga(Image.fromarray(paint.astype(np.uint8), "RGBA"), os.path.join(out_dir, paint_tag), tmax)
            write_tga(Image.fromarray(rest.astype(np.uint8), "RGBA"), os.path.join(out_dir, tag), tmax)
            split_tags[tag] = paint_tag
            print(f"  paint_split: {tag}: {n} of {mask.size} texels are paint; texture paint {texture_paint}, reference {entry['paint_rgb']}")

    # A person's clothing ("tint_clothing": the names of the materials whose
    # textures hold the clothes, typically the Rocketbox body texture): the
    # texels that are not skin go to a "_paint" copy, the skin stays in the
    # original, and the renderer tints the paint half with a pedestrian type's
    # colour (a gang's, a uniform's). The clothing's own mean colour is written
    # back as paint_rgb, so the tint is the remap colour over it.
    zone_split, zone_info = ped_zone_split(entry, g, binary, tex_by_material, overrides, src_dir, out_dir) \
        if entry.get("ped_zones") else ({}, {})
    for mat_name in ([] if entry.get("ped_zones") else entry.get("tint_clothing", [])):
        for mi, mat in enumerate(g.get("materials", [])):
            if mat.get("name") != mat_name or mi not in tex_by_material: continue
            tag = tex_by_material[mi]
            if tag.endswith("_paint.tga"): continue
            src = os.path.join(src_dir, overrides[mat_name]) if mat_name in overrides else os.path.join(out_dir, tag)
            im = Image.open(src).convert("RGBA")
            tmax = int(entry.get("texture_max", 1024))
            if max(im.size) > tmax:
                f = tmax / max(im.size)
                im = im.resize((max(1, int(im.size[0] * f)), max(1, int(im.size[1] * f))))
            import numpy as np
            a = np.asarray(im).astype(np.float32)
            r_, g__, b_ = a[..., 0], a[..., 1], a[..., 2]
            mx = a[..., :3].max(axis=2); mn = a[..., :3].min(axis=2)
            # Skin: the classic RGB rule (reddish, not grey, not dark), widened a
            # little for shadowed skin; everything else on the body is clothing.
            skin = (r_ > 80) & (g__ > 35) & (b_ > 15) & ((mx - mn) > 12) & (np.abs(r_ - g__) > 12) & (r_ > g__) & (r_ > b_) & (r_ - b_ > 25)
            clothing = ~skin & (a[..., 3] > 0)
            n = int(clothing.sum())
            if n < 0.05 * clothing.size:
                print(f"  tint_clothing: {tag}: only {n} clothing texels, not split")
                continue
            l = a[..., :3].mean(axis=2)
            lit = l[clothing]
            top = a[..., :3][clothing][lit >= np.median(lit)]
            entry["paint_rgb"] = [round(float(v), 1) for v in top.mean(axis=0)]
            paint = a.copy(); paint[..., 3] = np.where(clothing, 255, 0)
            rest = a.copy(); rest[..., 3] = np.where(clothing, 0, 255)
            paint_tag = tag[:-4] + "_paint.tga"
            write_tga(Image.fromarray(paint.astype(np.uint8), "RGBA"), os.path.join(out_dir, paint_tag), tmax)
            write_tga(Image.fromarray(rest.astype(np.uint8), "RGBA"), os.path.join(out_dir, tag), tmax)
            split_tags[tag] = paint_tag
            print(f"  tint_clothing: {tag}: {n} of {clothing.size} texels are clothing; clothing colour {entry['paint_rgb']}")

    # Nodes whose names match an exclude pattern (variants such as "_aged",
    # "_rust") are dropped; a node named by "nodes_only" keeps only those.
    exclude = entry.get("nodes_exclude", [])
    only = entry.get("nodes_only", [])
    def node_wanted(n):
        nm = n.get("name", "")
        if only and not any(o in nm for o in only): return False
        return not any(e in nm for e in exclude)

    # A Direct3D 9 draw from user memory copies the whole vertex range, and
    # Wine's Direct3D fails (a null copy) past a few tens of thousands of
    # vertices in one call, so every primitive is split into pieces of at most
    # max_vertices, re-indexed. Pieces are extra meshes on the same node.
    max_vertices = int(entry.get("max_vertices", 12000))
    def split(verts, idx):
        pieces = []
        for start in range(0, len(idx), max_vertices * 3 // 2):
            chunk = idx[start:start + max_vertices * 3 // 2]
            remap = {}; pv = []; pi = []
            for i in chunk:
                if i not in remap:
                    remap[i] = len(pv); pv.append(verts[i])
                pi.append(remap[i])
            # a chunk can still exceed max_vertices when the indices are all distinct; halve it then
            if len(pv) > max_vertices and len(chunk) > 3:
                half = (len(chunk) // 6) * 3
                pieces += split(verts, chunk[:half]) + split(verts, chunk[half:])
            else:
                pieces.append((pv, pi))
        return pieces

    meshes = []           # (vertices, indices, texture)
    mesh_zone = {}        # ASSET-PEDS: our mesh index -> "t"/"b" for a ped's clothing zones
    mesh_groups = []      # per glTF mesh: the list of our mesh indices
    for m in g.get("meshes", []):
        group = []
        for prim in m["primitives"]:
            if prim.get("mode", 4) != 4: continue
            # "materials_exclude": primitives of these materials are left out (a prisoner's hard hat)
            if (g.get("materials", [{}] * (prim.get("material", 0) + 1))[prim.get("material", 0)].get("name") if "material" in prim else None) \
                    in entry.get("materials_exclude", []): continue
            pos = accessor(g, binary, prim["attributes"]["POSITION"])
            nrm = accessor(g, binary, prim["attributes"]["NORMAL"]) if "NORMAL" in prim["attributes"] else [(0, 1, 0)] * len(pos)
            uv = accessor(g, binary, prim["attributes"]["TEXCOORD_0"]) if "TEXCOORD_0" in prim["attributes"] else [(0, 0)] * len(pos)
            verts = [(p[0], p[1], p[2], n[0], n[1], n[2], t[0], t[1]) for p, n, t in zip(pos, nrm, uv)]
            idx = [i[0] for i in accessor(g, binary, prim["indices"])] if "indices" in prim else list(range(len(pos)))
            tex = tex_by_material.get(prim.get("material", -1), texture_name)
            # Skinning: four joints and weights per vertex, carried beside the vertex.
            skinw = None
            if "JOINTS_0" in prim["attributes"] and "WEIGHTS_0" in prim["attributes"]:
                joints = accessor(g, binary, prim["attributes"]["JOINTS_0"])
                weights = accessor(g, binary, prim["attributes"]["WEIGHTS_0"])
                skinw = [(tuple(int(x) for x in j), tuple(float(x) for x in w)) for j, w in zip(joints, weights)]
                verts = [v + (sw,) for v, sw in zip(verts, skinw)]
            for pv, pi in (split(verts, idx) if len(verts) > max_vertices else [(verts, idx)]):
                group.append(len(meshes))
                meshes.append((pv, pi, tex))
                if tex in split_tags:
                    group.append(len(meshes))
                    meshes.append((pv, pi, split_tags[tex]))
                if tex in zone_split and skinw is not None:
                    # ASSET-PEDS: the clothing half twice, the top's triangles and the
                    # bottom's (by UV island, as the texture was split), each its own
                    # mesh so the renderer tints them apart.
                    vz = ped_island_zones(pi, [v[8] for v in pv], zone_info["joint_class"])
                    for zone, zi in (("t", 0), ("b", 1)):
                        tri = [pi[k:k + 3] for k in range(0, len(pi) - 2, 3) if vz[pi[k]] == zi]
                        if not tri: continue
                        # only the vertices the zone uses (each is skinned on its own every pose)
                        used = {}; zv = []; zi_ = []
                        for t in tri:
                            for i in t:
                                if i not in used: used[i] = len(zv); zv.append(pv[i])
                                zi_.append(used[i])
                        group.append(len(meshes)); mesh_zone[len(meshes)] = zone
                        meshes.append((zv, zi_, zone_split[tex]))
        mesh_groups.append(group)
    # Which skin a mesh uses comes from the node that carries it.
    mesh_skin = {}
    for n in nodes_all if False else g.get("nodes", []):
        if "mesh" in n and "skin" in n and n["mesh"] < len(mesh_groups):
            for mi in mesh_groups[n["mesh"]]: mesh_skin[mi] = n["skin"]
    skins = []
    for sk in g.get("skins", []):
        ibm = accessor(g, binary, sk["inverseBindMatrices"]) if "inverseBindMatrices" in sk else [tuple([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])] * len(sk["joints"])
        skins.append((list(sk["joints"]), [list(m) for m in ibm]))

    nodes = g.get("nodes", [])
    nodes_all = nodes
    parent = [-1] * len(nodes)
    for i, n in enumerate(nodes):
        for c in n.get("children", []): parent[c] = i
    anims = []
    stride = [0.0]   # the ground a stripped walk covers per cycle, model units
    strides = {}     # the same per animation name (walk, run, ...), model units
    target_hip = next((n.get("translation", [0, 0, 0])[1] for n in nodes if n.get("name") == "Bip01"), 0.0)
    def read_anims(gg, bb, node_map, strip_root, rename=None, retarget=False, max_len=None):
        """retarget (QB-20, tools/locomotion_meta.py): a mocap clip from another body on the
        same Biped skeleton keeps only its rotations and its root's motion, the root's
        height and the ground it covers scaled by the two hip heights, so the avatar keeps
        its own bones."""
        out = []
        ratio = 1.0
        if retarget:
            src_hip = next((n.get("translation", [0, 0, 0])[1] for n in gg["nodes"] if n.get("name") == "Bip01"), 0.0)
            ratio = target_hip / src_hip if src_hip > 1e-6 and target_hip > 1e-6 else 1.0
        for a in gg.get("animations", []):
            channels = []
            aname = rename or a.get("name", f"anim{len(out)}")
            for ch in a["channels"]:
                sm = a["samplers"][ch["sampler"]]
                times = [t[0] for t in accessor(gg, bb, sm["input"])]
                values = accessor(gg, bb, sm["output"])
                if max_len and times and times[-1] > max_len:   # a long capture cut to its first max_len seconds
                    keep = max(2, sum(1 for t in times if t <= max_len))
                    times, values = times[:keep], values[:keep]
                path = {"translation": 0, "rotation": 1, "scale": 2}.get(ch["target"]["path"])
                if path is None or "node" not in ch["target"]: continue
                target = ch["target"]["node"]
                if retarget and path == 0 and gg["nodes"][target].get("name") != strip_root: continue
                if retarget and path == 0:
                    values = [(v[0] * ratio, v[1] * ratio, v[2] * ratio) for v in values]
                if node_map is not None:
                    nm = gg["nodes"][target].get("name")
                    if nm not in node_map: continue
                    target = node_map[nm]
                # A walk recorded with its ground motion: keep the body where it is
                # (x, z of the root held at the first key), the game moves him.
                if strip_root and path == 0 and gg["nodes"][ch["target"]["node"]].get("name") == strip_root:
                    x0, y0, z0 = values[0]
                    x1, _, z1 = values[-1]
                    covered = ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5
                    stride[0] = max(stride[0], covered)
                    strides[aname] = max(strides.get(aname, 0.0), covered)
                    values = [(x0, v[1], z0) for v in values]
                channels.append((target, path, times, values))
            out.append((aname, channels))
        return out
    anims += read_anims(g, binary, None, entry.get("strip_root"))
    by_name = {n.get("name"): i for i, n in enumerate(nodes)}
    for extra in entry.get("animations_from", []):
        gg, bb = load_glb(os.path.join(src_dir, extra["glb"]))
        anims += read_anims(gg, bb, by_name, extra.get("strip_root", entry.get("strip_root")), extra.get("name"),
                            extra.get("retarget", False), extra.get("max_len"))
    # The locomotion tables (tools/locomotion_meta.py) of the retargeted clips that name a
    # reference cycle ("ref": the clip name of the walk or run their phases are measured on).
    loco = []
    retargeted = {e.get("name"): e for e in entry.get("animations_from", []) if e.get("retarget")}
    if retargeted and target_hip > 1e-6:
        import locomotion_meta
        for cname, e in retargeted.items():
            if "ref" not in e or e["ref"] not in retargeted: continue
            key = (e["glb"], retargeted[e["ref"]]["glb"])
            if key not in _LOCO_CACHE:
                _LOCO_CACHE[key] = locomotion_meta.tables(os.path.join(src_dir, e["glb"]), os.path.join(src_dir, key[1]))
            d, ph = _LOCO_CACHE[key]
            src_hip = locomotion_meta.Clip(os.path.join(src_dir, e["glb"])).hip if key not in _HIP_CACHE else _HIP_CACHE[key]
            _HIP_CACHE[key] = src_hip
            k = target_hip / src_hip * float(entry.get("scale", 1.0))
            loco.append(locomotion_meta.encode(cname, [round(v * k, 4) for v in d], ph))

    # Every Biped-skeleton avatar gets the shared action clips (tools/gen_ped_clips.py
    # output and the Rocketbox crouch clips for the car climb) unless the entry names
    # its own, so a regenerated manifest keeps them.
    extra_from = list(entry.get("animations_from", []))
    extra_json = list(entry.get("animations_json", []))
    if "Bip01" in by_name and g.get("skins") and not extra_json:
        have = {a for a, _ in anims}
        for clip, glb in (("getin", "humans/rocketbox/anim/m_crouch_in.glb"), ("getout", "humans/rocketbox/anim/m_crouch_out.glb")):
            if clip not in have and os.path.exists(os.path.join(src_dir, glb)):
                gg, bb = load_glb(os.path.join(src_dir, glb))
                anims += read_anims(gg, bb, by_name, "Bip01", clip)
        if os.path.exists(os.path.join(src_dir, "humans/clips/ped_clips.json")):
            extra_json.append({"file": "humans/clips/ped_clips.json"})
    # Clips authored as JSON by tools/gen_ped_clips.py: {"clips": [{"name", "channels":
    # {joint name: {"rotation": {"times", "values"}, "translation": {...}}}]}, matched by joint name.
    for extra in extra_json:
        clips = json.load(open(os.path.join(src_dir, extra["file"])))["clips"]
        for clip in clips:
            if extra.get("only") and clip["name"] not in extra["only"]: continue
            channels = []
            for joint, paths in clip["channels"].items():
                if joint not in by_name: continue
                for pname, path in (("translation", 0), ("rotation", 1), ("scale", 2)):
                    if pname in paths:
                        channels.append((by_name[joint], path, list(paths[pname]["times"]),
                                         [tuple(v) for v in paths[pname]["values"]]))
            anims.append((clip["name"], channels))

    scale = float(entry.get("scale", 1.0))
    # Our nodes: the glTF nodes, then one extra child per additional primitive
    # of a node's mesh (the first primitive stays on the node itself).
    # The extra nodes go after all the glTF ones, so every index the file uses
    # (parents, skin joints, animation targets) stays a glTF node index.
    out_nodes = []
    extras = []
    for i, n in enumerate(nodes):
        t = n.get("translation", [0, 0, 0]); r = n.get("rotation", [0, 0, 0, 1]); sc = n.get("scale", [1, 1, 1])
        if "matrix" in n:
            m = n["matrix"]; t = [m[12], m[13], m[14]]
        group = mesh_groups[n["mesh"]] if "mesh" in n and n["mesh"] < len(mesh_groups) and node_wanted(n) else []
        out_nodes.append((n.get("name", f"node{i}"), parent[i], t, r, sc, group[0] if group else -1))
        for extra in group[1:]:
            # a clothing zone's mesh is marked in its node's name ("#pt" top, "#pb" bottom)
            ename = n.get("name", f"node{i}") + "+"
            if extra in mesh_zone: ename = ename[:26] + "#p" + mesh_zone[extra]
            extras.append((ename, i, [0, 0, 0], [0, 0, 0, 1], [1, 1, 1], extra))
    out_nodes += extras
    with open(os.path.join(out_dir, f"{name}.mesh"), "wb") as f:
        f.write(b"GMSH" + struct.pack("<IIIII", 2, len(out_nodes), len(meshes), len(anims), len(skins)))
        for nname, par, t, r, sc, mesh_index in out_nodes:
            f.write(pack_str(nname, 32))
            f.write(struct.pack("<i", par))
            f.write(struct.pack("<3f", *[v * scale for v in t]))
            f.write(struct.pack("<4f", *r))
            f.write(struct.pack("<3f", *sc))
            f.write(struct.pack("<i", mesh_index))
        for mi, (verts, idx, tex) in enumerate(meshes):
            skin = mesh_skin.get(mi, -1)
            f.write(struct.pack("<II", len(verts), len(idx)))
            f.write(pack_str(tex, 64))
            f.write(struct.pack("<i", skin))
            for v in verts:
                f.write(struct.pack("<8f", v[0] * scale, v[1] * scale, v[2] * scale, v[3], v[4], v[5], v[6], v[7]))
            if skin >= 0:
                for v in verts:
                    j, w = v[8] if len(v) > 8 else ((0, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))
                    f.write(struct.pack("<4H4f", *j, *w))
            f.write(struct.pack(f"<{len(idx)}I", *idx))
        for aname, channels in anims:
            f.write(pack_str(aname, 32))
            f.write(struct.pack("<I", len(channels)))
            for node, path, times, values in channels:
                f.write(struct.pack("<iII", node, path, len(times)))
                f.write(struct.pack(f"<{len(times)}f", *times))
                flat = []
                for v in values:
                    vv = list(v)
                    if path == 0: vv = [x * scale for x in vv]
                    flat += vv
                f.write(struct.pack(f"<{len(flat)}f", *flat))
        for joints, ibm in skins:
            f.write(struct.pack("<I", len(joints)))
            f.write(struct.pack(f"<{len(joints)}i", *joints))
            for m in ibm:
                # The inverse bind matrix carries the model's units: its translation row scales too.
                mm = list(m)
                mm[12] *= scale; mm[13] *= scale; mm[14] *= scale
                f.write(struct.pack("<16f", *mm))
    return dict(name=name, nodes=len(out_nodes), meshes=len(meshes), vertices=sum(len(v) for v, _, _ in meshes),
                animations=[a for a, _ in anims], textures=sorted(set(t for _, _, t in meshes)), skins=len(skins),
                forward=entry.get("forward", ""),
                # stride: the walk's own ground per cycle (the largest of all clips when there is no walk);
                # run_stride: the run's, 0 without a run clip.
                stride=round(strides.get("walk", stride[0]) * scale, 4),
                run_stride=round(strides.get("run", 0.0) * scale, 4),
                **({"loco": ";".join(loco)} if loco else {}),
                **({"ped_zones": 1, "zone_ref": PED_ZONE_REF, "zone_rgb_t": zone_info["rgb"][0], "zone_rgb_b": zone_info["rgb"][1],
                    "zone_rgb_h": zone_info["rgb"][2]} if zone_info.get("rgb") else {}))

if __name__ == "__main__":
    manifest = json.load(open(sys.argv[1]))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    src_dir = os.path.dirname(os.path.abspath(sys.argv[1]))
    # --only a,b,c: import just those models and keep the others' report entries
    # from the existing manifest in out_dir (a partial re-import).
    only = None
    if len(sys.argv) > 4 and sys.argv[3] == "--only":
        only = set(sys.argv[4].split(","))
    previous = {}
    if only:
        try:
            previous = {e["name"]: e for e in json.load(open(os.path.join(out_dir, "manifest.json"))).get("imported", [])}
        except (OSError, ValueError):
            previous = {}
    report = []
    for entry in manifest["models"]:
        if only and entry["name"] not in only and entry["name"] in previous:
            report.append(previous[entry["name"]]); continue
        report.append(import_model(entry, src_dir, out_dir))
        print(report[-1])
    # The models list goes out without the import-only lists (the renderer's
    # manifest reader takes every "name" in it for a model file).
    models_out = [{k: v for k, v in e.items() if k not in ("animations_from", "animations_json")} for e in manifest["models"]]
    json.dump({"models": models_out, "cars": manifest.get("cars", {}), "pedestrian": manifest.get("pedestrian", ""),
               "pedestrians": manifest.get("pedestrians", []),
               "props": manifest.get("props", {}), "objects": manifest.get("objects", {}),
               "objects_yaw": manifest.get("objects_yaw", {}), "objects_anim": manifest.get("objects_anim", {}),
               "ped_types": manifest.get("ped_types", []), "ped_remap_colours": manifest.get("ped_remap_colours", []), "ped_outfits": manifest.get("ped_outfits", []),
               "imported": report},
              open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
