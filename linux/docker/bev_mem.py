#!/usr/bin/env python3
"""BEV parity, memory side: reads the running gta2.exe image from outside the game
(/proc/<pid>/mem, the container needs --cap-add SYS_PTRACE) and diffs every section
against the gta2.exe file on disk. Code bytes that differ are the renderer's patches
into the game; the two view-rectangle PUSH operands are followed to the values the
game's spawn/draw window is really computed from.

  python3 bev_mem.py <label> [out dir]    -> <out>/bev_mem_<label>.json

Independent of the renderer's own log: what it reads is what the game executes."""
import json, os, struct, sys, time

EXE = "/tmp/wp/drive_c/Games/GTA2/gta2.exe"
# game_access.h: kViewHalfScaleSite / kViewAspectSite are the PUSH imm32 operands of
# FUN_0041E7A0; stock they push the addresses of the game's own 0.5 and 0.75 (16.14).
SITES = {"view_half_scale": (0x0041E7F0, 0x005E3F54, 0x2000), "view_aspect": (0x0041E8E4, 0x005E3F34, 0x3000)}


def find_pid():
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            cmd = open(f"/proc/{d}/cmdline", "rb").read().replace(b"\0", b" ").lower()
        except OSError:
            continue
        if b"gta2.exe" in cmd and b"bev_mem" not in cmd and b"winedbg" not in cmd:
            # the process that has the image mapped at 0x400000
            try:
                maps = open(f"/proc/{d}/maps").read()
            except OSError:
                continue
            if "00400000-" in maps:
                return int(d)
    return None


def sections(path):
    data = open(path, "rb").read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
    out = []
    for i in range(nsec):
        o = pe + 24 + optsz + 40 * i
        name = data[o:o + 8].rstrip(b"\0").decode("latin-1")
        vsize, va, rsize, rptr, _, _, _, _, chars = struct.unpack_from("<IIIIIIHHI", data, o + 8)
        out.append(dict(name=name, va=base + va, vsize=vsize, raw=data[rptr:rptr + min(rsize, vsize)], chars=chars))
    return base, out


def runs(a, b, base, gap=8):
    """differing byte ranges of two equal-length buffers, merged across gaps < gap"""
    out, start, last = [], None, None
    for i in range(len(a)):
        if a[i] != b[i]:
            if start is None:
                start = i
            elif i - last > gap:
                out.append((start, last + 1)); start = i
            last = i
    if start is not None:
        out.append((start, last + 1))
    return [dict(at=f"{base + s:08X}", n=e - s, disk=a[s:e][:16].hex(), live=b[s:e][:16].hex()) for s, e in out]


def snapshot(label, outdir="/out"):
    rec = dict(label=label, t=time.time())
    pid = find_pid()
    rec["pid"] = pid
    if pid is None:
        rec["error"] = "gta2.exe process not found"
    else:
        try:
            base, secs = sections(EXE)
            with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
                def rd(addr, n):
                    mem.seek(addr); return mem.read(n)
                rec["sections"] = []
                for s in secs:
                    executable = bool(s["chars"] & 0x20000000)
                    live = rd(s["va"], len(s["raw"]))
                    entry = dict(name=s["name"], va=f"{s['va']:08X}", size=len(s["raw"]), executable=executable)
                    if executable:   # code: every changed byte is a patch
                        entry["diffs"] = runs(s["raw"], live, s["va"])
                    else:            # data changes as the game runs: only say how much
                        entry["changed_bytes"] = sum(1 for x, y in zip(s["raw"], live) if x != y)
                    rec["sections"].append(entry)
                rec["view_rect"] = {}
                for name, (site, stock_addr, stock_val) in SITES.items():
                    operand = struct.unpack("<I", rd(site, 4))[0]
                    value = struct.unpack("<i", rd(operand, 4))[0]
                    rec["view_rect"][name] = dict(operand=f"{operand:08X}", patched=operand != stock_addr,
                                                  value=value, stock=stock_val, ratio=round(value / stock_val, 4))
        except Exception as e:   # noqa: BLE001 - a probe reports, it does not stop the run
            rec["error"] = f"{type(e).__name__}: {e}"
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/bev_mem_{label}.json", "w") as f:
        json.dump(rec, f, indent=1)
    return rec


if __name__ == "__main__":
    r = snapshot(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "/out")
    code = [s for s in r.get("sections", []) if s.get("executable")]
    print("bev_mem", r["label"], r.get("error", ""), "code patches:", sum(len(s["diffs"]) for s in code),
          "view_rect:", {k: v["ratio"] for k, v in r.get("view_rect", {}).items()}, flush=True)
