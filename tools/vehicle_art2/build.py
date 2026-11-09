#!/usr/bin/env python3
"""Build carkit cars and import them into the game's model format.

    gen3d/venv/bin/python tools/vehicle_art2/build.py <out dir> 036 [008 056 ...] [--preview]

<out dir>/src/<name>.glb + <name>/<material>.png (the textures under their material names, so the
renderer can tell glass, chrome and rubber apart: model_store.cpp CarSurfaceFor), then
tools/import_assets.py into <out dir>/models (a fresh dir: never import over assets/models, whose
files are hard-linked into stages). Copy the result with `cp --remove-destination`.
"""
import importlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import carkit  # noqa


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = os.path.abspath(args[0])
    src = os.path.join(out, "src"); models = os.path.join(out, "models")
    os.makedirs(src, exist_ok=True); os.makedirs(models, exist_ok=True)
    entries = []
    for num in args[1:]:
        mod = importlib.import_module(f"car_{num}")
        car = mod.build()
        v, f = car.stats()
        print(f"{mod.NAME}: {v} vertices, {f} triangles")
        mats = carkit.write_glb(car, os.path.join(src, f"{mod.NAME}.glb"), scale=0.2)
        os.makedirs(os.path.join(src, mod.NAME), exist_ok=True)
        tex = {}
        for m in mats:
            p = os.path.join(src, mod.NAME, f"{m}.png")
            car.materials[m].save(p)
            tex[m] = f"{mod.NAME}/{m}.png"
        entries.append({"name": mod.NAME, "glb": f"cars/vehicle_art2/{mod.NAME}.glb", "scale": 1.0, "paint_rgb": [round(float(c), 1) for c in mod.PAINT],
                        "texture_max": 512, "material_textures": {k: "cars/vehicle_art2/" + v for k, v in tex.items()}, "generator": f"tools/vehicle_art2/car_{num}.py"})
        if "--preview" in sys.argv:
            import preview
            preview.sheet(car, os.path.join(out, f"preview_{num}.png"), mod.LEN)
    # the importer resolves paths from the manifest's folder: src/ stands in for assets-src/
    man = os.path.join(src, "manifest.json")
    os.makedirs(os.path.join(src, "cars"), exist_ok=True)
    link = os.path.join(src, "cars", "vehicle_art2")
    if not os.path.exists(link):
        os.symlink(src, link)
    json.dump({"models": entries}, open(man, "w"), indent=1)
    subprocess.check_call([sys.executable, os.path.join(HERE, "..", "import_assets.py"), man, models])
    json.dump(entries, open(os.path.join(out, "entries.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
