#!/usr/bin/env python3
"""Offline sheet of converted cars: the generator's shell (top row) and the converted model (bottom row) from the
views a player sees, plus wheel close-ups.  preview.py <out.jpg> <src glb dir> <converted glb dir> <name>..."""
import sys, os, math, numpy as np, torch, trimesh
sys.path.insert(0, '/mnt/gta2/gta2-linux/gen3d')
import render_glb as R
import nvdiffrast.torch as dr
from PIL import Image, ImageDraw
ctx = dr.RasterizeCudaContext()

def view(meshes, eye_dir, size=420, target=None, dist=2.4, fov=35):
    allv = np.concatenate([m.vertices for m in meshes]); lo, hi = allv.min(0), allv.max(0)
    c = (lo + hi) / 2 if target is None else np.array(target, float); rad = np.linalg.norm(hi - lo) / 2
    eye = c + np.array(eye_dir, float) / np.linalg.norm(eye_dir) * rad * dist
    mv = R.look_at(eye, c, (0, 1, 0)); pr = R.perspective(math.radians(fov), 1.0, 0.01, rad * 10)
    mvp = torch.tensor(pr @ mv, device='cuda')
    img = torch.zeros((1, size, size, 3), device='cuda'); depth = torch.full((1, size, size, 1), 1e9, device='cuda')
    L = torch.tensor(np.array([0.4, 1.0, 0.6]) / np.linalg.norm([0.4, 1.0, 0.6]), device='cuda', dtype=torch.float32)
    for m in meshes:
        v = torch.tensor(np.asarray(m.vertices), dtype=torch.float32, device='cuda'); f = torch.tensor(np.asarray(m.faces), dtype=torch.int32, device='cuda')
        vh = torch.cat([v, torch.ones_like(v[:, :1])], 1) @ mvp.T
        rast, _ = dr.rasterize(ctx, vh[None], f, (size, size))
        n = torch.tensor(np.asarray(m.vertex_normals), dtype=torch.float32, device='cuda'); ni, _ = dr.interpolate(n[None], rast, f)
        shade = (0.38 + 0.62 * (ni @ L).abs())[..., None]
        col = torch.ones((1, size, size, 3), device='cuda') * 0.7
        vis = m.visual
        if isinstance(vis, trimesh.visual.TextureVisuals) and vis.uv is not None and vis.material is not None:
            t = getattr(vis.material, 'baseColorTexture', None) or getattr(vis.material, 'image', None)
            if t is not None:
                tt = torch.tensor(np.array(t.convert('RGB')), dtype=torch.float32, device='cuda') / 255
                uv = torch.tensor(np.asarray(vis.uv), dtype=torch.float32, device='cuda'); uv = torch.stack([uv[:, 0], 1 - uv[:, 1]], 1)
                uvi, _ = dr.interpolate(uv[None].contiguous(), rast, f); col = dr.texture(tt[None].contiguous(), uvi.contiguous(), filter_mode='linear')
        z = rast[..., 2:3]; hit = (rast[..., 3:4] > 0) & (z < depth)
        img = torch.where(hit, col * shade, img); depth = torch.where(hit, z, depth)
    img = torch.where(depth < 1e8, img, torch.tensor([0.93, 0.93, 0.93], device='cuda'))
    return Image.fromarray((img[0].flip(0).clamp(0, 1).cpu().numpy() * 255).astype(np.uint8))

def views(meshes, nose):
    allv = np.concatenate([m.vertices for m in meshes]); lo, hi = allv.min(0), allv.max(0)
    s = 1.0 if nose == '+z' else -1.0
    out = [view(meshes, (0.75, 0.45, 0.75 * s)), view(meshes, (-0.75, 0.40, -0.75 * s)), view(meshes, (1, 0.12, 0)),
           view(meshes, (0, 1, 0.001 * s))]
    # wheel close-ups: front-right wheel at chase eye height, and low from the side
    zf = s * 0.62 * (hi[2] - lo[2]) / 2
    out.append(view(meshes, (0.8, 0.35, 0.6 * s), target=(hi[0] * 0.8, 0.08, zf), dist=0.55))
    out.append(view(meshes, (0.3, 0.1, 1.0 * s), target=(0, (hi[1]) * 0.45, hi[2] if s > 0 else lo[2]), dist=1.1))
    return out

if __name__ == '__main__':
    out, srcd, cvd = sys.argv[1:4]; rows = []
    for spec in sys.argv[4:]:
        num, name, nose = spec.split(':')
        a = R.load(f'{srcd}/{num}.glb'); b = R.load(f'{cvd}/{name}.glb')
        ra = views(a, nose); rb = views(b, '+z')
        for lab, imgs in ((f'{num} generator shell', ra), (f'{name} converted', rb)):
            row = Image.new('RGB', (len(imgs) * 420, 420), 'white')
            for i, im in enumerate(imgs): row.paste(im, (i * 420, 0))
            ImageDraw.Draw(row).text((6, 6), lab, fill=(200, 0, 0)); rows.append(row)
    o = Image.new('RGB', (rows[0].width, 420 * len(rows)), 'white')
    for i, r in enumerate(rows): o.paste(r, (0, i * 420))
    o.save(out, quality=88)
