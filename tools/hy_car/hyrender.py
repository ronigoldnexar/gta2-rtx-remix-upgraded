"""Orthographic nvdiffrast renders of textured trimesh parts along the model axes (nose +z, y up, x across).
view: 'side+' (looking from +x toward -x; image right = +z nose... see AXES), 'side-', 'top', 'front', 'rear'.
Returns dict(albedo HxWx3 float, shaded, alpha bool, depth = distance along the view axis from the viewer side
(world units, 0 at the bounding box face), extent (u0,u1,v0,v1) world coords of the image)."""
import numpy as np, torch, nvdiffrast.torch as dr, trimesh
_ctx = None
def ctx():
    global _ctx
    if _ctx is None: _ctx = dr.RasterizeCudaContext()
    return _ctx
# per view: (image-right axis, image-up axis, toward-viewer axis) as (index, sign)
AXES = {'side+': ((2, +1), (1, +1), (0, +1)), 'side-': ((2, -1), (1, +1), (0, -1)),
        'top': ((0, +1), (2, -1), (1, +1)), 'front': ((0, -1), (1, +1), (2, +1)), 'rear': ((0, +1), (1, +1), (2, -1)),
        'under': ((0, +1), (2, +1), (1, -1))}
def _tex(part):
    vis = part.visual
    if isinstance(vis, trimesh.visual.TextureVisuals) and vis.uv is not None and vis.material is not None:
        t = getattr(vis.material, 'baseColorTexture', None) or getattr(vis.material, 'image', None)
        if t is not None: return t
    return None
def render(parts, view, res=0.002, bounds=None, light=(0.35, 0.8, 0.5), pad=0.01):
    allv = np.concatenate([p.vertices for p in parts])
    lo, hi = (allv.min(0), allv.max(0)) if bounds is None else bounds
    (ia, sa), (ib, sb), (ic, sc) = AXES[view]
    def rng(i, s): return (lo[i] - pad, hi[i] + pad) if s > 0 else (-(hi[i] + pad), -(lo[i] - pad))
    u0, u1 = rng(ia, sa); v0, v1 = rng(ib, sb)
    W = int(np.ceil((u1 - u0) / res)); H = int(np.ceil((v1 - v0) / res))
    W += W % 2; H += H % 2
    u1 = u0 + W * res; v1 = v0 + H * res
    dlo, dhi = lo[ic] - pad, hi[ic] + pad
    alb = torch.zeros((1, H, W, 3), device='cuda'); shd = torch.zeros_like(alb)
    depth = torch.full((1, H, W, 1), 1e9, device='cuda'); fid = torch.full((1, H, W, 1), -1, device='cuda', dtype=torch.int32)
    pid = torch.full((1, H, W, 1), -1, device='cuda', dtype=torch.int32)
    L = torch.tensor(np.array(light) / np.linalg.norm(light), device='cuda', dtype=torch.float32)
    for k, p in enumerate(parts):
        v = torch.tensor(np.asarray(p.vertices), dtype=torch.float32, device='cuda')
        f = torch.tensor(np.asarray(p.faces), dtype=torch.int32, device='cuda')
        x = sa * v[:, ia]; y = sb * v[:, ib]; dz = (dhi - v[:, ic]) if sc > 0 else (v[:, ic] - dlo)   # distance from viewer
        clip = torch.stack([(x - u0) / (u1 - u0) * 2 - 1, (y - v0) / (v1 - v0) * 2 - 1, dz / (dhi - dlo) * 2 - 1, torch.ones_like(x)], 1)
        rast, _ = dr.rasterize(ctx(), clip[None].contiguous(), f, (H, W))
        n = torch.tensor(np.asarray(p.vertex_normals), dtype=torch.float32, device='cuda')
        ni, _ = dr.interpolate(n[None], rast, f)
        ni = ni / ni.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        shade = (0.35 + 0.65 * (ni @ L).clamp(min=0))[..., None]
        col = torch.ones((1, H, W, 3), device='cuda') * 0.7
        t = _tex(p)
        if t is not None:
            tt = torch.tensor(np.array(t.convert('RGB')), dtype=torch.float32, device='cuda') / 255
            uv = torch.tensor(np.asarray(p.visual.uv), dtype=torch.float32, device='cuda'); uv = torch.stack([uv[:, 0], 1 - uv[:, 1]], 1)
            uvi, _ = dr.interpolate(uv[None].contiguous(), rast, f); col = dr.texture(tt[None].contiguous(), uvi.contiguous(), filter_mode='linear')
        elif p.metadata.get('rgb') is not None:
            col = col * 0 + torch.tensor(p.metadata['rgb'], device='cuda', dtype=torch.float32)
        dd, _ = dr.interpolate(dz[None, :, None].contiguous(), rast, f)
        hit = (rast[..., 3:4] > 0) & (dd < depth)
        alb = torch.where(hit, col, alb); shd = torch.where(hit, col * shade, shd); depth = torch.where(hit, dd, depth)
        fid = torch.where(hit, rast[..., 3:4].int() - 1, fid); pid = torch.where(hit, torch.full_like(pid, k), pid)
    # row 0 = top of the image (largest v)
    flip = lambda a: a[0].flip(0).cpu().numpy()
    a = flip(depth)[..., 0]
    return dict(albedo=flip(alb), shaded=flip(shd), alpha=a < 1e8, depth=np.where(a < 1e8, a, np.inf), face=flip(fid)[..., 0],
                part=flip(pid)[..., 0], extent=(u0, u1, v0, v1), res=res)
def to_img(arr, alpha=None, bg=(0.93, 0.93, 0.93)):
    from PIL import Image
    a = np.clip(arr, 0, 1)
    if alpha is not None: a = np.where(alpha[..., None], a, np.array(bg))
    return Image.fromarray((a * 255).astype(np.uint8))
