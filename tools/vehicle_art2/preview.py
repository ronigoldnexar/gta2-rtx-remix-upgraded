#!/usr/bin/env python3
"""Offline preview of a carkit car under the renderer's car lighting (car_bodies.cpp: one sun
from (0.38,-0.78,0.50), diffuse 0.78, ambient 0x5A, specular 0.55 x material, local viewer;
glass blended over the rest). nvdiffrast; run with the gen3d venv:
    gen3d/venv/bin/python tools/vehicle_art2/preview.py <car module> <out.png>
The renderer's per-material specular (model_store.cpp CarSurfaceMaterial) is mirrored in SPEC."""
import math
import numpy as np
import torch
import nvdiffrast.torch as dr
from PIL import Image

SPEC = {"chrome": (1.0, 60.0), "glass": (1.0, 90.0), "rubber": (0.06, 8.0), "paint": (0.6, 26.0)}


def spec_of(mat):
    for k in ("chrome", "glass", "rubber"):
        if k in mat:
            return SPEC[k]
    if "tyre" in mat or "underbody" in mat or "seal" in mat:
        return SPEC["rubber"]
    return SPEC["paint"]


def look_at(eye, target, up=(0, 1, 0)):
    eye, target, up = (np.array(v, np.float32) for v in (eye, target, up))
    f = target - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s) + 1e-9
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def persp(fov, aspect, near, far):
    f = 1 / math.tan(fov / 2)
    m = np.zeros((4, 4), np.float32)
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2], m[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def render(car, eye, target, size=(640, 400), fov=40, ctx=None, bg=(0.62, 0.68, 0.74), up=(0, 1, 0)):
    W, H = size
    mv = look_at(eye, target, up)
    mvp = torch.tensor(persp(math.radians(fov), W / H, 0.05, 80) @ mv, device="cuda")
    eye_t = torch.tensor(np.array(eye, np.float32), device="cuda")
    L = -torch.tensor(np.array([0.38, -0.78, 0.50]) / np.linalg.norm([0.38, -0.78, 0.50]), device="cuda", dtype=torch.float32)
    img = torch.ones((1, H, W, 3), device="cuda") * torch.tensor(bg, device="cuda")
    # ground
    depth = torch.full((1, H, W, 1), 2.0, device="cuda")
    layers = []
    for mat, part in car.parts.items():
        arr = part.arrays()
        if arr is None:
            continue
        p, n, t, f = arr
        v = torch.tensor(p, dtype=torch.float32, device="cuda")
        nn = torch.tensor(n, dtype=torch.float32, device="cuda")
        uv = torch.tensor(t, dtype=torch.float32, device="cuda")
        ff = torch.tensor(f, dtype=torch.int32, device="cuda")
        vh = torch.cat([v, torch.ones_like(v[:, :1])], 1) @ mvp.T
        rast, _ = dr.rasterize(ctx, vh[None], ff, (H, W))
        ni, _ = dr.interpolate(nn[None], rast, ff)
        pi, _ = dr.interpolate(v[None], rast, ff)
        ti, _ = dr.interpolate(uv[None], rast, ff)
        im = car.materials[mat].convert("RGBA")
        tex = torch.tensor(np.array(im), dtype=torch.float32, device="cuda") / 255
        if mat.startswith("paint") and getattr(car, "preview_tint", None):
            tex[..., :3] = tex[..., :3] * torch.tensor([c / 235.0 for c in car.preview_tint], device="cuda")
        col = dr.texture(tex[None], ti, filter_mode="linear")
        ni = ni / ni.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        vd = eye_t - pi; vd = vd / vd.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        # two-sided like the game (cull none): flip normals facing away
        ni = torch.where((ni * vd).sum(-1, keepdim=True) < 0, -ni, ni)
        ndl = (ni * L).sum(-1, keepdim=True).clamp(min=0)
        hv = L + vd; hv = hv / hv.norm(dim=-1, keepdim=True)
        ks, pw = spec_of(mat)
        sp = ((ni * hv).sum(-1, keepdim=True).clamp(min=0) ** pw) * 0.55 * ks * (ndl > 0)
        rgb = col[..., :3] * (0.353 + 0.78 * ndl) + sp
        a = col[..., 3:4]
        z = rast[..., 2:3]
        hit = rast[..., 3:4] > 0
        layers.append((mat, rgb, a, z, hit))
    for mat, rgb, a, z, hit in layers:
        if "glass" in mat:
            continue
        m = hit & (z < depth)
        img = torch.where(m, rgb, img); depth = torch.where(m, z, depth)
    for mat, rgb, a, z, hit in layers:
        if "glass" not in mat:
            continue
        m = hit & (z < depth)
        img = torch.where(m, rgb * a + img * (1 - a), img)
    return (img[0].flip(0).clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)


def sheet(car, out, length):
    ctx = dr.RasterizeCudaContext()
    L = length
    views = [
        ((L * 0.75, L * 0.30, L * 0.85), (0, 0.25 * L * 0.25, 0)),      # 3/4 front, chase-ish height
        ((-L * 0.8, L * 0.32, -L * 0.8), (0, 0.06 * L, 0)),             # 3/4 rear
        ((L * 1.25, L * 0.10, 0.0), (0, 0.12 * L, 0)),                   # side
        ((0.0, L * 1.4, 0.0), (0, 0, 0), (0, 0, -1)),                    # top, nose down as the sprite
        ((L * 0.35, 0.36, L * 0.95), (0, 0.15 * L, 0)),                  # eye height, front
        ((-L * 0.25, L * 0.45, -L * 1.0), (0, 0.1 * L, 0.1 * L)),        # chase behind
    ]
    tiles = [render(car, v[0], v[1], ctx=ctx, up=(v[2] if len(v) > 2 else (0, 1, 0))) for v in views]
    rows = [np.concatenate(tiles[i:i + 3], 1) for i in (0, 3)]
    Image.fromarray(np.concatenate(rows, 0)).save(out)
