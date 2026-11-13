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

# ---- the head covering: a smooth cloth shell round the skull (an ellipsoid fitted to the scalp), open at the face;
# hair outside it (a ponytail, a bun, long hair) is removed; a snood adds a soft bag at the nape, a tichel a knot
F = H[(H[:, 0] - nx < 0.20)]
crown = F[np.abs(F[:, 1]) < 0.03]; top_z = crown[:, 2].max()
side = F[np.abs(F[:, 2] - (nz + 0.05)) < 0.015]; half_w = np.abs(side[:, 1]).max()
cx, cz = nx + 0.098, nz + 0.030
rx, ry, rz = 0.118, half_w + 0.014, (top_z - cz) + 0.014
def inside(p, m=0.0):
    return ((p[0] - cx) / (rx + m)) ** 2 + (p[1] / (ry + m)) ** 2 + ((p[2] - cz) / (rz + m)) ** 2 <= 1.0
def covered(p):
    x, y, z = p; depth = x - nx
    if depth < 0.050: return z > nz + 0.066                        # the forehead line
    if depth < 0.105: return z > nz + 0.066 - 0.75 * (depth - 0.050)   # down over the temples and the ears
    return z > nz - 0.075                                          # the back of the head to the nape
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=1.0, location=(0, 0, 0))
sph = bpy.context.object
sb = bmesh.new(); sb.from_mesh(sph.data)
for v in sb.verts: v.co = Vector((cx + rx * v.co.x, ry * v.co.y, cz + rz * v.co.z))
if cover == 'snood':      # the bag: a second, softer ellipsoid at the back of the head, low
    bag = bmesh.ops.create_uvsphere(sb, u_segments=32, v_segments=20, radius=1.0)
    for v in bag['verts']: v.co = Vector((cx + 0.072 + 0.075 * v.co.x, 0.072 * v.co.y, cz - 0.085 + 0.09 * v.co.z))
else:                     # the knot of the tichel at the back
    knot = bmesh.ops.create_uvsphere(sb, u_segments=16, v_segments=10, radius=1.0)
    for v in knot['verts']: v.co = Vector((cx + rx + 0.006 + 0.022 * v.co.x, 0.03 * v.co.y, cz - 0.035 + 0.026 * v.co.z))
bmesh.ops.delete(sb, geom=[v for v in sb.verts if not covered(v.co)], context='VERTS')
sb.to_mesh(sph.data); sb.free()
sph.name = 'cover'; sph.data.materials.append(mat('haredi_cover', cover_rgb))
bpy.ops.object.shade_smooth(); skin_to(sph, 'Bip01 Head')
# hair outside the shell goes (only behind the face, never the face itself)
hair = [f for f in bm.faces if f.material_index == head_mi and any((v.co.x - nx > 0.06) and not inside(v.co, 0.004) and (v.co.z > nz - 0.03 or v.co.x - nx > 0.19 or abs(v.co.y) > 0.066) and v.co.z > nz - 0.30 for v in f.verts)]
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
    for v in newv:
        d = Vector((v.co.x - pelvis.x, v.co.y - pelvis.y, 0))
        v.co += d * 0.05 + Vector((0, 0, -ext))           # down, flaring a little
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
np.save(out + '.legs.npy', np.array(legs, np.float32).reshape(-1, 8, 2))
print('leg polys', len(legs))
bm.transform(mwi); bm.to_mesh(body.data); bm.free()
for o in [o for o in bpy.data.objects if o.name.startswith('Icosphere')]: bpy.data.objects.remove(o)
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_animations=False, export_skins=True)
print('wrote', out)
