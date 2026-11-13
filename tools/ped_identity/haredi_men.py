"""PEDS-VARIETY-3 prototype: a Haredi man from a Rocketbox suit avatar. Blender 4.2, headless:
  blender -b --factory-startup --python haredi_men.py -- <in.glb> <out.glb> <beard rgb> <hat: homburg|fedora> <peyot 0|1>
Adds three meshes skinned 100% to Bip01 Head (beard shell from the face, a felt hat) and optional thin peyot,
and writes a UV mask of the tie/shirt-front region (<out>.tie.npy) for the texture pass."""
import bpy, bmesh, sys, math, numpy as np
from mathutils import Vector
a = sys.argv[sys.argv.index('--') + 1:]
src, out, beard_rgb, hat, peyot = a[0], a[1], [int(x) / 255 for x in a[2].split(',')], a[3], a[4] == '1'
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

# ---- beard: the lower face's faces, pushed out along their normals, fuller toward the chin; a strand texture
def in_beard(p):
    x, y, z = p
    depth = x - nx                                  # 0 at the nose tip, grows toward the back
    if depth > 0.13: return False
    if abs(y) < 0.020 and nz - 0.046 < z < nz - 0.024 and depth < 0.035: return False                # the lips
    if z > nz - 0.014:                              # above the moustache line: only the sideburns, in front of the ears
        return z < nz + 0.045 and 0.085 < depth < 0.13 and abs(y) > 0.05
    if z > nz - 0.030 and depth < 0.075 and abs(y) > 0.034: return False                           # the cheeks' bare front
    return True
bm = bmesh.new(); bm.from_mesh(body.data); bm.transform(mw); bm.normal_update()
bm.faces.ensure_lookup_table()
keep = [f for f in bm.faces if f.material_index == head_mi and sum(in_beard(v.co) for v in f.verts) >= len(f.verts) - 1]
bm2 = bmesh.new(); vmap = {}
uv_src = bm.loops.layers.uv.active; uv_dst = bm2.loops.layers.uv.new('UVMap')
for f in keep:
    vs = []
    for v in f.verts:
        if v.index not in vmap:
            low = max(0.0, (nz - 0.03) - v.co.z)          # below the mouth: fuller and longer
            co = v.co + v.normal * (0.008 + 0.12 * low)
            co.z -= 0.45 * low
            vmap[v.index] = bm2.verts.new(co)
        vs.append(vmap[v.index])
    try:
        nf = bm2.faces.new(vs)
        for l_src, l_dst in zip(f.loops, nf.loops): l_dst[uv_dst].uv = l_src[uv_src].uv
    except ValueError: pass
for _ in range(3): bmesh.ops.smooth_vert(bm2, verts=bm2.verts, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
me = bpy.data.meshes.new('beard'); bm2.to_mesh(me); bm2.free(); bm.free()
beard = bpy.data.objects.new('beard', me); bpy.context.collection.objects.link(beard)
# strand texture: the beard colour with fine vertical streaks (no flat plastic)
N = 128; rng = np.random.default_rng(7)
streak = np.repeat(rng.normal(0, 1, (1, N)), N, 0) * 0.6 + rng.normal(0, 1, (N, N)) * 0.4
streak = np.clip(1 + 0.18 * streak, 0.7, 1.3)
px = np.zeros((N, N, 4), np.float32); px[..., 3] = 1
for k in range(3): px[..., k] = np.clip(beard_rgb[k] * streak, 0, 1)
img = bpy.data.images.new('haredi_beard_tex', N, N); img.pixels = px.ravel(); img.pack()
bm_mat = mat('haredi_beard', beard_rgb)
tex = bm_mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = img
bm_mat.node_tree.links.new(tex.outputs['Color'], bm_mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
beard.data.materials.append(bm_mat)
skin_to_head(beard)
print('beard faces', len(me.polygons))

# ---- hat: brim + crown, black felt, a grosgrain band; homburg = a centre crease and a curled brim
hx = H[:, 0].min() * 0.5 + H[:, 0].max() * 0.5; hy = 0.0
crown_r = 0.5 * (H[:, 1].max() - H[:, 1].min()) * 1.06
base_z = top - 0.072
bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=crown_r + (0.062 if hat == 'fedora' else 0.055), depth=0.008, location=(hx, hy, base_z))
brim = bpy.context.object
bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=crown_r, depth=0.105, location=(hx, hy, base_z + 0.0525))
crown = bpy.context.object
for o in (brim, crown): o.scale = (1.12, 0.95, 1.0)   # longer front to back, as a head is
bpy.ops.object.select_all(action='DESELECT')
# the crown narrows a little to the top and dents along the middle (a homburg's gutter, a fedora's pinch)
bm = bmesh.new(); bm.from_mesh(crown.data)
for v in bm.verts:
    if v.co.z > 0.0:
        v.co.x *= 0.90; v.co.y *= 0.90
        if hat == 'homburg': v.co.z -= 0.022 * max(0.0, 1 - abs(v.co.x) / (crown_r * 0.9))
        else: v.co.z -= 0.025 * max(0.0, 1 - abs(v.co.y) / (crown_r * 0.5)) * (0.6 + 0.4 * (v.co.x > 0))
bm.to_mesh(crown.data); bm.free()
if hat == 'homburg':
    bm = bmesh.new(); bm.from_mesh(brim.data)
    for v in bm.verts:
        r = math.hypot(v.co.x, v.co.y)
        if r > crown_r + 0.03: v.co.z += 0.010 * (r - crown_r - 0.03) / 0.025
    bm.to_mesh(brim.data); bm.free()
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
bmesh.ops.delete(bm, geom=dead, context='FACES'); bm.to_mesh(body.data); bm.free()
print('tie faces removed', len(dead))
for o in [o for o in bpy.data.objects if o.name.startswith('Icosphere')]: bpy.data.objects.remove(o)
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_animations=False, export_skins=True, export_apply=False)
print('wrote', out)
