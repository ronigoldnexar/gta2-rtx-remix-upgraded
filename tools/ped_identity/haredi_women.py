"""PEDS-VARIETY-3 prototype: a Haredi woman from a Rocketbox woman. Blender 4.2, headless:
  blender -b --factory-startup --python haredi_women.py -- <in.glb> <out.glb> <cover: tichel|snood> <cover rgb> <skirt +m>
Removes the hair cards, covers the hair with a cloth shell skinned to the head, lengthens the skirt by extruding
its hem (UVs from the hem, so the importer's clothing zone and the tint follow), and writes a UV mask of the
lower legs (<out>.legs.npy) for the opaque-stockings texture pass."""
import bpy, bmesh, sys, math, numpy as np
from mathutils import Vector
a = sys.argv[sys.argv.index('--') + 1:]
src, out, cover, cover_rgb, ext = a[0], a[1], a[2], [int(x) / 255 for x in a[3].split(',')], float(a[4])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
body = [o for o in bpy.data.objects if o.type == 'MESH' and any('_head' in m.name for m in o.data.materials)][0]
mats = body.data.materials
head_mi = [i for i, m in enumerate(mats) if m.name.endswith('_head')][0]
body_mi = [i for i, m in enumerate(mats) if m.name.endswith('_body')][0]
op_mi = [i for i, m in enumerate(mats) if m.name.endswith('_opacity')]
mw = body.matrix_world; mwi = mw.inverted()

def mat(name, rgb, rough=0.95, streak=0.08):
    m = bpy.data.materials.new(name); m.use_nodes = True
    N = 64; rng = np.random.default_rng(3)
    t = np.clip(1 + streak * rng.normal(0, 1, (N, N)), 0.8, 1.2)
    px = np.ones((N, N, 4), np.float32)
    for k in range(3): px[..., k] = np.clip(rgb[k] * t, 0, 1)
    img = bpy.data.images.new(name + '_tex', N, N); img.pixels = px.ravel(); img.pack()
    tx = m.node_tree.nodes.new('ShaderNodeTexImage'); tx.image = img
    m.node_tree.links.new(tx.outputs['Color'], m.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    return m

def skin_to(o, bone):
    mwo = o.matrix_world.copy(); o.parent = arm; o.matrix_world = mwo
    vg = o.vertex_groups.new(name=bone); vg.add(list(range(len(o.data.vertices))), 1.0, 'REPLACE')
    md = o.modifiers.new('Armature', 'ARMATURE'); md.object = arm

bm = bmesh.new(); bm.from_mesh(body.data); bm.transform(mw); bm.normal_update()
bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
H = np.array([v.co[:] for f in bm.faces if f.material_index == head_mi for v in f.verts])
top = H[:, 2].max(); mid = H[np.abs(H[:, 1]) < 0.012]; nose = mid[np.argmin(mid[:, 0])]; nx, nz = nose[0], nose[2]
print('landmarks top %.3f nose x %.3f z %.3f' % (top, nx, nz))

# ---- the head covering. Hair outside the skull goes first (a ponytail, a bun, long hair); then a cloth shell is
# shrink-wrapped onto what is left of the head (it follows the skull, so the forehead edge lies on the skin: no
# rim), with soft diagonal folds. A tichel adds a knot and two tails at the nape; a snood a soft gathered bag.
F = H[(H[:, 0] - nx < 0.20)]
crown = F[np.abs(F[:, 1]) < 0.03]; top_z = crown[:, 2].max()
side = F[np.abs(F[:, 2] - (nz + 0.05)) < 0.015]; half_w = np.abs(side[:, 1]).max()
cx, cz = nx + 0.098, nz + 0.030
rx, ry, rz = 0.118, min(half_w + 0.014, 0.100), (top_z - cz) + 0.014   # (a wide mane must not widen the skull)
def inside(p, m=0.0):
    return ((p[0] - cx) / (rx + m)) ** 2 + (p[1] / (ry + m)) ** 2 + ((p[2] - cz) / (rz + m)) ** 2 <= 1.0
def covered(p):
    x, y, z = p; depth = x - nx
    if depth < 0.050: return z > nz + 0.066
    if depth < 0.105: return z > nz + 0.066 - 0.75 * (depth - 0.050)
    return z > nz - 0.075
hair = [f for f in bm.faces if f.material_index == head_mi and any((v.co.x - nx > 0.03) and not inside(v.co, 0.004)
        and (v.co.z > nz - 0.03 or v.co.x - nx > 0.19 or abs(v.co.y) > 0.066) and v.co.z > nz - 0.30 for v in f.verts)]
hair_set = set(hair)
# the shrink-wrap target: the head without the hair
tb = bmesh.new(); tmap = {}
for f in bm.faces:
    if f.material_index != head_mi or f in hair_set: continue
    vs = []
    for v in f.verts:
        if v.index not in tmap: tmap[v.index] = tb.verts.new(v.co.copy())
        vs.append(tmap[v.index])
    try: tb.faces.new(vs)
    except ValueError: pass
tme = bpy.data.meshes.new('skull'); tb.to_mesh(tme); tb.free()
target = bpy.data.objects.new('skull', tme); bpy.context.collection.objects.link(target)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=40, radius=1.0, location=(0, 0, 0))
sph = bpy.context.object
sb = bmesh.new(); sb.from_mesh(sph.data)
for v in sb.verts: v.co = Vector((cx + rx * v.co.x, ry * v.co.y, cz + rz * v.co.z))
bmesh.ops.delete(sb, geom=[v for v in sb.verts if not covered(v.co)], context='VERTS')
sb.to_mesh(sph.data); sb.free()
sw = sph.modifiers.new('wrap', 'SHRINKWRAP'); sw.target = target; sw.wrap_method = 'NEAREST_SURFACEPOINT'; sw.offset = 0.009
bpy.context.view_layer.objects.active = sph; sph.select_set(True); bpy.ops.object.modifier_apply(modifier='wrap'); sph.select_set(False)
sb = bmesh.new(); sb.from_mesh(sph.data); sb.normal_update()
import heapq
sb.verts.ensure_lookup_table()
dist = {v: (0.0 if v.is_boundary else 1e9) for v in sb.verts}
pq = [(0.0, i, v) for i, v in enumerate(sb.verts) if v.is_boundary]; heapq.heapify(pq); cnt = len(pq)
while pq:
    dd, _, v = heapq.heappop(pq)
    if dd > dist[v]: continue
    for e in v.link_edges:
        w = e.other_vert(v); nd = dd + e.calc_length()
        if nd < dist[w]: dist[w] = nd; cnt += 1; heapq.heappush(pq, (nd, cnt, w))
for v in sb.verts:   # soft folds running diagonally round the head, fading out toward the face edge (no rim)
    th = math.atan2(v.co.y, v.co.x - cx); ph = (v.co.z - cz) / rz
    k = min(1.0, dist[v] / 0.025)
    v.co += v.normal * (0.0016 * math.sin(6 * th + 4 * ph) + 0.002) * k - v.normal * 0.004 * (1 - k)
if cover == 'snood':   # the bag: an ellipsoid at the back of the head, low, gathered into pleats toward its top
    bag = bmesh.ops.create_uvsphere(sb, u_segments=40, v_segments=24, radius=1.0)
    for v in bag['verts']:
        th = math.atan2(v.co.y, v.co.x); k = 0.5 + 0.5 * v.co.z
        g = 1 + 0.06 * math.sin(14 * th) * (0.3 + 0.7 * k)
        v.co = Vector((cx + 0.080 + 0.075 * v.co.x * g, 0.074 * v.co.y * g, cz - 0.080 + 0.088 * v.co.z))
else:                  # the knot and two tails
    knot = bmesh.ops.create_uvsphere(sb, u_segments=16, v_segments=10, radius=1.0)
    for v in knot['verts']: v.co = Vector((cx + rx + 0.004 + 0.020 * v.co.x, 0.028 * v.co.y, cz - 0.040 + 0.022 * v.co.z))
    for sy in (-1, 1):
        x0, z0 = cx + rx - 0.004, cz - 0.05
        for face_side in (1, -1):                         # both sides of the cloth (its own vertices each)
            quad = []
            for t in (0.0, 1.0):
                L = 0.15 * t
                for w in (-0.011, 0.011):
                    quad.append(sb.verts.new(Vector((x0 + 0.012 * t + 0.0008 * face_side, sy * (0.012 + 0.03 * t) + w * (1 - 0.3 * t), z0 - L))))
            sb.faces.new((quad[0], quad[1], quad[3], quad[2]) if face_side > 0 else (quad[2], quad[3], quad[1], quad[0]))
sb.to_mesh(sph.data); sb.free()
bpy.data.objects.remove(target)
sph.name = 'cover'; sph.data.materials.append(mat('haredi_cover', cover_rgb))
bpy.ops.object.shade_smooth(); skin_to(sph, 'Bip01 Head')
print('cover: skull rx %.3f ry %.3f rz %.3f, hair faces removed %d' % (rx, ry, rz, len(hair)))

# ---- no hair cards (they would poke through the covering); the eyelashes go with them
dead = [f for f in bm.faces if f.material_index in op_mi] + hair
# ---- the skirt: its hem is the open boundary of the body mesh between the knees and the hips
calf = (arm.matrix_world @ arm.data.bones['Bip01 L Calf'].head_local).z
pelvis = arm.matrix_world @ arm.data.bones['Bip01 Pelvis'].head_local
hem = [e for e in bm.edges if e.is_boundary and all(f.material_index == body_mi for f in e.link_faces)
       and all(calf - 0.06 < v.co.z < pelvis.z - 0.12 for v in e.verts)
       and all(math.hypot(v.co.x - pelvis.x, v.co.y - pelvis.y) > 0.10 for v in e.verts)]
hem_z = float(np.mean([v.co.z for e in hem for v in e.verts])) if hem else None
print('hem edges', len(hem), 'hem z', hem_z, 'calf z', calf)
bmesh.ops.delete(bm, geom=dead, context='FACES')
hem = [e for e in hem if e.is_valid]
if hem and ext > 0:
    defl = bm.verts.layers.deform.active
    r = bmesh.ops.extrude_edge_only(bm, edges=hem)
    newv = [g for g in r['geom'] if isinstance(g, bmesh.types.BMVert)]
    hem_low = min(v.co.z for e in hem for v in e.verts)
    for v in newv:                                         # down to one level (a straight hem), flaring a little
        d = Vector((v.co.x - pelvis.x, v.co.y - pelvis.y, 0))
        v.co += d * 0.05; v.co.z = hem_low - ext
    # the new faces take UVs from the skirt just above the hem (the hem's own texels are its shadowed edge)
    uvl = bm.loops.layers.uv.active
    hem_vs = {v for e in hem for v in e.verts}
    def body_uv(v):
        for l2 in v.link_loops:
            if l2.face.material_index == body_mi and l2.face.is_valid and l2.face not in newf: return l2[uvl].uv.copy()
        return None
    newf = set(g for g in r['geom'] if isinstance(g, bmesh.types.BMFace))
    up_uv = {}
    for hv in hem_vs:
        ups = [e.other_vert(hv) for e in hv.link_edges if e.other_vert(hv) not in newv and e.other_vert(hv) not in hem_vs]
        ups = [u for u in ups if u.co.z > hv.co.z]
        up_uv[hv] = body_uv(max(ups, key=lambda u: u.co.z)) if ups else body_uv(hv)
    for f in newf:
        f.material_index = body_mi
        for l in f.loops:
            if l.vert in newv:
                src_v = [e.other_vert(l.vert) for e in l.vert.link_edges if e.other_vert(l.vert) in hem_vs]
                uv = up_uv.get(src_v[0]) if src_v else None
            else:
                uv = body_uv(l.vert)
            if uv is not None: l[uvl].uv = uv
    print('skirt lengthened by %.2f m (%d verts)' % (ext, len(newv)))
bm.normal_update()
# ---- the lower legs below the hem: their UV polygons, for the stockings
legs = []
if hem_z is not None:
    uvl = bm.loops.layers.uv.active
    for f in bm.faces:
        if f.material_index != body_mi: continue
        c = f.calc_center_median()
        if c.z < hem_z - 0.02 and c.z > calf - 0.42 and math.hypot(c.x - pelvis.x, c.y - pelvis.y) < 0.20:
            q = [tuple(l[uvl].uv) for l in f.loops]; legs.append((q + [q[-1]] * 8)[:8])
neck = arm.matrix_world @ arm.data.bones['Bip01 Neck'].head_local
chest = []
for f in bm.faces:
    if f.material_index != head_mi: continue        # the open collar's skin is the head map's (neck and upper chest)
    c = f.calc_center_median()
    if c.z < neck.z - 0.022 and abs(c.y) < 0.10 and c.x < neck.x + 0.02:
        q = [tuple(l[uvl].uv) for l in f.loops]; chest.append((q + [q[-1]] * 8)[:8])
np.save(out + '.chest.npy', np.array(chest, np.float32).reshape(-1, 8, 2))
print('chest polys', len(chest))
np.save(out + '.legs.npy', np.array(legs, np.float32).reshape(-1, 8, 2))
print('leg polys', len(legs))
bm.transform(mwi); bm.to_mesh(body.data); bm.free()
for o in [o for o in bpy.data.objects if o.name.startswith('Icosphere')]: bpy.data.objects.remove(o)
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_animations=False, export_skins=True)
print('wrote', out)
