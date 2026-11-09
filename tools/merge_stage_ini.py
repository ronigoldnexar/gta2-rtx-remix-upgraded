#!/usr/bin/env python3
"""Build the stage's gta2dx9.ini for restage.sh: the committed package/gta2dx9.ini (every documented key,
one section each) with the running stage's deliberate overrides re-applied.

Usage: merge_stage_ini.py <package.ini> <stage.ini or missing> <out.ini>

An override is a key present in both files whose stage value differs from the package value (e.g. the play
page's [visuals] enabled=1). Keys that exist only in the stage ini are appended to their section. Keys that are
new in the package ini arrive with their documented default. Only the first occurrence of a section is read,
like Wine's GetPrivateProfileString, so a stale duplicate section in the old stage ini contributes nothing.
Prints one line per override so the restage log shows what the play page keeps.
"""
import re, sys

# Former package defaults: a stage value equal to one of these was the default when the stage was built, not a
# deliberate override, so the package's current default replaces it (printed as "retired default").
# FIX-SMOOTH-SWITCH, 9 Nov: the classic->3D dissolve (45) is replaced by a camera move with no image effect (0).
RETIRED = {("camera", "switch_dissolve_percent"): {"45"}}

def parse(path):
    """-> {(section, key): value} using the first occurrence of each section and key."""
    d = {}; seen = set(); sec = None; active = False
    for line in open(path, errors="replace"):
        line = line.rstrip("\r\n")
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            sec = m.group(1); active = sec not in seen; seen.add(sec); continue
        m = re.match(r"^([A-Za-z_0-9]+)=(.*)$", line)
        if m and sec and active:
            d.setdefault((sec, m.group(1)), m.group(2))
    return d

def main():
    pkg_path, stage_path, out_path = sys.argv[1:4]
    pkg = parse(pkg_path)
    try:
        stage = parse(stage_path)
    except FileNotFoundError:
        stage = {}
    overrides = {k: v for k, v in stage.items() if k in pkg and pkg[k] != v and v not in RETIRED.get(k, ())}
    for k, v in stage.items():
        if k in pkg and pkg[k] != v and v in RETIRED.get(k, ()):
            print(f"stage ini: retired default [{k[0]}] {k[1]}={v} replaced by the package's {pkg[k]}")
    extras = {k: v for k, v in stage.items() if k not in pkg}
    out = []; sec = None; seen = set(); pending_extras = {}
    for k, v in extras.items():
        pending_extras.setdefault(k[0], []).append((k[1], v))
    def flush_extras(s):
        for key, val in pending_extras.pop(s, []):
            out.append(f"{key}={val}"); print(f"stage ini: kept stage-only key [{s}] {key}={val}")
    for line in open(pkg_path, errors="replace"):
        line = line.rstrip("\r\n")
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            if sec is not None: flush_extras(sec)
            sec = m.group(1); seen.add(sec); out.append(line); continue
        m = re.match(r"^([A-Za-z_0-9]+)=(.*)$", line)
        if m and sec and (sec, m.group(1)) in overrides:
            val = overrides.pop((sec, m.group(1)))
            out.append(f"{m.group(1)}={val}")
            print(f"stage ini: kept override [{sec}] {m.group(1)}={val} (package default {m.group(2)})")
            continue
        out.append(line)
    if sec is not None: flush_extras(sec)
    for s, items in pending_extras.items():
        out.append(f"[{s}]"); print(f"stage ini: kept stage-only section [{s}]")
        for key, val in items: out.append(f"{key}={val}"); print(f"stage ini: kept stage-only key [{s}] {key}={val}")
    nl = "\r\n" if "\r\n" in open(pkg_path, "rb").read(4096).decode(errors="replace") else "\n"   # keep the package file's line endings
    with open(out_path, "w", newline="") as f:
        f.write(nl.join(out) + nl)

if __name__ == "__main__":
    main()
