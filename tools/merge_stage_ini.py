#!/usr/bin/env python3
"""Build the stage's gta2dx9.ini for restage.sh: the committed package/gta2dx9.ini (every documented key,
one section each) with the running stage's deliberate overrides re-applied.

Usage: merge_stage_ini.py <package.ini> <stage.ini or missing> <out.ini> [<package.ini of the running stage's commit>]

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
RETIRED = {("camera", "switch_dissolve_percent"): {"45"},
           # COORDINATOR shift 79, 10 Nov: three former defaults the stage carried as "overrides" after their package
           # default moved, which kept the owner's fixes off the play page (B5 soft smoke 64c1eb2b, B3 traffic cap 20e5b979,
           # day-night follow_clock f46ec882):
           ("devtools", "remix_puff_mode"): {"1", "2"},
           ("density", "traffic_cap"): {"36"},
           ("sky", "follow_clock"): {"0"}}

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
    prev_path = sys.argv[4] if len(sys.argv) > 4 else None   # the package ini of the commit the running stage was built from
    pkg = parse(pkg_path)
    try:
        stage = parse(stage_path)
    except FileNotFoundError:
        stage = {}
    # A stage value that equals the package default of the commit the stage was built from is not a deliberate override
    # either: the default moved underneath it (restage.sh passes that ini when it can read the staged-from commit).
    retired = {k: set(v) for k, v in RETIRED.items()}
    if prev_path:
        try:
            for k, v in parse(prev_path).items():
                if k in pkg and pkg[k] != v:
                    retired.setdefault(k, set()).add(v)
        except FileNotFoundError:
            pass
    overrides = {k: v for k, v in stage.items() if k in pkg and pkg[k] != v and v not in retired.get(k, ())}
    for k, v in stage.items():
        if k in pkg and pkg[k] != v and v in retired.get(k, ()):
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
