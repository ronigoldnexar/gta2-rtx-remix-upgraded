"""Renders a GMSH avatar (posed) with nvdiffrast: textures, alpha test, per-mesh tint.
render(model_path, views, tints=None, clip='idle') -> list of PIL images.
tints: function(tex_name, node_name) -> rgb multiplier (3,) or None."""
import os, sys, numpy as np, torch, nvdiffrast.torch as dr
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__)); import gmsh
_ctx = None; _tex = {}
def ctx():
    global _ctx
    if _ctx is None: _ctx = dr.RasterizeCudaContext()
    return _ctx
def tex(path):
    if path not in _tex:
        im = Image.open(path).convert('RGBA')   # TGA written flipped; PIL un-flips by origin flag
        _tex[path] = torch.tensor(np.asarray(im, np.float32) / 255.0, device='cuda')
    return _tex[path]
def look(eye, target, up=(0, 1, 0)):
    eye, target, up = map(np.array, (eye, target, up)); f = target - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s); u = np.cross(s, f)
    m = np.eye(4); m[0, :3] = s; m[1, :3] = u; m[2, :3] = -f; m[:3, 3] = -m[:3, :3] @ eye; return m
def persp(fov, aspect, n=0.05, f=20):
    t = np.tan(np.radians(fov) / 2); m = np.zeros((4, 4))
    m[0, 0] = 1 / (t * aspect); m[1, 1] = 1 / t; m[2, 2] = -(f + n) / (f - n); m[2, 3] = -2 * f * n / (f - n); m[3, 2] = -1; return m
def render(path, views, tints=None, clip='idle', frame=0, size=(320, 480), bg=(0.42, 0.44, 0.46), hide=None, anim_from=None):
    model = gmsh.load(path)
    if anim_from: model['anims'] = gmsh.load(anim_from)['anims']   # a detail variant carries no clips: its avatar's
    parts, world = gmsh.pose(model, clip, frame)
    d = os.path.dirname(path); W, H = size; imgs = []
    allp = np.concatenate([p[0] for p in parts]); lo, hi = allp.min(0), allp.max(0); c = (lo + hi) / 2; h = hi[1] - lo[1]
    for (yaw, pitch) in views:
        dist = h * 2.3; yr, pr = np.radians(yaw), np.radians(pitch)
        eye = c + dist * np.array([np.sin(yr) * np.cos(pr), np.sin(pr), np.cos(yr) * np.cos(pr)])
        mvp = persp(30, W / H) @ look(eye, c)
        col = torch.tensor(bg, device='cuda').expand(H, W, 3).clone(); depth = torch.full((H, W), 1e9, device='cuda')
        for p, n, uv, idx, texname, ni in parts:
            if hide and hide(texname, model['nodes'][ni]['name']): continue
            P = torch.tensor(np.c_[p, np.ones(len(p))] @ mvp.T, dtype=torch.float32, device='cuda')[None]
            tri = torch.tensor(idx, dtype=torch.int32, device='cuda')
            rast, _ = dr.rasterize(ctx(), P, tri, (H, W))
            uvs, _ = dr.interpolate(torch.tensor(uv, dtype=torch.float32, device='cuda')[None], rast, tri)
            nrm, _ = dr.interpolate(torch.tensor(n, dtype=torch.float32, device='cuda')[None], rast, tri)
            t = tex(os.path.join(d, texname))
            uvs = uvs.clone(); uvs[..., 1] = uvs[..., 1]   # glTF uv origin top-left = image row 0
            s = dr.texture(t[None].contiguous(), uvs.contiguous(), filter_mode='linear')[0]
            z = rast[0, ..., 2]; cover = (rast[0, ..., 3] > 0) & (s[..., 3] > 0.5)
            ndc_z = z
            L = torch.tensor([0.4, 0.8, 0.6], device='cuda'); L = L / L.norm()
            nn = torch.nn.functional.normalize(nrm[0], dim=-1)
            lam = 0.45 + 0.55 * (nn @ L).abs().clamp(0, 1)
            rgb = s[..., :3]
            if tints:
                tn = tints(texname, model['nodes'][ni]['name'])
                if tn is not None: rgb = (rgb * torch.tensor(tn, device='cuda', dtype=torch.float32)).clamp(0, 1)
            rgb = rgb * lam[..., None]
            upd = cover & (ndc_z < depth)
            col[upd] = rgb[upd]; depth[upd] = ndc_z[upd]
        im = (col.flip(0).cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        imgs.append(Image.fromarray(im))
    return imgs
