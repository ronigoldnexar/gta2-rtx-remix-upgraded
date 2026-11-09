#!/usr/bin/env python3
"""Offline preview of a carkit car: textured, sun + sky ambient, a grey road, the views a
player sees (eye height in front, chase camera behind, close 3/4, side) and a top
orthographic view beside the game's sprite (nose down, as the game draws it)."""
import math
import numpy as np
from PIL import Image, ImageDraw


def _persp(fovy, aspect, n=0.05, f=200.0):
    t = math.tan(math.radians(fovy) / 2)
    return np.array([[1 / (t * aspect), 0, 0, 0], [0, 1 / t, 0, 0], [0, 0, -(f + n) / (f - n), -2 * f * n / (f - n)], [0, 0, -1, 0]], np.float32)


def _ortho(w, h, n=-50, f=50):
    return np.array([[2 / w, 0, 0, 0], [0, 2 / h, 0, 0], [0, 0, -2 / (f - n), -(f + n) / (f - n)], [0, 0, 0, 1]], np.float32)


def _look(eye, tgt, up=(0, 1, 0)):
    eye, tgt, up = (np.asarray(v, np.float32) for v in (eye, tgt, up))
    f = tgt - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def render(groups, view, size=(640, 400), sun=(-0.45, 0.8, 0.40), device="cuda", ground=True, paint=None):
    import torch, nvdiffrast.torch as dr
    glctx = dr.RasterizeCudaContext(device=device)
    W, H = size
    if view.get("ortho"):
        P = _ortho(*view["ortho"]); M = _look(view["eye"], view["tgt"], view.get("up", (0, 1, 0)))
    else:
        P = _persp(view.get("fov", 50), W / H); M = _look(view["eye"], view["tgt"])
    MVP = torch.tensor(P @ M, device=device)
    Vs, Ns, UVs, Fs, tex_id = [], [], [], [], []
    off = 0
    for gi, g in enumerate(groups):
        Vs.append(g["V"]); Ns.append(g["N"]); UVs.append(g["UV"]); Fs.append(g["F"] + off); off += len(g["V"])
        tex_id.append(np.full(len(g["F"]), gi))
    if ground:
        s = 12.0
        gv = np.array([[-s, -0.002, -s], [s, -0.002, -s], [s, -0.002, s], [-s, -0.002, s]])
        Vs.append(gv); Ns.append(np.tile([0, 1, 0], (4, 1))); UVs.append(np.zeros((4, 2)))
        Fs.append(np.array([[0, 2, 1], [0, 3, 2]]) + off); tex_id.append(np.full(2, len(groups)))
    V = torch.tensor(np.vstack(Vs), dtype=torch.float32, device=device)
    N = torch.tensor(np.vstack(Ns), dtype=torch.float32, device=device)
    UV = torch.tensor(np.vstack(UVs), dtype=torch.float32, device=device)
    F = torch.tensor(np.vstack(Fs), dtype=torch.int32, device=device)
    tid = torch.tensor(np.concatenate(tex_id), dtype=torch.int64, device=device)
    clip = torch.cat([V, torch.ones_like(V[:, :1])], 1) @ MVP.T
    rast, rdb = dr.rasterize(glctx, clip[None], F, resolution=[H, W], grad_db=True)
    uv, uvda = dr.interpolate(UV[None], rast, F, rast_db=rdb, diff_attrs="all")
    nrm, _ = dr.interpolate(N[None], rast, F)
    pos, _ = dr.interpolate(V[None], rast, F)
    nrm = torch.nn.functional.normalize(nrm, dim=-1)
    tri = rast[..., 3].long() - 1
    cov = tri >= 0
    which = torch.where(cov, tid[tri.clamp(min=0)], torch.full_like(tri, -1))
    col = torch.zeros((1, H, W, 3), device=device)
    for gi, g in enumerate(groups):
        rgb = g["rgb"] * (np.asarray(paint, float) / 235.0 if (paint is not None and g.get("name") == "paint") else 1.0)
        t = torch.tensor(rgb, dtype=torch.float32, device=device)[None].contiguous()
        c = dr.texture(t, uv, uvda, filter_mode="linear-mipmap-linear", max_mip_level=6)
        col = torch.where((which == gi)[..., None], c, col)
    # ground: asphalt with a soft contact darkening near the car
    if ground:
        gx, gz = pos[..., 0], pos[..., 2]
        d = torch.sqrt(torch.clamp(gx.abs() - view.get("halfw", 1.1), min=0) ** 2 + torch.clamp(gz.abs() - view.get("halfl", 2.0), min=0) ** 2)
        shade = 0.36 - 0.10 * torch.exp(-d / 0.25)
        col = torch.where((which == len(groups))[..., None], shade[..., None].expand(-1, -1, -1, 3) * torch.tensor([1.0, 1.0, 1.02], device=device), col)
    L = torch.tensor(sun, dtype=torch.float32, device=device); L = L / L.norm()
    lam = torch.clamp((nrm * L).sum(-1, keepdim=True), min=0)
    sky = 0.42 + 0.18 * nrm[..., 1:2]
    lit = col * (sky + 0.75 * lam)
    bg = torch.tensor([0.62, 0.74, 0.88], device=device)
    img = torch.where(cov[..., None], lit, bg)
    img = dr.antialias(img.contiguous(), rast, clip[None], F)
    return Image.fromarray((img[0].clamp(0, 1).flip(0).cpu().numpy() * 255).astype(np.uint8))


def sheet(groups, L, W, Hh, sprite_path=None, out=None, device="cuda", title="", paint=None):
    """L, W, Hh: the car's length, width, height in metres (for framing)."""
    halfl, halfw = L / 2, W / 2
    views = [
        dict(name="eye 1.6 m, front 3/4, 7 m", eye=(4.5, 1.6, 6.0), tgt=(0, 0.9, 0.3), fov=45),
        dict(name="chase (behind, above)", eye=(-1.2, 3.2, -7.5), tgt=(0, 1.0, 0.5), fov=50),
        dict(name="close front", eye=(1.6, 1.3, 4.3), tgt=(0, 1.0, 1.0), fov=50),
        dict(name="side", eye=(8.0, 1.2, 0.0), tgt=(0, Hh * 0.45, 0), fov=35),
        dict(name="rear 3/4 low", eye=(-4.0, 1.4, -5.5), tgt=(0, 1.0, -0.3), fov=45),
        dict(name="far 20 m", eye=(9.0, 2.2, 18.0), tgt=(0, 1.0, 0), fov=30),
    ]
    tiles = []
    for v in views:
        v.setdefault("halfw", halfw); v.setdefault("halfl", halfl)
        im = render(groups, v, device=device, paint=paint)
        ImageDraw.Draw(im).text((6, 4), v["name"], fill=(0, 0, 0))
        tiles.append(im)
    # top: nose down like the sprite
    top = render(groups, dict(ortho=(W * 1.15, L * 1.08), eye=(0, 20, 0), tgt=(0, 0, 0), up=(0, 0, -1), halfw=halfw, halfl=halfl),
                 size=(int(320 * W / L * 1.15 / 1.08), 320), device=device, ground=False, paint=paint)
    sp = None
    if sprite_path:
        sp = Image.open(sprite_path).convert("RGBA")
        bg = Image.new("RGBA", sp.size, (158, 189, 224, 255)); bg.alpha_composite(sp); sp = bg.convert("RGB")
        sp = sp.resize((int(sp.width * 320 / sp.height), 320), Image.LANCZOS)
    tw, th = tiles[0].size
    extra = top.width + (sp.width if sp else 0) + 20
    S = Image.new("RGB", (tw * 3 + extra, th * 2 + 20), (40, 40, 40))
    for i, t in enumerate(tiles):
        S.paste(t, ((i % 3) * tw, 20 + (i // 3) * th))
    S.paste(top, (tw * 3 + 10, 20))
    if sp: S.paste(sp, (tw * 3 + 10 + top.width + 5, 20))
    ImageDraw.Draw(S).text((6, 4), title, fill=(255, 255, 255))
    if out: S.save(out)
    return S
