#!/usr/bin/env python3
"""PBR maps for the 3D model textures (cars, props, code objects, avatars) under RTX Remix.

Every texture in assets/models that a manifest model's mesh names gets, besides its
albedo: a normal map, a roughness map, a metallic map (or constant) and, where
something should glow, an emissive mask. tools/remix_model_materials.py writes them
into the hash-keyed layer (one AperturePBR_Opacity prim per texture hash); this
module only makes the maps. Formats are what the runtime reads directly (see
docs/remix-materials.md, "Model PBR maps"):

* normal: tangent space, DirectX orientation (x along +u, y along +v, i.e. *down*
  the image), stored as unsigned octahedral in BC5. That is the AperturePBR default
  `encoding = octahedral`, which the MDL decodes exactly like `tangent_space_dx`
  (no green flip; AperturePBR_Normal.mdl), so a DirectX map goes in unchanged and an
  OpenGL one (glTF, Poly Haven `nor_gl`) has its green negated first.
* roughness and metallic: two single-channel linear textures (BC4); AperturePBR
  has no packed ORM input, so a glTF metallicRoughness texture (G rough, B metal)
  or a Poly Haven ARM (R ao, G rough, B metal) is split.
* emissive: an sRGB colour mask (BC3) times `emissive_intensity`.

Where the maps come from, best source first:

1. The model's own source material (assets-src, the glTF the importer read): its
   normal map, metallicRoughness / ARM texture, its roughness and metallic factors
   (the procedural cars, code objects and weapons are authored per material: chrome
   0.12 / 1.0, tyre 0.85 / 0, glass 0.05 ...), its emissiveFactor (proc-car head and
   tail lamps, siren lenses). A texture shared by several materials (the street
   lamp's body, glass and bulb share one picture) gets a per-texel material id by
   rasterising each material's triangles in UV space, so the bulb texels alone glow.
   Microsoft Rocketbox avatars: their `_normal` and `_specular` maps (fetched beside
   the colour maps; roughness from specular). The normal map's handedness is
   measured, not assumed: a real height field's slopes are curl-free, so
   d/dv(n_x/n_z) correlates with +d/du(n_y/n_z) in the DirectX convention and with
   the negative in the OpenGL one.
2. Derived from the albedo, detail-aware (the image-to-3D cars' baked atlases and
   everything without a source normal map): a scale-normalised Hessian line and
   blob detector at three scales, not a gradient of the albedo. A thin dark line
   (panel gap, door line, shut line, grille slot) is a valley of the luminance:
   one large positive and one small Hessian eigenvalue -> a groove. A thin bright
   line (chrome strip, rib, grille bar) -> a raised bead. A small round spot (both
   eigenvalues large, same sign: rivet, bolt, screw head) -> a dome or a dimple. A
   step between two colours (paint against trim, a livery edge) has a large
   gradient where its curvature is: the detector subtracts the gradient term, so a
   colour edge does not become a step in the surface. Responses are divided by the
   local contrast so a faint seam on dark paint counts like a crisp one on light
   paint, a weak grain band (0.15) adds surface texture, and the slopes fade to
   flat within two texels of an atlas island's edge (no seams from the transparent
   background, which is filled by normalised convolution first).
3. Per-texel classes from the colour where the source has nothing per texel: the
   image-to-3D car atlases (chrome, brushed metal, glass, rubber, lamps, painted
   body with a clear coat; see remix_model_materials.py's notes), avatar skin
   against cloth.

Emission: tail/brake lamps (compact red islands at the car's ends) and head lamps
(compact bright islands there) on the baked cars; emissiveFactor materials; every
`__lit` companion model (traffic-light lenses, the phone booth's sign, the pickups'
rings: the renderer draws them unlit so they read as light, and here they are);
materials named bulb / lens / lamp / neon / sign on a lit model. No model has a
dashboard material or a recognisable dashboard in its atlas, so no dashboard glows.

    remix_model_pbr.py preview <out.png> <models dir> <texture.tga> ...   (the maps side by side)

Pure numpy + Pillow (no scipy on this machine).
"""
import io, json, os, re, struct, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Clear coat (AperturePBR has no second lobe): smooth dielectric with a little flake.
PAINT_METALLIC, PAINT_ROUGHNESS = 0.2, 0.12
LAMP_INTENSITY = 6.0        # tail / brake lamps, emissiveFactor lamps
HEADLAMP_INTENSITY = 3.0    # white head lamps on the baked cars (brighter colour, lower gain)
LIT_INTENSITY = 8.0         # __lit companions: booth sign, traffic-light lenses
LIT_SMALL_INTENSITY = 3.0   # __lit pickup / token rings, the ringing handset
BULB_INTENSITY = 12.0       # a street lamp's bulb

# ------------------------------------------------------------------ filters --
def _kernel(s, order=0):
    r = max(1, int(np.ceil(3 * s)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    g = np.exp(-x * x / (2 * s * s)); g /= g.sum()
    if order == 1: g = -x / (s * s) * g
    if order == 2: g = (x * x / (s ** 4) - 1 / (s * s)) * g
    return g

def _conv1(a, k, axis):
    r = len(k) // 2
    pad = [(0, 0)] * a.ndim; pad[axis] = (r, r)
    p = np.pad(a, pad, mode="reflect" if a.shape[axis] > r else "edge")
    out = np.zeros_like(a, dtype=np.float32)
    n = a.shape[axis]
    for i, w in enumerate(k):
        sl = [slice(None)] * a.ndim; sl[axis] = slice(i, i + n)
        out += w * p[tuple(sl)]
    return out

def gauss(a, s, oy=0, ox=0):
    """Gaussian (derivative) filter, sigma s texels, mirrored edges; oy/ox derivative orders."""
    a = a.astype(np.float32)
    if s <= 0: return a
    return _conv1(_conv1(a, _kernel(s, oy), 0), _kernel(s, ox), 1)

def fill_hidden(lum, vis, sigmas=(1.5, 4, 12, 40)):
    """Values for the transparent texels by normalised convolution (coarser where needed),
    so a filter at an island's edge does not see a cliff into the background."""
    out = lum.copy(); have = vis.copy()
    w = vis.astype(np.float32)
    for s in sigmas:
        if have.all(): break
        num = gauss(lum * w, s); den = gauss(w, s)
        ok = (den > 1e-3) & ~have
        out[ok] = num[ok] / den[ok]; have |= ok
    out[~have] = float(lum[vis].mean()) if vis.any() else 0.5
    return out

def erode(mask, n):
    m = mask.copy()
    for _ in range(n):
        g = m.copy()
        g[1:] &= m[:-1]; g[:-1] &= m[1:]; g[:, 1:] &= m[:, :-1]; g[:, :-1] &= m[:, 1:]
        m = g
    return m

def luminance(rgb):
    rgb = rgb.astype(np.float32) / 255.0
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]

# ------------------------------------------------------------ derived normals --
def detail_height(rgba, strength_scale=1.0):
    """Height field from the albedo's thin structures (see the module notes): grooves for
    dark lines, beads for bright lines, domes / dimples for small round spots, a weak
    grain; colour steps suppressed. Returns (height, weight) with weight 0 at island edges."""
    h, w = rgba.shape[:2]
    vis = rgba[..., 3] >= 128
    if not vis.any(): vis = np.ones((h, w), bool)
    lum = fill_hidden(luminance(rgba[..., :3]), vis)
    k = max(min(h, w), 16) / 512.0                       # the textures are 512 px or less
    contrast = np.sqrt(np.maximum(gauss((lum - gauss(lum, 6 * max(k, 0.25))) ** 2, 6 * max(k, 0.25)), 0)) + 0.025
    height = np.zeros((h, w), np.float32)
    for s, wt in ((0.8, 0.45), (1.5, 0.35), (2.6, 0.20)):
        s = max(s * max(k, 0.5), 0.6)
        hyy = gauss(lum, s, 2, 0) * s * s
        hxx = gauss(lum, s, 0, 2) * s * s
        hxy = gauss(lum, s, 1, 1) * s * s
        gy = gauss(lum, s, 1, 0) * s; gx = gauss(lum, s, 0, 1) * s
        grad = np.sqrt(gx * gx + gy * gy)
        tr = 0.5 * (hxx + hyy); dt = np.sqrt(0.25 * (hxx - hyy) ** 2 + hxy * hxy)
        l1, l2 = tr + dt, tr - dt                         # l1 >= l2
        dark_line = np.maximum(l1 - np.abs(l2) - 0.6 * grad, 0)     # valley: groove
        bright_line = np.maximum(-l2 - np.abs(l1) - 0.6 * grad, 0)  # ridge: bead
        dark_blob = np.maximum(np.minimum(l1, l2) - 0.6 * grad, 0)  # both positive: dimple
        bright_blob = np.maximum(-np.maximum(l1, l2) - 0.6 * grad, 0)  # both negative: dome
        resp = (-1.0 * dark_line + 0.6 * bright_line - 0.5 * dark_blob + 0.7 * bright_blob) / contrast
        height += wt * np.tanh(resp * 0.8)
    grain = np.tanh((lum - gauss(lum, 1.0 * max(k, 0.5))) / contrast)
    height += 0.15 * grain
    weight = gauss(erode(vis, 2).astype(np.float32), 1.0)
    return height * strength_scale, weight

def height_to_normal(height, weight, strength):
    """DirectX tangent space: n = (-dh/du, -dh/dv, 1), v down the image."""
    dx = gauss(height, 0.7, 0, 1); dy = gauss(height, 0.7, 1, 0)
    n = np.stack([-dx * strength * weight, -dy * strength * weight, np.ones_like(dx)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)

def derived_normal(rgba, strength):
    hgt, wt = detail_height(rgba)
    return height_to_normal(hgt, wt, strength)

# -------------------------------------------------------------- source maps --
def decode_normal_image(im, size):
    """An RGB normal map resized to size (w, h), decoded to unit vectors, converted to
    the DirectX orientation by the curl test. Returns (normals, convention)."""
    a = np.asarray(im.convert("RGB").resize(size, Image.LANCZOS), np.float32) / 127.5 - 1.0
    a[..., 2] = np.maximum(a[..., 2], 0.05)
    px, py = a[..., 0] / a[..., 2], a[..., 1] / a[..., 2]
    s = 1.0
    d1 = gauss(px, 1.0, 1, 0); d2 = gauss(py, 1.0, 0, 1)
    c = float((d1 * d2).mean() / (np.sqrt((d1 * d1).mean() * (d2 * d2).mean()) + 1e-12))
    conv = "dx" if c >= 0 else "gl"
    if conv == "gl": a[..., 1] = -a[..., 1]
    return a / np.linalg.norm(a, axis=-1, keepdims=True), conv, c

def _load_gltf(path):
    import import_assets
    return import_assets.load_glb(path)

def _image(g, binary, path, index):
    img = g["images"][index]
    if "uri" in img and not img["uri"].startswith("data:"):
        return Image.open(os.path.join(os.path.dirname(path), img["uri"]))
    if "uri" in img:
        import base64
        return Image.open(io.BytesIO(base64.b64decode(img["uri"].split(",", 1)[1])))
    bv = g["bufferViews"][img["bufferView"]]; off = bv.get("byteOffset", 0)
    return Image.open(io.BytesIO(binary[off:off + bv["byteLength"]]))

_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

def accessor(g, binary, index):
    """a glTF accessor as a numpy array (count, n), strided views and normalised ints handled"""
    a = g["accessors"][index]; bv = g["bufferViews"][a["bufferView"]]
    dt = np.dtype(_CT[a["componentType"]]).newbyteorder("<"); n = _NC[a["type"]]
    stride = bv.get("byteStride", dt.itemsize * n); base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    cnt = a["count"]
    raw = np.frombuffer(binary, np.uint8, (cnt - 1) * stride + dt.itemsize * n, base) if cnt else np.zeros(0, np.uint8)
    out = np.lib.stride_tricks.as_strided(raw, (cnt, dt.itemsize * n), (stride, 1)).copy().view(dt).reshape(cnt, n)
    if a.get("normalized") and dt.kind in "iu": out = out.astype(np.float32) / np.iinfo(dt).max
    return out

def raster_uv(mask, uvs):
    """Marks the texels covered by UV triangles (n, 3, 2) in mask (h, w), v down the image."""
    h, w = mask.shape
    for uv in uvs:
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
    return mask

EMIT_NAME = re.compile(r"bulb|lens|lamp|neon|sign|light|led|beacon|siren", re.I)
GLASS_NAME = re.compile(r"glass|window|pane", re.I)

def source_specs(models_dir, src_root, manifest=None, only=None):
    """Per baked texture file: what the source material says. {tga: spec}, spec =
    {model, group, lit, mats: [{name, rough, metal, emit (rgb) or None, glass, emitname,
    normal_img, mr_img, mr_kind, spec_img, uvs (n,3,2) or None}]}. Missing sources give {}."""
    manifest = manifest or json.load(open(os.path.join(models_dir, "manifest.json")))
    specs = {}
    for e in manifest.get("models", []):
        name = e["name"]; path = os.path.join(src_root, e.get("glb", ""))
        if only is not None and name not in only: continue
        if not e.get("glb") or not os.path.exists(path): continue
        try: g, binary = _load_gltf(path)
        except Exception: continue
        group = e["glb"].split("/")[0]
        if group == "cars": group = "car3d" if "models3d" in e["glb"] else "carproc"
        overrides = e.get("material_textures", {})
        # UV triangles per material (for textures shared by several materials)
        uvs_by_mat = {}
        try:
            for mesh in g.get("meshes", []):
                for prim in mesh.get("primitives", []):
                    mi = prim.get("material"); at = prim.get("attributes", {})
                    if mi is None or "TEXCOORD_0" not in at: continue
                    uv = accessor(g, binary, at["TEXCOORD_0"]).astype(np.float32)
                    idx = accessor(g, binary, prim["indices"]).astype(np.int64).reshape(-1) \
                        if "indices" in prim else np.arange(len(uv))
                    idx = idx[:len(idx) // 3 * 3].reshape(-1, 3)
                    uvs_by_mat.setdefault(mi, []).append(uv[idx])
        except Exception:
            uvs_by_mat = {}
        rb_dir = None
        for v in overrides.values():
            if "rocketbox" in v: rb_dir = os.path.join(src_root, os.path.dirname(v))
        for mi, mat in enumerate(g.get("materials", [])):
            pbr = mat.get("pbrMetallicRoughness", {})
            mname = mat.get("name") or ""
            if mname in overrides:
                tag = f"{name}_{mname}.tga"
            elif "baseColorTexture" in pbr:
                tex = g["textures"][pbr["baseColorTexture"]["index"]]
                if "source" not in tex: continue
                tag = f"{name}_{tex['source']}.tga"
            else:
                tag = f"{name}_m{mi}.tga"
            rec = {"name": mname, "rough": float(pbr.get("roughnessFactor", 1.0)),
                   "metal": float(pbr.get("metallicFactor", 1.0)),
                   "emit": [float(c) for c in mat["emissiveFactor"]] if any(mat.get("emissiveFactor", [0, 0, 0])) else None,
                   "glass": bool(GLASS_NAME.search(mname)) or mat.get("alphaMode") == "BLEND" and pbr.get("roughnessFactor", 1) < 0.15,
                   "emitname": bool(EMIT_NAME.search(mname)),
                   "uvs": np.concatenate(uvs_by_mat[mi]) if mi in uvs_by_mat else None,
                   "normal_img": None, "mr_img": None, "spec_img": None}
            def img_of(key):
                t = mat.get(key) or pbr.get(key)
                if not t: return None
                tx = g["textures"][t["index"]]
                if "source" not in tx: return None
                try:
                    im = _image(g, binary, path, tx["source"])
                    return im if min(im.size) > 4 else None    # 1x1 placeholders (FBX2glTF) are no map
                except Exception: return None
            rec["normal_img"] = img_of("normalTexture")
            rec["mr_img"] = img_of("metallicRoughnessTexture")
            if group == "polyhaven" or "polyhaven" in e["glb"]: rec["mr_kind"] = "arm"
            else: rec["mr_kind"] = "gltf"
            if rb_dir and mname in overrides:
                base = os.path.basename(overrides[mname]).replace("_color", "")
                for kind in ("normal", "specular"):
                    p = os.path.join(rb_dir, base[:-4] + f"_{kind}.tga")
                    if os.path.exists(p) and os.path.getsize(p) > 1000:
                        rec[kind + "_img" if kind == "normal" else "spec_img"] = p
            s = specs.setdefault(tag, {"model": name, "group": group, "lit": name.endswith("__lit"),
                                       "glass_model": name.endswith("__glass"), "mats": [],
                                       "human": name.startswith("human_") or "rocketbox" in e["glb"]})
            s["mats"].append(rec)
    return specs

# ------------------------------------------------------------- classifiers --
def local_std(lum, vis, r=3):
    """standard deviation of the luminance over a (2r+1)^2 window, visible texels only"""
    def box(a):
        p = np.pad(a, ((r + 1, r), (r + 1, r)), mode="edge").cumsum(0).cumsum(1)
        k = 2 * r + 1
        return p[k:, k:] - p[:-k, k:] - p[k:, :-k] + p[:-k, :-k]
    w = vis.astype(np.float32); n = np.maximum(box(w), 1.0)
    m = box(lum * w) / n
    return np.sqrt(np.maximum(box(lum * lum * w) / n - m * m, 0))

def blobs(mask, visible, amax_frac=0.0025, ratio=4, fill=0.35):
    """The compact islands of mask: 4-connected components of at most amax_frac of the
    visible texels, bounding box no more than ratio:1 and at least `fill` filled."""
    h, w = mask.shape
    out = np.zeros_like(mask); seen = np.zeros_like(mask)
    amax = max(24, int(visible * amax_frac))
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]: continue
        stack, comp = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop(); comp.append((y, x))
            if len(comp) > amax * 4: continue
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True; stack.append((yy, xx))
        cy = [c[0] for c in comp]; cx = [c[1] for c in comp]
        bh, bw = max(cy) - min(cy) + 1, max(cx) - min(cx) + 1
        if 4 <= len(comp) <= amax and max(bh, bw) <= ratio * min(bh, bw) and len(comp) >= fill * bh * bw:
            out[cy, cx] = True
    return out

def car_trim_maps(rgba, ends=None):
    """The baked image-to-3D car atlases: metallic, roughness (0..1 float) and an emissive
    colour (uint8 RGB) + intensity map from the texel colours (REMIX-POLISH / REMIX-3
    classes) plus head lamps. Returns metal, rough, emit_rgb, emit_gain, class shares."""
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    mx, mn = rgb.max(-1), rgb.min(-1)
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0.0)
    vis = rgba[..., 3] >= 128
    sd = local_std(lum, vis)
    busy = sd > 0.11
    metal = np.full(lum.shape, PAINT_METALLIC, np.float32)
    rough = np.full(lum.shape, PAINT_ROUGHNESS + 0.04, np.float32)
    neutral = sat < 0.14
    # A large bright neutral field is white paint (a livery's doors, a van's sides), not
    # chrome, even where the bake left reflections in it: chrome strips and bumpers are
    # narrow, broken by dark reflection bands, so they fill less of their neighbourhood.
    bn = (neutral & (lum > 0.45) & vis).astype(np.float32)
    r7 = 7; pad = np.pad(bn, ((r7 + 1, r7), (r7 + 1, r7)), mode="edge").cumsum(0).cumsum(1); k7 = 2 * r7 + 1
    frac = (pad[k7:, k7:] - pad[:-k7, k7:] - pad[k7:, :-k7] + pad[:-k7, :-k7]) / (k7 * k7)
    chrome = neutral & (lum > 0.45) & busy & (frac < 0.6)
    brushed = neutral & (lum > 0.28) & (lum <= 0.45) & busy
    rubber = (mx < 0.11)
    glass = ~rubber & (lum < 0.30) & (rgb[..., 2] >= rgb[..., 0]) & (sat > 0.08) & (sat < 0.6)
    red = (rgb[..., 0] > 0.50) & (rgb[..., 1] < 0.32) & (rgb[..., 2] < 0.32) & (sat > 0.55)
    at_end = ends if ends is not None and ends.shape == red.shape else None
    nvis = int(vis.sum())
    lamp = blobs(red & at_end if at_end is not None else red, nvis)
    # Head lamps: compact, very bright, white-to-warm islands at the ends, smoother than
    # the chrome around them. Only where the mesh says which texels are the ends.
    head = np.zeros_like(lamp)
    if at_end is not None:
        bright = (lum > 0.80) & (sat < 0.35) & (sd < 0.16) & at_end & vis
        head = blobs(bright, nvis, amax_frac=0.0015, ratio=3, fill=0.45)
    for m, (mt, ro) in ((brushed, (0.7, 0.32)), (chrome, (1.0, 0.16)), (glass, (0.0, 0.05)),
                        (rubber, (0.0, 0.60)), (lamp, (0.0, 0.12)), (head, (0.0, 0.08))):
        metal[m] = mt; rough[m] = ro
    # tyre tread and seals rougher where the rubber is busy, glossy paint micro-variation
    rough = np.where(rubber, np.clip(0.6 + 0.6 * sd, 0.6, 0.9), rough)
    emit = np.zeros(rgba.shape[:2] + (3,), np.uint8)
    gain = np.zeros(lum.shape, np.float32)
    emit[lamp] = rgba[..., :3][lamp]; gain[lamp] = LAMP_INTENSITY
    emit[head] = rgba[..., :3][head]; gain[head] = HEADLAMP_INTENSITY
    n = max(nvis, 1)
    share = {k: float((v & vis).sum()) / n for k, v in (("chrome", chrome), ("brushed", brushed), ("glass", glass),
                                                     ("rubber", rubber), ("lamp", lamp), ("headlamp", head))}
    return metal, rough, emit, gain, share

def grain_mod(rgba):
    """per-texel roughness offset for a surface of one material: busier and darker than its
    neighbourhood (grime, wear, joints) rougher, by up to +-0.12"""
    lum = luminance(rgba[..., :3]); vis = rgba[..., 3] >= 128
    sd = local_std(lum, vis, 2)
    dark = gauss(lum, 4) - lum
    return np.clip(0.6 * (sd - 0.04) + 0.5 * dark, -0.12, 0.12)

def skin_mask(rgba):
    a = rgba[..., :3].astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    return (r > 80) & (g > 35) & (b > 15) & ((mx - mn) > 12) & (np.abs(r - g) > 12) & (r > g) & (r > b) & (r - b > 25)

# ---------------------------------------------------------------- per texture --
def texture_maps(tga, rgba, spec, ends=None, paint_mask=None, is_car=False):
    """All maps for one texture (uint8 RGBA, rows top down).
    paint_mask: the paint half's texels of a split pair (cars: clear coat; avatars: cloth).
    Returns dict: normal (h,w,3 float) or None, metal / rough (h,w float 0..1), emit (h,w,3
    uint8) or None, gain (float, the emissive_intensity), source (str), stats (dict)."""
    h, w = rgba.shape[:2]
    spec = spec or {}
    mats = spec.get("mats", [])
    group = spec.get("group", "car3d" if is_car else "prop")
    human = spec.get("human", False)
    stats = {}
    # material id per texel: biggest coverage first, so a small bulb or lens wins
    mid = np.zeros((h, w), np.int16)
    if len(mats) > 1:
        cover = []
        for i, m in enumerate(mats):
            msk = np.zeros((h, w), bool)
            if m["uvs"] is not None: raster_uv(msk, m["uvs"])
            cover.append((int(msk.sum()), i, msk))
        for _, i, msk in sorted(cover, key=lambda c: -c[0]):
            mid[msk] = i
    metal = np.zeros((h, w), np.float32); rough = np.full((h, w), 0.7, np.float32)
    emit = np.zeros((h, w, 3), np.uint8); gain = np.zeros((h, w), np.float32)
    normal = None; source = []
    vis = rgba[..., 3] >= 128
    if group == "car3d":
        metal, rough, emit, gain, stats = car_trim_maps(rgba, ends)
        source.append("classes")
    elif mats:
        gm = grain_mod(rgba)
        for i, m in enumerate(mats):
            sel = mid == i
            if not sel.any(): continue
            r0, m0 = m["rough"], m["metal"]
            if human:   # FBX2glTF's 0.4 / 0.707 for every Rocketbox material is no measurement
                r0, m0 = 0.78, 0.0
            if m["glass"] or spec.get("glass_model"): r0, m0 = 0.05, 0.0
            rough[sel] = np.clip(r0 + gm[sel] * (0.5 if r0 < 0.3 else 1.0), 0.03, 1.0)
            metal[sel] = m0
            if m["mr_img"] is not None:
                a = np.asarray(m["mr_img"].convert("RGB").resize((w, h), Image.LANCZOS), np.float32) / 255.0
                rough[sel] = np.clip(a[..., 1] * (m["rough"] if m["mr_kind"] == "gltf" else 1.0), 0.02, 1)[sel]
                metal[sel] = np.clip(a[..., 2] * (m["metal"] if m["mr_kind"] == "gltf" else 1.0), 0, 1)[sel]
                source.append("mr")
            if m.get("spec_img"):
                sp = luminance(np.asarray(Image.open(m["spec_img"]).convert("RGB").resize((w, h), Image.LANCZOS)))
                ref = max(float(np.percentile(sp[vis] if vis.any() else sp, 97)), 0.05)
                rough[sel] = np.clip(0.88 - 0.55 * np.clip(sp / ref, 0, 1), 0.3, 0.92)[sel]
                source.append("specular")
                if re.search(r"pistol|gun|weapon", m["name"], re.I):
                    metal[sel] = np.where(sp[sel] / ref > 0.5, 0.85, 0.1)
            if m["glass"] or spec.get("glass_model"):
                rough[sel] = 0.05; metal[sel] = 0.0
            if spec.get("lit") or m["emit"] is not None:
                small = re.search(r"pickup|token|handset|ring", spec.get("model", "") + " " + m["name"], re.I)
                col = rgba[..., :3].astype(np.float32)
                if spec.get("lit"):
                    g0 = LIT_SMALL_INTENSITY if small else LIT_INTENSITY
                else:
                    g0 = LAMP_INTENSITY
                    f = np.array(m["emit"], np.float32); f = f / max(float(f.max()), 1e-3)
                    col = np.maximum(col, 255 * f * 0.6) * np.maximum(f, 0.25)
                emit[sel] = np.clip(col, 0, 255).astype(np.uint8)[sel]; gain[sel] = g0
            elif re.search(r"bulb", m["name"], re.I):
                emit[sel] = np.clip(rgba[..., :3].astype(np.float32) * 0.5 + np.array([255, 214, 150]) * 0.5, 0, 255).astype(np.uint8)[sel]
                gain[sel] = BULB_INTENSITY
        source.append("material")
    else:
        rough = np.clip(0.7 + grain_mod(rgba), 0.3, 1.0)
        source.append("default")
    if human:
        # skin is smoother than cloth where no specular map says otherwise
        if not any(m.get("spec_img") for m in mats):
            sk = skin_mask(rgba)
            rough = np.where(sk, 0.5, rough)
        metal = np.where(metal > 0.5, metal, 0.0)
    if paint_mask is not None:
        if human:
            pass     # the clothing half keeps the cloth / specular roughness
        else:
            metal[paint_mask] = PAINT_METALLIC; rough[paint_mask] = PAINT_ROUGHNESS
            emit[paint_mask] = 0; gain[paint_mask] = 0
    elif group in ("carproc",) and tga.endswith("_paint.tga"):
        metal[:] = PAINT_METALLIC; rough[:] = PAINT_ROUGHNESS
    # normals: the source's where it has one, else derived
    for i, m in enumerate(mats):
        if m.get("normal_img") is None: continue
        im = m["normal_img"] if not isinstance(m["normal_img"], str) else Image.open(m["normal_img"])
        n, conv, c = decode_normal_image(im, (w, h))
        if normal is None: normal = np.zeros((h, w, 3), np.float32); normal[..., 2] = 1
        sel = mid == i if len(mats) > 1 else np.ones((h, w), bool)
        normal[sel] = n[sel]
        source.append(f"normal:{conv}({c:+.2f})")
    if normal is None and min(h, w) >= 32:
        strength = {"car3d": 5.0, "carproc": 3.0, "humans": 1.5}.get(group, 3.5)
        if human: strength = 1.5
        if spec.get("lit") or spec.get("glass_model"): strength = 1.0
        normal = derived_normal(rgba, strength)
        source.append("derived")
    if not gain.any(): emit_out, g_out = None, 0.0
    else:
        g_out = float(gain.max())
        emit_out = (emit.astype(np.float32) * (gain / g_out)[..., None]).astype(np.uint8)
    stats.setdefault("emit_texels", int((gain > 0).sum()))
    return {"normal": normal, "metal": metal, "rough": rough, "emit": emit_out, "gain": g_out,
            "source": "+".join(dict.fromkeys(source)), "stats": stats}

# ----------------------------------------------------------------- preview --
def shade(rgba, normal, rough=None, metal=None, light=(-0.55, -0.55, 0.63)):
    """The albedo lit by one raking light through the normal map, with a Blinn-Phong
    highlight whose width follows the roughness: a quick look at the relief and gloss.
    normal None = flat (the 'before')."""
    h, w = rgba.shape[:2]
    alb = rgba[..., :3].astype(np.float32) / 255.0
    n = normal if normal is not None else np.dstack([np.zeros((h, w)), np.zeros((h, w)), np.ones((h, w))])
    L = np.array(light, np.float32); L /= np.linalg.norm(L)
    # image y is +v (down): a light from the top-left has negative x and y in tangent space
    ndl = np.clip((n * L).sum(-1), 0, 1)
    out = alb * (0.25 + 0.95 * ndl[..., None])
    if rough is not None:
        H = L + np.array([0, 0, 1], np.float32); H /= np.linalg.norm(H)
        ndh = np.clip((n * H).sum(-1), 0, 1)
        p = 2.0 / np.maximum(rough, 0.04) ** 2
        spec = ndh ** p * (p + 2) / 40.0
        f0 = 0.04 + (metal if metal is not None else 0) * 0.9
        tint = np.where((metal if metal is not None else np.zeros((h, w)))[..., None] > 0.5, alb, 1.0)
        out = out * (1 - (metal if metal is not None else 0)[..., None] * 0.5) + (spec * f0)[..., None] * tint
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)

def normal_rgb(n):
    """for viewing: the DirectX tangent-space normal as the usual RGB (green = +v, down)"""
    return np.clip((n * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)

if __name__ == "__main__":
    if len(sys.argv) < 5 or sys.argv[1] != "preview":
        print(__doc__.split("\n\n")[-2]); sys.exit(1)
    import remix_materials as rm
    out, models = sys.argv[2], sys.argv[3]
    root = os.path.abspath(os.path.join(models, "..", "..", "..", "assets-src"))
    mesh_of = {t: m for m in os.listdir(models) if m.endswith(".mesh") for t in sys.argv[4:]
               if t.startswith(m[:-5] + "_")}
    specs = source_specs(models, root, only={m[:-5] for m in mesh_of.values()})
    rows = []
    for t in sys.argv[4:]:
        rgba = rm.to_rgba(rm.read_tga(os.path.join(models, t)))
        base = t[:-10] + ".tga" if t.endswith("_paint.tga") else t
        mp = texture_maps(t, rgba, specs.get(base), is_car=bool(re.match(r"\d{3}_", t)))
        n = mp["normal"] if mp["normal"] is not None else np.dstack([np.zeros(rgba.shape[:2])] * 2 + [np.ones(rgba.shape[:2])])
        cells = [rgba[..., :3], normal_rgb(n), np.repeat((mp["rough"] * 255).astype(np.uint8)[..., None], 3, -1),
                 np.repeat((mp["metal"] * 255).astype(np.uint8)[..., None], 3, -1),
                 mp["emit"] if mp["emit"] is not None else np.zeros_like(rgba[..., :3]),
                 shade(rgba, None), shade(rgba, mp["normal"], mp["rough"], mp["metal"])]
        rows.append(np.concatenate([np.asarray(Image.fromarray(c).resize((256, 256))) for c in cells], 1))
        print(t, mp["source"], mp["stats"])
    Image.fromarray(np.concatenate(rows, 0)).save(out)
