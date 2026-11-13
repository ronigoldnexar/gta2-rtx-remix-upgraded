"""PEDS-VARIETY-3 prototype: a Haredi man from a Rocketbox suit avatar. Blender 4.2, headless:
  blender -b --factory-startup --python haredi_men.py -- <in.glb> <out.glb> <beard rgb> <hat: homburg|fedora> <peyot 0|1>
Adds three meshes skinned 100% to Bip01 Head (beard shell from the face, a felt hat) and optional thin peyot,
and writes a UV mask of the tie/shirt-front region (<out>.tie.npy) for the texture pass."""
import bpy, bmesh, sys, math, numpy as np
from mathutils import Vector
a = sys.argv[sys.argv.index('--') + 1:]
src, out, beard_rgb, hat, peyot = a[0], a[1], [int(x) / 255 for x in a[2].split(',')], a[3], a[4] == '1'
drop_tie = len(a) < 6 or a[5] != 'keeptie'   # keeptie: the tie stays as geometry, painted as the white shirt
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
body = [o for o in bpy.data.objects if o.type == 'MESH' and any('_head' in m.name for m in o.data.materials)][0]
head_mi = [i for i, m in enumerate(body.data.materials) if m.name.endswith('_head')][0]
mw = body.matrix_world
V = [mw @ v.co for v in body.data.vertices]
head_vs = sorted({v for p in body.data.polygons if p.material_index == head_mi for v in p.vertices})
H = np.array([V[i][:] for i in head_vs])
top = H[:, 2].max()
mid = H[np.abs(H[:, 1]) < 0.012]
nose = mid[np.argmin(mid[:, 0])]          # forward is -x
nx, nz = nose[0], nose[2]
print('landmarks top %.3f nose x %.3f z %.3f' % (top, nx, nz))

def mat(name, rgb, rough=0.9):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']; b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
    return m

def skin_to_head(o):
    mwo = o.matrix_world.copy(); o.parent = arm; o.matrix_world = mwo   # keep where it is in the world
    vg = o.vertex_groups.new(name='Bip01 Head'); vg.add(list(range(len(o.data.vertices))), 1.0, 'REPLACE')
    md = o.modifiers.new('Armature', 'ARMATURE'); md.object = arm

# ---- beard: the lower face's faces, pushed out along their normals, fuller toward the chin, tapering to nothing at
# its border; strand cards: the texture's alpha thins to scattered strands toward the border (alpha test), so the
# beard feathers into the cheeks and jaw instead of ending in a hard edge
def in_beard(p):
    x, y, z = p
    depth = x - nx
    if depth > 0.13: return False
    if abs(y) < 0.021 and nz - 0.046 < z < nz - 0.031 and depth < 0.035: return False                # the lower lip
    if z > nz - 0.008:                              # above the moustache: the sideburns, in front of the ears
        return z < nz + 0.045 and 0.085 < depth < 0.13 and abs(y) > 0.05
    if z > nz - 0.030 and depth < 0.070 and abs(y) > 0.036: return False                           # the cheeks' bare front
    return True
bm = bmesh.new(); bm.from_mesh(body.data); bm.transform(mw); bm.normal_update()
bm.faces.ensure_lookup_table()
keep = [f for f in bm.faces if f.material_index == head_mi and sum(in_beard(v.co) for v in f.verts) >= len(f.verts) - 1]
bm2 = bmesh.new(); vmap = {}; base = {}
for f in keep:
    vs = []
    for v in f.verts:
        if v.index not in vmap:
            vmap[v.index] = bm2.verts.new(v.co.copy()); base[vmap[v.index]] = (v.co.copy(), v.normal.copy())
        vs.append(vmap[v.index])
    try: bm2.faces.new(vs)
    except ValueError: pass
bm2.verts.ensure_lookup_table(); bm2.edges.ensure_lookup_table()
import heapq
dist = {v: (0.0 if v.is_boundary else 1e9) for v in bm2.verts}
pq = [(0.0, i, v) for i, v in enumerate(bm2.verts) if v.is_boundary]; heapq.heapify(pq); cnt = len(pq)
while pq:
    dd, _, v = heapq.heappop(pq)
    if dd > dist[v]: continue
    for e in v.link_edges:
        w = e.other_vert(v); nd = dd + e.calc_length()
        if nd < dist[w]: dist[w] = nd; cnt += 1; heapq.heappush(pq, (nd, cnt, w))
FEATHER = 0.016
for v in bm2.verts:
    co, n = base[v]; k = min(1.0, dist[v] / FEATHER)
    low = max(0.0, (nz - 0.03) - co.z)
    p = co + n * ((0.002 + 0.007 * k) + 0.12 * low * k)
    p.z -= 0.45 * low * k
    p.y *= 1.0 - 0.9 * low                                   # the beard narrows toward its point
    v.co = p
for _ in range(3): bmesh.ops.smooth_vert(bm2, verts=bm2.verts, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
uvl = bm2.loops.layers.uv.new('UVMap')
for f in bm2.faces:
    for l in f.loops:
        v = l.vert; k = min(1.0, dist[v] / FEATHER)
        l[uvl].uv = (0.5 + math.atan2(v.co.y, v.co.x - (nx + 0.10)) / (2 * math.pi) * 6.0, 0.02 + 0.96 * k)
me = bpy.data.meshes.new('beard'); bm2.to_mesh(me); bm2.free(); bm.free()
beard = bpy.data.objects.new('beard', me); bpy.context.collection.objects.link(beard)
N = 256; rng = np.random.default_rng(7)
col = rng.random(N); jitter = rng.random((N, N)) * 0.25
vv = np.linspace(0, 1, N)[:, None]
alpha = ((col[None, :] + jitter) < vv * 1.9).astype(np.float32)
streak = np.clip(1 + 0.18 * (np.repeat(rng.normal(0, 1, (1, N)), N, 0) * 0.6 + rng.normal(0, 1, (N, N)) * 0.4), 0.7, 1.3)
px = np.zeros((N, N, 4), np.float32); px[..., 3] = alpha
for k in range(3): px[..., k] = np.clip(beard_rgb[k] * streak, 0, 1)
img = bpy.data.images.new('haredi_beard_tex', N, N, alpha=True); img.pixels = px.ravel(); img.pack()
bm_mat = mat('haredi_beard', beard_rgb); bm_mat.blend_method = 'CLIP'
tex = bm_mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = img
bsdf = bm_mat.node_tree.nodes['Principled BSDF']
bm_mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color']); bm_mat.node_tree.links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
beard.data.materials.append(bm_mat)
skin_to_head(beard)
print('beard faces', len(me.polygons))

# ---- hat: brim + crown, black felt, a grosgrain band; homburg = a centre crease and a curled brim
hx = H[:, 0].min() * 0.5 + H[:, 0].max() * 0.5; hy = 0.0
crown_r = 0.5 * (H[:, 1].max() - H[:, 1].min()) * 1.06
base_z = top - 0.072
bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=crown_r + 0.070, depth=0.008, location=(hx, hy, base_z))
brim = bpy.context.object
bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=crown_r, depth=0.128, location=(hx, hy, base_z + 0.064))
crown = bpy.context.object
for o in (brim, crown): o.scale = (1.12, 0.95, 1.0)   # longer front to back, as a head is
bpy.ops.object.select_all(action='DESELECT')
# the crown narrows a little to the top and dents along the middle (a homburg's gutter, a fedora's pinch)
bm = bmesh.new(); bm.from_mesh(crown.data)
for v in bm.verts:
    if v.co.z > 0.0:
        v.co.x *= 0.92; v.co.y *= 0.92
        r = crown_r * 0.92
        v.co.z -= 0.026 * max(0.0, 1 - abs(v.co.y) / (r * 0.45))           # the centre crease, front to back
        if v.co.x < 0:                                                      # the pinch: two dents at the front
            for sy in (-1, 1):
                d = math.hypot((v.co.x + 0.55 * r) / (0.35 * r), (v.co.y - sy * 0.5 * r) / (0.3 * r))
                if d < 1: v.co.y -= sy * 0.012 * (1 - d); v.co.z -= 0.010 * (1 - d)
bm.to_mesh(crown.data); bm.free()
bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=crown_r * 1.012, depth=0.022, location=(hx, hy, base_z + 0.014))
band = bpy.context.object; band.scale = (1.12, 0.95, 1.0)
felt = mat('haredi_hat', (0.035, 0.035, 0.04)); ribbon = mat('haredi_band', (0.015, 0.015, 0.018), 0.5)
for o, m in ((brim, felt), (crown, felt), (band, ribbon)): o.data.materials.append(m)
for o in (brim, crown, band):
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True); o.select_set(False)
    skin_to_head(o)

# ---- peyot: two thin, short curls in front of the ears, the beard's colour
if peyot:
    for side in (-1, 1):
        y0 = side * (crown_r * 0.93); x0 = nx + 0.10; z0 = nz + 0.035
        pts = [(x0 + 0.0025 * math.cos(t * 3.0), y0 + side * 0.0025 * math.sin(t * 3.0), z0 - 0.010 * t) for t in np.linspace(0, 6.5, 50)]
        cu = bpy.data.curves.new('peyot', 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = 0.0028; cu.bevel_resolution = 2
        sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1)
        for p, c in zip(sp.points, pts): p.co = (*c, 1)
        o = bpy.data.objects.new('peyot', cu); bpy.context.collection.objects.link(o)
        bpy.context.view_layer.objects.active = o; o.select_set(True); bpy.ops.object.convert(target='MESH'); o.select_set(False)
        o.data.materials.append(bpy.data.materials['haredi_beard'])
        skin_to_head(o)

# ---- tzitzit: four thin white strings at each hip, from under the jacket hem, swinging with the thigh
pel = arm.matrix_world @ arm.data.bones['Bip01 Pelvis'].head_local
thigh = arm.matrix_world @ arm.data.bones['Bip01 L Thigh'].head_local
hip_w = abs(thigh.y) + 0.082                      # the hip joint's offset and the thigh's girth under the trousers
white = mat('haredi_tzitzit', (0.86, 0.86, 0.84), 0.8)
for side, bone in ((-1, 'Bip01 L Thigh'), (1, 'Bip01 R Thigh')):
    for k in range(4):
        x0 = pel.x - 0.025 + 0.016 * k; y0 = side * (hip_w + 0.004); z0 = pel.z - 0.07
        L = 0.11 + 0.012 * ((k * 7) % 3)
        bpy.ops.mesh.primitive_cylinder_add(vertices=5, radius=0.0016, depth=L, location=(x0, y0, z0 - L / 2))
        o = bpy.context.object; o.data.materials.append(white)
        mwo = o.matrix_world.copy(); o.parent = arm; o.matrix_world = mwo
        o.vertex_groups.new(name=bone).add(list(range(len(o.data.vertices))), 1.0, 'REPLACE')
        md = o.modifiers.new('Armature', 'ARMATURE'); md.object = arm
print('tzitzit at hip half-width %.3f' % hip_w)

# ---- the tie / shirt-front region in UV space (faces of the body material in a narrow band of the chest front)
body_mi = [i for i, m in enumerate(body.data.materials) if m.name.endswith('_body')][0]
neck = arm.matrix_world @ arm.data.bones['Bip01 Neck'].head_local
uvl = body.data.uv_layers.active.data
polys = []
for p in body.data.polygons:
    if p.material_index != body_mi: continue
    c = sum((V[i] for i in p.vertices), Vector()) / len(p.vertices)
    if abs(c.y) < 0.075 and neck.z - 0.40 < c.z < neck.z + 0.02 and c.x < neck.x - 0.03 and p.normal.x < -0.3:
        polys.append([tuple(uvl[l].uv) for l in p.loop_indices])
np.save(out + '.tie.npy', np.array([q for poly in polys for q in (poly + [poly[-1]] * (8 - len(poly)))[:8]], dtype=np.float32).reshape(-1, 8, 2))
print('tie polys', len(polys))
# no tie: drop the tie's own faces (its UV island at the bottom centre of the suit's body map)
bm = bmesh.new(); bm.from_mesh(body.data); uvl2 = bm.loops.layers.uv.active
dead = []
for f in bm.faces:
    if f.material_index != body_mi: continue
    u = sum(l[uvl2].uv.x for l in f.loops) / len(f.loops); v = sum(l[uvl2].uv.y for l in f.loops) / len(f.loops)
    if 0.33 < u < 0.63 and 0.015 < v < 0.18: dead.append(f)
if drop_tie: bmesh.ops.delete(bm, geom=dead, context='FACES')
else: dead = []
bm.to_mesh(body.data); bm.free()
print('tie faces removed', len(dead))
for o in [o for o in bpy.data.objects if o.name.startswith('Icosphere')]: bpy.data.objects.remove(o)
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_animations=False, export_skins=True, export_apply=False)
print('wrote', out)
