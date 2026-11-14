#!/usr/bin/env python3
"""Packs the release archives that cannot live in git (they embed the game's own
artwork) or that carry a build, the same way on Linux and Windows.

    python3 tools/pack_release.py [--stage DIR] [--rev REV] <out dir> [linux|people|cars|textures|remix|districts ...]

Run from the repository root after `make stage` (or `package.bat`). For a release, build
the DLLs from a clean worktree of the release commit instead of the shared stage/ (whose
DLLs may come from another commit):
    git worktree add --detach /tmp/rel-wt <rev> && (cd /tmp/rel-wt && make stage)
    python3 tools/pack_release.py --stage /tmp/rel-wt/stage --rev <rev> <out dir> linux
--stage is where the DLL/ini/reg files are read (default stage/); --rev is the commit the
linux/ tree is read from (default HEAD) and is written to gta2dx9-linux-built/BUILD.txt
with the DLLs' SHA-256, so a binary can be traced to its source. With no names
every archive is written. Each archive is written whole (an existing file of the
same name is replaced), entries in sorted order, and its listing is checked
against the source tree afterwards. Layout (paths inside the zip):

  gta2dx9-x86-linux-built.zip  gta2dx9-linux-built/{BUILD.txt, gta2dx9.dll, gta2dx9.map, d3ddll.dll, gta2dx9_vid.dll,
                               Dmavideo.dll, DMAGlide.dll, gta2dx9.ini, gta2dx9_effects.ini, install.reg, uninstall.reg}
                               from stage/, plus gta2dx9-linux-built/linux/... (the committed linux/
                               tree at HEAD, read from git, so local edits never ship)
  gta2dx9_models_people.zip    assets/models/human_*, acc_*   (41 Rocketbox avatars, MIT, re-imported; accessory maps)
  gta2dx9_models_cars.zip      assets/models/0NN_*     (the generated car models)
  textures_hd_dds.zip          assets/textures_hd/{wil,bil,ste}/*.dds
  remix_mod_gta2hd.zip         gta2hd/{mod.usda, mod_wet.usda, pbr.json, textures/*.dds}, store-only (what
                               linux/docker/build_remix_mod.sh ZIP=1 writes)
  gta2dx9_districts.zip        gta2dx9_districts/{wil,ste,bil}.kit2, *.dstyle, kit_NN.dds from stage/ (the facade kit:
                               made from the game's maps by `make districts` / restage.sh, so an archive, not git),
                               store-only (the streams are deflated already)

Unpack the asset archives at the repository root (`make stage` then copies
assets/models and assets/textures_hd into stage/); the Remix one into
package/rtx-remix/mods/ (or rtx-remix/mods/ beside gta2.exe); the districts one beside gta2.exe.
"""
import hashlib, os, re, subprocess, sys, zipfile

STAGE = "stage"
REV = "HEAD"

STAGE_FILES = ["gta2dx9.dll", "gta2dx9.map", "d3ddll.dll", "gta2dx9_vid.dll", "Dmavideo.dll", "DMAGlide.dll",
               "gta2dx9.ini", "gta2dx9_effects.ini", "install.reg", "uninstall.reg"]


def entries(name):
    """(path in the zip, path on disk) pairs for one archive"""
    if name == "linux":
        out = [(f"gta2dx9-linux-built/{f}", os.path.join(STAGE, f)) for f in STAGE_FILES]
        out.append(("gta2dx9-linux-built/BUILD.txt", "build:"))
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", REV, "linux"], capture_output=True, text=True, check=True).stdout.split()
        out += [(f"gta2dx9-linux-built/{f}", "git:" + f) for f in files]   # as committed at REV, not the working tree
        return "gta2dx9-x86-linux-built.zip", out, zipfile.ZIP_DEFLATED
    if name in ("people", "cars"):
        pat = re.compile(r"^(human_|acc_)" if name == "people" else r"^\d{3}_")
        fs = sorted(f for f in os.listdir("assets/models") if pat.match(f))
        return f"gta2dx9_models_{name}.zip", [(f"assets/models/{f}", f"assets/models/{f}") for f in fs], zipfile.ZIP_DEFLATED
    if name == "textures":
        out = []
        for r, _, fs in os.walk("assets/textures_hd"):
            out += [(os.path.join(r, f).replace(os.sep, "/"),) * 2 for f in fs]
        return "textures_hd_dds.zip", out, zipfile.ZIP_DEFLATED
    if name == "districts":
        base = os.path.join(STAGE, "gta2dx9_districts")
        fs = sorted(f for f in os.listdir(base) if f.endswith((".kit2", ".dstyle", ".dds")))
        need = {"wil.kit2", "ste.kit2", "bil.kit2", "wil.dstyle", "ste.dstyle", "bil.dstyle"}
        if not need <= set(fs):
            raise SystemExit(f"gta2dx9_districts.zip: {sorted(need - set(fs))} missing in {base} (make districts)")
        return "gta2dx9_districts.zip", [(f"gta2dx9_districts/{f}", os.path.join(base, f)) for f in fs], zipfile.ZIP_STORED
    if name == "remix":
        base = "package/rtx-remix/mods/gta2hd"
        out = [(f"gta2hd/{f}", f"{base}/{f}") for f in ("mod.usda", "mod_wet.usda", "pbr.json") if os.path.isfile(f"{base}/{f}")]
        out += [(f"gta2hd/textures/{f}", f"{base}/textures/{f}") for f in os.listdir(f"{base}/textures")]
        return "remix_mod_gta2hd.zip", out, zipfile.ZIP_STORED
    raise SystemExit(f"unknown archive {name}")


def pack(outdir, name):
    zname, items, method = entries(name)
    items = sorted(items)
    missing = [d for _, d in items if not d.startswith(("git:", "build:")) and not os.path.isfile(d)]
    if missing or not items:
        raise SystemExit(f"{zname}: {len(missing)} missing source files, e.g. {missing[:3]}" if missing else f"{zname}: nothing to pack")
    path = os.path.join(outdir, zname); tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", method, compresslevel=9 if method == zipfile.ZIP_DEFLATED else None) as z:
        for arc, disk in items:
            if disk == "build:":
                rev = subprocess.run(["git", "rev-parse", REV], capture_output=True, text=True, check=True).stdout.strip()
                lines = [f"source commit: {rev}", "built with mingw-w64 (make stage) from a clean worktree of that commit", ""]
                lines += [f"{hashlib.sha256(open(os.path.join(STAGE, f), 'rb').read()).hexdigest()}  {f}" for f in STAGE_FILES]
                zi = zipfile.ZipInfo(arc, (2026, 1, 1, 0, 0, 0)); zi.external_attr = 0o100644 << 16
                z.writestr(zi, "\n".join(lines) + "\n", compress_type=method)
            elif disk.startswith("git:"):
                data = subprocess.run(["git", "show", f"{REV}:" + disk[4:]], capture_output=True, check=True).stdout
                mode = subprocess.run(["git", "ls-tree", REV, disk[4:]], capture_output=True, text=True).stdout.split()[0]
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
    args = sys.argv[1:]
    while args and args[0] in ("--stage", "--rev") and len(args) > 1:
        if args[0] == "--stage": STAGE = args[1]
        else: REV = args[1]
        args = args[2:]
    outdir = args[0] if args else "release"
    os.makedirs(outdir, exist_ok=True)
    for n in args[1:] or ["linux", "people", "cars", "textures", "remix", "districts"]:
        pack(outdir, n)
