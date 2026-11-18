"""FIX-FP-ARMS: Blender (4.2, headless) half of tools/gen_fp_arms.py: the dense marching-cubes surfaces (vertex
colours) -> a low-poly mesh per node, unwrapped, the dense colour baked into its texture, a fine skin grain on top,
exported as a .glb in the renderer's model space (no axis conversion: the PLYs are already +y up, +z ahead).

    blender -b --factory-startup --python tools/fp_arms_bake.py -- <out.glb> <scale> <triangles> node=dense.ply ...
"""
import sys, math
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
out_glb, scale, tris = argv[0], float(argv[1]), int(argv[2])
nodes = [a.split("=", 1) for a in argv[3:]]
TEX = 1024

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
scn.render.engine = "CYCLES"
scn.cycles.device = "CPU"
scn.cycles.samples = 4
scn.render.bake.margin = 12
scn.render.bake.use_selected_to_active = True
scn.render.bake.cage_extrusion = 0.0015
scn.render.bake.max_ray_distance = 0.004

total_faces = 0
dense = []
for name, ply in nodes:
    bpy.ops.wm.ply_import(filepath=ply)
    o = bpy.context.selected_objects[0]
    o.name = name + "_dense"
    dense.append((name, o))
    total_faces += len(o.data.polygons)

lows = []
for name, hi in dense:
    # the share of the triangle budget by the dense face count
    want = max(300, int(tris * len(hi.data.polygons) / total_faces))
    bpy.ops.object.select_all(action="DESELECT")
    hi.select_set(True); bpy.context.view_layer.objects.active = hi
    bpy.ops.object.duplicate()
    lo = bpy.context.active_object
    lo.name = name
    m = lo.modifiers.new("dec", "DECIMATE")
    m.ratio = want / max(1, len(lo.data.polygons))
    m.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier="dec")
    bpy.ops.object.shade_smooth()
    # unwrap
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.006, area_weight=0.0, scale_to_bounds=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    for c in list(lo.data.color_attributes):
        lo.data.color_attributes.remove(c)
    # the dense mesh's material: its vertex colour as emission
    mh = bpy.data.materials.new(name + "_hi"); mh.use_nodes = True
    nt = mh.node_tree; nt.nodes.clear()
    ca = nt.nodes.new("ShaderNodeVertexColor"); ca.layer_name = hi.data.color_attributes[0].name
    em = nt.nodes.new("ShaderNodeEmission"); outn = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(ca.outputs["Color"], em.inputs["Color"]); nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
    hi.data.materials.clear(); hi.data.materials.append(mh)
    # the low mesh's material: the texture to bake into
    img = bpy.data.images.new(name + "_tex", TEX, TEX, alpha=False)
    img.colorspace_settings.name = "sRGB"
    ml = bpy.data.materials.new(name); ml.use_nodes = True
    nt = ml.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = img
    nt.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.55 if name == "skin" else 0.9
    bsdf.inputs["Metallic"].default_value = 0.0
    nt.nodes.active = tn
    lo.data.materials.clear(); lo.data.materials.append(ml)
    bpy.ops.object.select_all(action="DESELECT")
    hi.select_set(True); lo.select_set(True); bpy.context.view_layer.objects.active = lo
    bpy.ops.object.bake(type="EMIT")
    # a fine grain over the baked colour: skin mottling and pores, the cloth's weave
    px = np.array(img.pixels[:], np.float32).reshape(TEX, TEX, 4)
    rng = np.random.default_rng(11)
    def blur(a, r):
        k = np.exp(-0.5 * (np.arange(-3 * r, 3 * r + 1) / r) ** 2); k /= k.sum()
        a = np.apply_along_axis(lambda x: np.convolve(np.pad(x, 3 * r, mode="wrap"), k, "valid"), 0, a)
        return np.apply_along_axis(lambda x: np.convolve(np.pad(x, 3 * r, mode="wrap"), k, "valid"), 1, a)
    if name == "skin":
        mott = blur(rng.standard_normal((TEX, TEX)), 9); mott /= np.abs(mott).max()
        pores = blur(rng.standard_normal((TEX, TEX)), 1); pores /= np.abs(pores).max()
        g = 1.0 + 0.045 * mott + 0.03 * pores
        px[..., 0] *= g * (1 + 0.012 * mott); px[..., 1] *= g; px[..., 2] *= g * (1 - 0.01 * mott)
    else:
        y, x = np.mgrid[0:TEX, 0:TEX]
        weave = 0.04 * np.sin(x * 2.2) * np.sin(y * 2.2) + 0.03 * blur(rng.standard_normal((TEX, TEX)), 4) / 0.05
        px[..., :3] *= (1.0 + np.clip(weave, -0.08, 0.08))[..., None]
    px[..., 3] = 1.0
    img.pixels[:] = np.clip(px, 0, 1).ravel()
    img.pack()
    lows.append(lo)
    print(f"bake: {name}: {len(lo.data.polygons)} faces")

for name, hi in dense:
    bpy.data.objects.remove(hi, do_unlink=True)
for lo in lows:
    lo.scale = (scale, scale, scale)
    bpy.ops.object.select_all(action="DESELECT")
    lo.select_set(True); bpy.context.view_layer.objects.active = lo
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", export_yup=False, use_selection=True,
                          export_apply=True, export_texcoords=True, export_normals=True, export_materials="EXPORT",
                          export_image_format="AUTO")
print("bake: wrote", out_glb)
