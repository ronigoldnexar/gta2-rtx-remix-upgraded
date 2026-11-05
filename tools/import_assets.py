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

def pack_str(s, n):
    b = s.encode("utf-8")[: n - 1]
    return b + b"\0" * (n - len(b))

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
    def image_tga(img_index):
        tag = f"{name}_{img_index}.tga"
        out = os.path.join(out_dir, tag)
        if tag not in images_by_tag:
            images_by_tag[tag] = load_image(img_index)
        if not os.path.exists(out):
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
        if not os.path.exists(out):
            write_tga(Image.new("RGBA", (4, 4), rgba), out)
        return tag
    for mi, mat in enumerate(g.get("materials", [])):
        pbr = mat.get("pbrMetallicRoughness", {})
        if mat.get("name") in overrides:
            tag = f"{name}_{mat['name']}{'_paint' if is_paint(mat) else ''}.tga"
            out = os.path.join(out_dir, tag)
            if not os.path.exists(out):
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
    mesh_groups = []      # per glTF mesh: the list of our mesh indices
    for m in g.get("meshes", []):
        group = []
        for prim in m["primitives"]:
            if prim.get("mode", 4) != 4: continue
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
    def read_anims(gg, bb, node_map, strip_root, rename=None):
        out = []
        for a in gg.get("animations", []):
            channels = []
            aname = rename or a.get("name", f"anim{len(out)}")
            for ch in a["channels"]:
                sm = a["samplers"][ch["sampler"]]
                times = [t[0] for t in accessor(gg, bb, sm["input"])]
                values = accessor(gg, bb, sm["output"])
                path = {"translation": 0, "rotation": 1, "scale": 2}.get(ch["target"]["path"])
                if path is None or "node" not in ch["target"]: continue
                target = ch["target"]["node"]
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
        anims += read_anims(gg, bb, by_name, extra.get("strip_root", entry.get("strip_root")), extra.get("name"))

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
            extras.append((n.get("name", f"node{i}") + "+", i, [0, 0, 0], [0, 0, 0, 1], [1, 1, 1], extra))
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
                run_stride=round(strides.get("run", 0.0) * scale, 4))

if __name__ == "__main__":
    manifest = json.load(open(sys.argv[1]))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    src_dir = os.path.dirname(os.path.abspath(sys.argv[1]))
    report = []
    for entry in manifest["models"]:
        report.append(import_model(entry, src_dir, out_dir))
        print(report[-1])
    # The models list goes out without the import-only lists (the renderer's
    # manifest reader takes every "name" in it for a model file).
    models_out = [{k: v for k, v in e.items() if k != "animations_from"} for e in manifest["models"]]
    json.dump({"models": models_out, "cars": manifest.get("cars", {}), "pedestrian": manifest.get("pedestrian", ""),
               "pedestrians": manifest.get("pedestrians", []),
               "props": manifest.get("props", {}), "objects": manifest.get("objects", {}),
               "objects_yaw": manifest.get("objects_yaw", {}), "imported": report},
              open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
