#!/usr/bin/env python3
"""Packs the release archives that cannot live in git (they embed the game's own
artwork) or that carry a build, the same way on Linux and Windows.

    python3 tools/pack_release.py <out dir> [linux|people|cars|textures|remix ...]

Run from the repository root after `make stage` (or `package.bat`). With no names
every archive is written. Each archive is written whole (an existing file of the
same name is replaced), entries in sorted order, and its listing is checked
against the source tree afterwards. Layout (paths inside the zip):

  gta2dx9-x86-linux-built.zip  gta2dx9-linux-built/{gta2dx9.dll, d3ddll.dll, gta2dx9_vid.dll,
                               Dmavideo.dll, DMAGlide.dll, gta2dx9.ini, install.reg, uninstall.reg}
                               from stage/, plus gta2dx9-linux-built/linux/... (the committed linux/
                               tree at HEAD, read from git, so local edits never ship)
  gta2dx9_models_people.zip    assets/models/human_*   (41 Rocketbox avatars, MIT, re-imported)
  gta2dx9_models_cars.zip      assets/models/0NN_*     (the generated car models)
  textures_hd_dds.zip          assets/textures_hd/{wil,bil,ste}/*.dds
  remix_mod_gta2hd.zip         gta2hd/{mod.usda, mod_wet.usda, pbr.json, textures/*.dds}, store-only (what
                               linux/docker/build_remix_mod.sh ZIP=1 writes)

Unpack the asset archives at the repository root (`make stage` then copies
assets/models and assets/textures_hd into stage/); the Remix one into
package/rtx-remix/mods/ (or rtx-remix/mods/ beside gta2.exe).
"""
import os, re, subprocess, sys, zipfile

STAGE_FILES = ["gta2dx9.dll", "d3ddll.dll", "gta2dx9_vid.dll", "Dmavideo.dll", "DMAGlide.dll",
               "gta2dx9.ini", "install.reg", "uninstall.reg"]


def entries(name):
    """(path in the zip, path on disk) pairs for one archive"""
    if name == "linux":
        out = [(f"gta2dx9-linux-built/{f}", os.path.join("stage", f)) for f in STAGE_FILES]
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD", "linux"], capture_output=True, text=True, check=True).stdout.split()
        out += [(f"gta2dx9-linux-built/{f}", "git:" + f) for f in files]   # as committed at HEAD, not the working tree
        return "gta2dx9-x86-linux-built.zip", out, zipfile.ZIP_DEFLATED
    if name in ("people", "cars"):
        pat = re.compile(r"^human_" if name == "people" else r"^\d{3}_")
        fs = sorted(f for f in os.listdir("assets/models") if pat.match(f))
        return f"gta2dx9_models_{name}.zip", [(f"assets/models/{f}", f"assets/models/{f}") for f in fs], zipfile.ZIP_DEFLATED
    if name == "textures":
        out = []
        for r, _, fs in os.walk("assets/textures_hd"):
            out += [(os.path.join(r, f).replace(os.sep, "/"),) * 2 for f in fs]
        return "textures_hd_dds.zip", out, zipfile.ZIP_DEFLATED
    if name == "remix":
        base = "package/rtx-remix/mods/gta2hd"
        out = [(f"gta2hd/{f}", f"{base}/{f}") for f in ("mod.usda", "mod_wet.usda", "pbr.json") if os.path.isfile(f"{base}/{f}")]
        out += [(f"gta2hd/textures/{f}", f"{base}/textures/{f}") for f in os.listdir(f"{base}/textures")]
        return "remix_mod_gta2hd.zip", out, zipfile.ZIP_STORED
    raise SystemExit(f"unknown archive {name}")


def pack(outdir, name):
    zname, items, method = entries(name)
    items = sorted(items)
    missing = [d for _, d in items if not d.startswith("git:") and not os.path.isfile(d)]
    if missing or not items:
        raise SystemExit(f"{zname}: {len(missing)} missing source files, e.g. {missing[:3]}" if missing else f"{zname}: nothing to pack")
    path = os.path.join(outdir, zname); tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", method, compresslevel=9 if method == zipfile.ZIP_DEFLATED else None) as z:
        for arc, disk in items:
            if disk.startswith("git:"):
                data = subprocess.run(["git", "show", "HEAD:" + disk[4:]], capture_output=True, check=True).stdout
                mode = subprocess.run(["git", "ls-tree", "HEAD", disk[4:]], capture_output=True, text=True).stdout.split()[0]
                zi = zipfile.ZipInfo(arc, (2026, 1, 1, 0, 0, 0))
                zi.external_attr = (0o100755 if mode == "100755" else 0o100644) << 16
                z.writestr(zi, data, compress_type=method)
            else:
                z.write(disk, arc)
    os.replace(tmp, path)
    with zipfile.ZipFile(path) as z:
        bad = z.testzip(); names = z.namelist()
    assert bad is None and names == [a for a, _ in items], f"{zname}: check failed ({bad})"
    print(f"{zname}: {len(items)} files, {os.path.getsize(path):,} bytes")


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "release"
    os.makedirs(outdir, exist_ok=True)
    for n in sys.argv[2:] or ["linux", "people", "cars", "textures", "remix"]:
        pack(outdir, n)
