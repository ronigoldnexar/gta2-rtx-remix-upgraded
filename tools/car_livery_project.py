#!/usr/bin/env python3
"""FIX-CAR-IDENTITY-2 (pm24 police, pm29 ambulance): repaint a livery model's top from the game's sprite.

Why: a livery model (identity.cpp Livery: cop car, ambulance, ...) is drawn untinted, so its texture alone decides
its colours in the 3D views. The image-to-3D generator painted some liveries' tops wrong: the cop car's roof,
bonnet and boot navy where the sprite (the identity reference, seen from above in the classic view) is white;
the ambulance's roof, rear deck and boot near-black where the sprite is cream. The tint cannot fix that (one
factor per draw), so the texture is repainted where it disagrees with the sprite.

What: every texel of the model's baked texture pair (<tex>.tga + <tex>_paint.tga, the same UVs) is located on the
mesh (its triangles rasterised in UV space: position and normal per texel). A texel is on the top when it faces
up (normal y >= --min-up) above the beltline (y >= --belt of the body height) and inside the sprite's footprint.
Its reference colour is the sprite's at the same point of the footprint (model x across, z along, mapped onto the
sprite's opaque box; the nose is the sprite's bottom, as the game draws it; --flip-z if the model's nose is -z).
Where the texel's (blurred) colour differs from the reference by more than --tol (RGB distance), it is repainted:
the reference colour plus the texel's own fine detail (its luminance minus a blur of it, x --detail).
Texels that already agree (a crisp cross, a shield, cream panels) are left alone. The sides, glass at the sides,
wheels and the undercarriage are not touched.

Writes the pair to --out (default in place; a file is unlinked first: assets/models shares inodes with stages) and
a preview: the top seen from above, before | after | the sprite (--preview PNG). Deterministic.

  python3 tools/car_livery_project.py assets/models 012_cop_car --sprite <dir>/012_cop_car_default.png \
      [--out DIR] [--preview p.png] [--dry-run]
"""
import argparse, os, struct, sys
import numpy as np
from PIL import Image, ImageFilter


def read_mesh(path):
    """(texture, vertices[n, 8]: position, normal, uv; indices[m, 3]) per mesh of a GMSH file (import_assets.py)."""
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


def read(path):
    return np.asarray(Image.open(path).convert("RGBA")).astype(np.float32)


def write_tga(arr, path):
    """32-bit uncompressed TGA, bottom-up (as tools/import_assets.py writes them)."""
    if os.path.lexists(path):
        os.unlink(path)
    px = np.clip(arr + 0.5, 0, 255).astype(np.uint8)[::-1][..., [2, 1, 0, 3]]
    h, w = px.shape[:2]
    with open(path, "wb") as f:
        f.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(px.tobytes())


def texel_geometry(meshes, tex, w, h):
    """Per texel of `tex`: covered, position (3), normal (3), by rasterising the triangles that use it in UV space."""
    cov = np.zeros((h, w), bool); pos = np.zeros((h, w, 3), np.float32); nrm = np.zeros((h, w, 3), np.float32)
    for t, v, idx in meshes:
        if t != tex or not len(idx):
            continue
        P = v[idx][:, :, :3]; N = v[idx][:, :, 3:6]; UV = v[idx][:, :, 6:8]
        for k in range(len(idx)):
            x = UV[k, :, 0] * w; y = UV[k, :, 1] * h
            xa, xb = int(max(np.floor(x.min()), 0)), int(min(np.ceil(x.max()), w - 1))
            ya, yb = int(max(np.floor(y.min()), 0)), int(min(np.ceil(y.max()), h - 1))
            if xb < xa or yb < ya:
                continue
            gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
            dd = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
            if abs(dd) < 1e-9:
                continue
            a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / dd
            b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / dd
            c = 1 - a - b
            ins = (a >= -0.01) & (b >= -0.01) & (c >= -0.01)
            if not ins.any():
                continue
            bc = np.stack([a, b, c], -1)[ins]
            sl = (slice(ya, yb + 1), slice(xa, xb + 1))
            sub_c = cov[sl]; sub_p = pos[sl]; sub_n = nrm[sl]
            sub_p[ins] = bc @ P[k]
            nn = bc @ N[k]
            sub_n[ins] = nn / (np.linalg.norm(nn, axis=1, keepdims=True) + 1e-9)
            sub_c[ins] = True
    return cov, pos, nrm


def bilinear(img, u, v):
    """img[h, w, c] sampled at continuous pixel coordinates (u across, v down)."""
    h, w = img.shape[:2]
    u = np.clip(u - 0.5, 0, w - 1); v = np.clip(v - 0.5, 0, h - 1)
    u0 = np.floor(u).astype(int); v0 = np.floor(v).astype(int)
    u1 = np.minimum(u0 + 1, w - 1); v1 = np.minimum(v0 + 1, h - 1)
    fu = (u - u0)[:, None]; fv = (v - v0)[:, None]
    return (img[v0, u0] * (1 - fu) * (1 - fv) + img[v0, u1] * fu * (1 - fv) + img[v1, u0] * (1 - fu) * fv + img[v1, u1] * fu * fv)


def top_splat(pos, col, sel, lo, hi, scale=6):
    """The selected texels seen from above (x across, nose down), as a picture the size of the sprite x scale."""
    W = int((hi[0] - lo[0]) / (hi[2] - lo[2]) * 64 * scale / 2) + 1; H = 64 * scale // 2
    img = np.full((H, W, 3), 60, np.float32); zb = np.full((H, W), -1e9, np.float32)
    p = pos[sel]; c = col[sel]
    ix = np.clip(((p[:, 0] - lo[0]) / (hi[0] - lo[0]) * (W - 1)).astype(int), 0, W - 1)
    iy = np.clip(((p[:, 2] - lo[2]) / (hi[2] - lo[2]) * (H - 1)).astype(int), 0, H - 1)
    order = np.argsort(p[:, 1])
    for i in order:   # highest last
        img[iy[i], ix[i]] = c[i]
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("name", help="e.g. 012_cop_car")
    ap.add_argument("--sprite", required=True, help="the game's sprite (default palette), RGBA")
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-up", type=float, default=0.40)
    ap.add_argument("--belt", type=float, default=0.45)
    ap.add_argument("--tol", type=float, default=70.0)
    ap.add_argument("--detail", type=float, default=0.6)
    ap.add_argument("--ends", choices=["tail", "nose", "both"], default=None,
                    help="also these end faces, from the sprite's end rows (the nose's windscreen faces forward too: use with care)")
    ap.add_argument("--end-low", type=float, default=0.30, help="ends: from this fraction of the body height up (above the bumper)")
    ap.add_argument("--flip-z", action="store_true")
    ap.add_argument("--flip-x", action="store_true")
    ap.add_argument("--preview", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = a.out or a.models
    meshes = read_mesh(os.path.join(a.models, a.name + ".mesh"))
    tex = a.name + "_0.tga"
    R = read(os.path.join(a.models, tex)); P = read(os.path.join(a.models, a.name + "_0_paint.tga"))
    h, w = R.shape[:2]
    pm = P[..., 3] >= 128
    albedo = np.where(pm[..., None], P[..., :3], R[..., :3])
    # the geometry: texels of the rest texture's triangles (the paint mesh has the same UVs)
    cov, pos, nrm = texel_geometry(meshes, tex, w, h)
    cov2, pos2, nrm2 = texel_geometry(meshes, a.name + "_0_paint.tga", w, h)
    add = cov2 & ~cov
    cov |= cov2; pos[add] = pos2[add]; nrm[add] = nrm2[add]
    allv = np.concatenate([v[:, :3] for _, v, idx in meshes if len(idx)])
    lo, hi = allv.min(0), allv.max(0)
    # the sprite's footprint
    S = read(a.sprite); sa = S[..., 3] >= 128
    ys, xs = np.where(sa)
    sx0, sx1, sy0, sy1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    fx = (pos[..., 0] - lo[0]) / (hi[0] - lo[0]); fz = (pos[..., 2] - lo[2]) / (hi[2] - lo[2])
    if a.flip_x: fx = 1 - fx
    if a.flip_z: fz = 1 - fz
    su = sx0 + fx * (sx1 - sx0); sv = sy0 + fz * (sy1 - sy0)   # nose (+z) at the sprite's bottom
    up = nrm[..., 1] >= a.min_up
    above = pos[..., 1] >= lo[1] + a.belt * (hi[1] - lo[1])
    cand = cov & up & above
    spr_rgb = S[..., :3] * (S[..., 3:4] / 255.0); spr_a = S[..., 3:4] / 255.0
    lum = 0.30 * albedo[..., 0] + 0.59 * albedo[..., 1] + 0.11 * albedo[..., 2]
    mx = albedo.max(-1); mn = albedo.min(-1); sat = (mx - mn) / np.maximum(mx, 1)
    # the reference per texel: the sprite at the point of the footprint (top), or its end row at that column (ends)
    refimg = np.zeros((h, w, 3), np.float32); have = np.zeros((h, w), bool)
    idx = np.where(cand)
    ref = bilinear(spr_rgb, su[idx], sv[idx]); ra = bilinear(spr_a, su[idx], sv[idx])[:, 0]
    ok = ra >= 0.6
    refimg[idx[0][ok], idx[1][ok]] = ref[ok] / np.maximum(ra[ok, None], 1e-3); have[idx[0][ok], idx[1][ok]] = True
    nends = 0
    if a.ends:
        # nose (+z, the sprite's bottom rows) and tail (-z, its top rows): faces turned that way, above the bumper,
        # not a lamp (bright and saturated) and not the top already done
        endf = cov & ~cand & (np.abs(nrm[..., 2]) >= 0.6) & (pos[..., 1] >= lo[1] + a.end_low * (hi[1] - lo[1])) & ~((sat > 0.45) & (mx > 120))
        nose = nrm[..., 2] > 0
        if a.flip_z: nose = ~nose
        if a.ends == "tail": endf &= ~nose
        if a.ends == "nose": endf &= nose
        rows = 3.0   # the sprite's last rows at that end, averaged
        ei = np.where(endf)
        acc = np.zeros((len(ei[0]), 3), np.float32); wa = np.zeros(len(ei[0]), np.float32)
        for k in range(int(rows)):
            v = np.where(nose[ei], sy1 - 0.5 - k, sy0 + 0.5 + k)
            c = bilinear(spr_rgb, su[ei], v); al = bilinear(spr_a, su[ei], v)[:, 0]
            acc += c; wa += al
        okE = wa >= 0.6 * rows
        refimg[ei[0][okE], ei[1][okE]] = acc[okE] / np.maximum(wa[okE, None], 1e-3); have[ei[0][okE], ei[1][okE]] = True
        nends = int(okE.sum())
    # disagreement on a blurred copy (texture noise and seams do not count)
    blur = np.stack([np.asarray(Image.fromarray(albedo[..., c].astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))).astype(np.float32) for c in range(3)], -1)
    hi_ = np.where(have)
    dist = np.linalg.norm(blur[hi_] - refimg[hi_], axis=1)
    rep = dist > a.tol
    lblur = np.asarray(Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(4))).astype(np.float32)
    detail = (lum - lblur)[hi_]
    new = np.clip(refimg[hi_] + a.detail * detail[:, None], 0, 255)
    result = albedo.copy()
    ry, rx = hi_[0][rep], hi_[1][rep]
    result[ry, rx] = new[rep]
    idx = hi_
    print(f"{a.name}: {int(cov.sum())} texels on the mesh, {int(cand.sum())} on the top ({int(ok.sum())} inside the sprite), {nends} on the ends, "
          f"{int(rep.sum())} repainted (tol {a.tol:.0f}); mean before {albedo[ry, rx].mean(0).round() if rep.any() else '-'}, "
          f"after {result[ry, rx].mean(0).round() if rep.any() else '-'}")
    if a.preview:
        topsel = cand & cov
        b = top_splat(pos, albedo, topsel, lo, hi); c = top_splat(pos, result, topsel, lo, hi)
        if a.flip_x: b = b[:, ::-1]; c = c[:, ::-1]
        if a.flip_z: b = b[::-1]; c = c[::-1]
        sp = S[sy0:sy1, sx0:sx1]
        sp = np.asarray(Image.fromarray(sp.astype(np.uint8)).resize((b.shape[1], b.shape[0]), Image.NEAREST)).astype(np.float32)
        spc = sp[..., :3] * (sp[..., 3:4] / 255) + 60 * (1 - sp[..., 3:4] / 255)
        gap = np.full((b.shape[0], 8, 3), 255, np.float32)
        rows_ = [np.concatenate([b, gap, c, gap, spc], 1)]
        if a.ends:
            for sign in (-1, 1):   # tail, nose seen from outside: x across, y up, the nearest texels last
                face = cov & (np.sign(nrm[..., 2]) == sign) & (np.abs(nrm[..., 2]) >= 0.3)
                pe = np.stack([pos[..., 0], sign * pos[..., 2], pos[..., 1]], -1)
                lo2 = np.array([lo[0], 0, lo[1]]); hi2 = np.array([hi[0], 0, hi[1]])
                e1 = top_splat(pe, albedo, face, lo2, hi2)[::-1]; e2 = top_splat(pe, result, face, lo2, hi2)[::-1]
                rows_.append(np.concatenate([e1, gap[:e1.shape[0]], e2], 1))
        Wm = max(r.shape[1] for r in rows_)
        rows_ = [np.pad(r, ((0, 8), (0, Wm - r.shape[1]), (0, 0)), constant_values=255) for r in rows_]
        Image.fromarray(np.concatenate(rows_, 0).astype(np.uint8)).save(a.preview)
    if a.dry_run:
        return
    newP = P.copy(); newR = R.copy()
    newP[..., :3] = np.where(pm[..., None], result, P[..., :3])
    newR[..., :3] = np.where(pm[..., None], R[..., :3], result)
    os.makedirs(out, exist_ok=True)
    write_tga(newP, os.path.join(out, a.name + "_0_paint.tga"))
    write_tga(newR, os.path.join(out, tex))


if __name__ == "__main__":
    main()
