#!/usr/bin/env python3
"""Which end of a fitted car model is its nose, judged against its own concept image.

make_car_model.py turns the nose to +z from the cabin position along the length,
which fails on bodies with a centred cabin (the v3 cop car came out tail-first). The
concept is a three-quarter FRONT view, so: render the fitted model from the four
diagonal three-quarter views (two show the +z end, two the -z end; one of each pair
is the mirror side), embed renders and the concept's cut-out with DINOv2, and
compare. If the -z renders match the concept better, the model is backwards.

    nose_from_concept.py model.glb concept_3q.png [class]  -> front/rear similarity and the verdict
    nose_from_concept.py --protos <v1 GLBs...>              -> gen3d/work/nose_protos.npz
"""
import os, sys, math
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
GEN3D = os.path.join(HERE, '..', '..', 'gen3d')
sys.path.insert(0, GEN3D)
os.environ.setdefault('U2NET_HOME', os.path.expanduser('~/.rembg/models/u2net'))
BG = (237, 237, 237)
_M = {}


def _dino():
    if 'dino' not in _M:
        import torch
        hub = os.path.expanduser('~/.cache/torch/hub/facebookresearch_dinov2_main')
        m = torch.hub.load(hub, 'dinov2_vitl14_reg', source='local', pretrained=True)
        _M['dino'] = m.eval().cuda().half()
    return _M['dino']


def _square(img, size=448):
    """Crop to the object (anything not background grey), pad to a square, resize."""
    a = np.asarray(img.convert('RGB')).astype(int)
    fg = np.abs(a - np.array(BG)).max(-1) > 10
    ys, xs = np.where(fg)
    if len(xs) == 0:
        return img.convert('RGB').resize((size, size))
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = a.shape[:2]; s = int(max(h, w) * 1.08)
    canvas = np.full((s, s, 3), BG, np.uint8)
    canvas[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = a
    return Image.fromarray(canvas).resize((size, size), Image.LANCZOS)


def _embed(imgs):
    import torch
    x = np.stack([np.asarray(i, np.float32) / 255 for i in imgs])
    x = (x - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
    t = torch.tensor(x.transpose(0, 3, 1, 2), dtype=torch.float16, device='cuda')
    with torch.no_grad():
        f = _dino().forward_features(t)
    v = torch.cat([f['x_norm_clstoken'], f['x_norm_patchtokens'].mean(1)], 1).float()
    return torch.nn.functional.normalize(v, dim=1).cpu().numpy()


def concept_cutout(path):
    import rembg
    if 'rembg' not in _M:
        _M['rembg'] = rembg.new_session('u2net')
    cut = rembg.remove(Image.open(path).convert('RGB'), session=_M['rembg'])
    bg = Image.new('RGBA', cut.size, BG + (255,)); bg.alpha_composite(cut)
    return _square(bg)


def renders(glb, size=448):
    import render_glb as R
    import nvdiffrast.torch as dr
    import trimesh
    if 'ctx' not in _M:
        _M['ctx'] = dr.RasterizeCudaContext()
    out = []
    for deg in (0, 90, 180, 270):          # camera at (+x,+z): 0/90 see the +z end, 180/270 the -z end
        meshes = R.load(glb)
        T = trimesh.transformations.rotation_matrix(math.radians(deg), (0, 1, 0))
        for m in meshes:
            m.apply_transform(T)
        out.append(_square(Image.fromarray(R.render(meshes, '3q', size, _M['ctx'])), size))
    return out


PROTOS = os.path.join(GEN3D, 'work', 'nose_protos.npz')
CAR_CLASSES = ('sedan', 'coupe', 'sports', 'limo', 'compact', 'microcar', 'muscle', 'police', 'taxi')


def _protos():
    """Mean DINOv2 embedding of the v1 models' front and rear three-quarter renders (59 models whose
    nose was checked in game; 069 left out). Built once by protos(); used to tell whether a concept
    shows the front or the back of the car, and which end of a fitted model looks like a front."""
    if 'protos' not in _M:
        P = np.load(PROTOS)
        f, r = P['front'].mean(0), P['rear'].mean(0)
        _M['protos'] = (f / np.linalg.norm(f), r / np.linalg.norm(r))
    return _M['protos']


def build_protos(glbs):
    F, R = [], []
    for p in glbs:
        e = _embed(renders(p)); F += [e[0], e[1]]; R += [e[2], e[3]]
    np.savez(PROTOS, front=np.array(F), rear=np.array(R))


def check(glb, concept, cls=None):
    """backwards: the fitted model's -z end is the one that looks like the concept's visible end,
    corrected when the concept itself shows the car from behind (SDXL draws a rear three-quarter view
    now and then: 013 Minx). concept_front_margin < -0.03 counts as a rear view for car classes; for
    trucks and buses the prototypes (sedans mostly) are not reliable enough. proto_margin > 0: the +z
    end looks more like a front than the -z end does, independent of the concept."""
    rs = renders(glb)
    e = _embed([concept_cutout(concept)] + rs)
    sim = e[1:] @ e[0]
    front, rear = float(max(sim[0], sim[1])), float(max(sim[2], sim[3]))
    res = dict(nose_front=front, nose_rear=rear, nose_sims=[round(float(s), 4) for s in sim])
    concept_rear = False
    if os.path.exists(PROTOS):
        Fm, Rm = _protos()
        cm = float(e[0] @ Fm - e[0] @ Rm)
        pm = float(np.mean(e[1:3] @ Fm - e[1:3] @ Rm) - np.mean(e[3:5] @ Fm - e[3:5] @ Rm))
        concept_rear = cm < -0.03 and (cls is None or cls in CAR_CLASSES)
        res.update(concept_front_margin=round(cm, 4), proto_margin=round(pm, 4), concept_is_rear=concept_rear)
    match_minus = rear > front + 0.01
    res['backwards'] = bool(match_minus != concept_rear)
    if concept_rear:      # the concept's visible end is the back: the matched end is the rear
        res['nose_front'], res['nose_rear'] = rear, front
    return res


if __name__ == '__main__':
    if sys.argv[1] == '--protos':          # nose_from_concept.py --protos v1_a.glb v1_b.glb ...
        build_protos(sys.argv[2:])
    else:
        print(check(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
