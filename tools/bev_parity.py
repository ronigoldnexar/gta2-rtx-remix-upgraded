#!/usr/bin/env python3
"""BEV parity check: does a 3D view show the same world, run by the same mechanics, as
the classic bird's-eye view? Reads one run of gamerun/bev_parity.py (keys script
keys_bev_parity.sh) and reports, with frames from both views of the same moment:

  1. world freeze     - paused, the views cycled classic->third->first->classic: every
                        logged object (player, cars, peds) must stay where it was.
  2. classic round trip - the classic frame before and after the cycle (same paused moment).
  3. classic vs 3D content from the classic camera - the frame 0.35 s into the move to
                        third person, while the camera is still the top-down one: terrain
                        difference, global misregistration, and per object (from the log's
                        positions projected with the game's camera extent) how far the 3D
                        body sits from the game's sprite.
  4. mechanics        - the same keys in classic, third and first person: walking speed and
                        turn rate per game frame, and game frames per wall second.
  5. memory           - live gta2.exe code against the file on disk (bev_mem.py), per view,
                        and the view rectangle the game spawns and culls by.

  python3 tools/bev_parity.py <run dir> [report.md] [sheet.png]
Needs numpy and Pillow. Writes <run>/bev_parity_report.json too."""
import json, math, os, re, sys
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw

TS = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\] (.*)$")
PLAYER = re.compile(r"view: player x=([-\d.]+) y=([-\d.]+) z=([-\d.]+) face=([-\d.]+),([-\d.]+) (on foot|driving)")
CAM = re.compile(r"cam\[(\d+)\] bounds=.*?78:([-\d.]+)/\S+ 7C:([-\d.]+)/\S+ 80:([-\d.]+)/\S+ 84:([-\d.]+)/")
FRAME = re.compile(r"view: (?:cars|peds) frame=(\d+)")
VIEWRECT = re.compile(r"view @(\d+): game ([\d.]+) x ([\d.]+) tiles \| frame ([\d.]+) x ([\d.]+) \| (.*)$")
FOV_DEG = 40.0   # [camera] fov_tenths=400 in the shipped ini (the classic camera)


# ---------------------------------------------------------------- log
def read_log(run):
    raw = open(os.path.join(run, "gta2dx9.log"), "rb").read()
    lines, off = [], 0
    day = 0.0
    prev = None
    for b in raw.split(b"\n"):
        s = b.decode("latin-1")
        m = TS.match(s)
        if m:
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
            if prev is not None and t + day < prev - 3600: day += 86400
            prev = t + day
            lines.append((off, prev, m.group(5)))
        off += len(b) + 1
    return lines


def seg(lines, a, b):
    return [l for l in lines if a <= l[0] < b]


def parse_objects(text):
    """{key: (x, y, z, extra)} from one 'view: cars' or 'view: peds' line"""
    out = {}
    if text.startswith("view: peds"):
        for tok in text.split(" ")[4:]:
            p = tok.split(":")
            if len(p) < 11: continue
            try:
                x, y, z = map(float, p[4].split(","))
            except ValueError:
                continue
            out["ped" + p[0]] = (x, y, z, ":".join([p[1], p[5], p[6], p[7], p[8]]))
    elif text.startswith("view: cars"):
        for tok in text.split(" ")[3:]:
            p = tok.split(":")
            if len(p) < 9: continue
            try:
                x, y, z = map(float, p[2].split(","))
            except ValueError:
                continue
            out["car" + p[0]] = (x, y, z, ":".join([p[1], p[3], p[5], p[6], p[7]]))
    return out


def player_of(text):
    m = PLAYER.search(text)
    if not m: return None
    return dict(x=float(m.group(1)), y=float(m.group(2)), z=float(m.group(3)),
                fx=float(m.group(4)), fy=float(m.group(5)), driving=m.group(6) == "driving")


def frame_clock(lines):
    """(wall t, renderer frame) pairs from the cars/peds lines, to put frames on any line"""
    pts = []
    for _, t, s in lines:
        m = FRAME.match(s)
        if m: pts.append((t, int(m.group(1))))
    pts.sort()
    return pts


def frame_at(clock, t):
    if not clock: return None
    ts = [p[0] for p in clock]
    i = np.searchsorted(ts, t)
    if i <= 0: return clock[0][1] - (clock[0][0] - t) * 30
    if i >= len(clock): return clock[-1][1] + (t - clock[-1][0]) * 30
    (t0, f0), (t1, f1) = clock[i - 1], clock[i]
    return f0 + (f1 - f0) * (t - t0) / max(t1 - t0, 1e-6)


# ---------------------------------------------------------------- images
def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def phase_shift(a, b):
    """integer (dx, dy) that best moves b onto a (phase correlation of the grey images)"""
    ga, gb = a.mean(2), b.mean(2)
    ga = ga - ga.mean(); gb = gb - gb.mean()
    w = np.outer(np.hanning(ga.shape[0]), np.hanning(ga.shape[1]))
    fa, fb = np.fft.fft2(ga * w), np.fft.fft2(gb * w)
    r = fa * np.conj(fb); r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    dy, dx = np.unravel_index(np.argmax(c), c.shape)
    if dy > c.shape[0] // 2: dy -= c.shape[0]
    if dx > c.shape[1] // 2: dx -= c.shape[1]
    return int(dx), int(dy), float(c.max() / (c.mean() + 1e-9))


def grad(g):
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]; gy[1:-1, :] = g[2:, :] - g[:-2, :]
    return np.hypot(gx, gy)


def patch_offset(a, b, cx, cy, r, search):
    """where the patch of b around (cx, cy) best matches a (NCC of gradient magnitude)"""
    H, W = a.shape[:2]
    x0, y0, x1, y1 = cx - r, cy - r, cx + r, cy + r
    if x0 - search < 0 or y0 - search < 0 or x1 + search > W or y1 + search > H: return None
    pa = grad(a[y0 - search:y1 + search, x0 - search:x1 + search].mean(2))
    pb = grad(b[y0:y1, x0:x1].mean(2))
    pb = pb - pb.mean(); nb = np.sqrt((pb * pb).sum()) + 1e-6
    best = (-2, 0, 0)
    for dy in range(-search, search + 1, 2):
        for dx in range(-search, search + 1, 2):
            q = pa[search + dy:search + dy + 2 * r, search + dx:search + dx + 2 * r]
            q = q - q.mean()
            ncc = float((q * pb).sum() / (np.sqrt((q * q).sum()) + 1e-6) / nb)
            if ncc > best[0]: best = (ncc, dx, dy)
    return best


# ---------------------------------------------------------------- checks
def check_freeze(lines, ev, tag):
    """objects across the paused window of one moment"""
    names = [e["name"] for e in ev]
    try:
        a = next(e for e in ev if e["name"] == "moment_start" and e.get("moment") == tag)
        b = next(e for e in ev if e["name"] == "moment_end" and e.get("moment") == tag)
    except StopIteration:
        return None
    s = seg(lines, a["log"], b["log"])
    first, moved, gone, born = {}, {}, set(), set()
    seen_keys = []
    switches = sum(1 for _, _, t in s if t.startswith("view: moving the camera to"))
    players = []
    for _, _, text in s:
        if text.startswith("view: player x="):
            p = player_of(text)
            if p: players.append(p)
        objs = parse_objects(text)
        if not objs: continue
        kind = "car" if text.startswith("view: cars") else "ped"
        seen_keys.append((kind, set(objs)))
        for k, v in objs.items():
            if k not in first: first[k] = v; continue
            d = math.dist(first[k][:3], v[:3])
            moved[k] = max(moved.get(k, 0.0), d)
            if v[3] != first[k][3]: moved[k + " state"] = 1.0
    for kind in ("car", "ped"):
        sets = [ks for kk, ks in seen_keys if kk == kind]
        if len(sets) > 1:
            gone |= sets[0] - sets[-1]; born |= sets[-1] - sets[0]
    pmax = max((math.dist((p["x"], p["y"], p["z"]), (players[0]["x"], players[0]["y"], players[0]["z"]))
                for p in players), default=None)
    frames = [int(m.group(1)) for _, _, t in s for m in [FRAME.match(t)] if m]
    return dict(seconds=round(b["t"] - a["t"], 1), view_switches=switches, samples=len(seen_keys),
                frames=(min(frames), max(frames)) if frames else None,
                objects=len(first), max_move=round(max(moved.values(), default=0.0), 3),
                moved=sorted(k for k, v in moved.items() if v > 0.01), despawned=sorted(gone), spawned=sorted(born),
                player_samples=len(players), player_max_move=None if pmax is None else round(pmax, 3))


def camera_for(lines, upto):
    """the last camera extent logged before byte offset `upto`"""
    best = None
    for off, _, t in lines:
        if off >= upto: break
        m = CAM.match(t)
        if m: best = tuple(float(m.group(i)) for i in range(2, 6))
    return best


def objects_at(lines, upto):
    """the last cars/peds/player lines before `upto`"""
    objs, player = {}, None
    for off, _, t in lines:
        if off >= upto: break
        if t.startswith("view: cars") or t.startswith("view: peds"):
            o = parse_objects(t)
            kind = "car" if t.startswith("view: cars") else "ped"
            objs = {k: v for k, v in objs.items() if not k.startswith(kind)}
            objs.update(o)
        elif t.startswith("view: player x="):
            player = player_of(t) or player
    return objs, player


def project(cam, W, H, x, y, z, zref):
    x0, x1, y0, y1 = cam
    s = H / (y1 - y0)
    D = ((y1 - y0) * 0.5) / math.tan(math.radians(FOV_DEG) * 0.5)
    k = D / max(D - (z - zref), 0.5)   # nearer the camera, larger and further out
    return W / 2 + (x - (x0 + x1) / 2) * s * k, H / 2 + (y - (y0 + y1) / 2) * s * k, s


def check_frames(run, lines, ev, tag, sheet_rows):
    shots = {e["label"]: e for e in ev if e["name"] == "shot" and e["label"].startswith(tag)}
    get = lambda suffix: next((e for k, e in shots.items() if k.endswith(suffix)), None)
    c0, c3d, c4 = get("0_classic"), get("1_3d_at_classic_camera"), get("4_classic_again")
    if not (c0 and c3d): return None
    P = lambda e: os.path.join(run, f"bev_{e['label']}.png")
    a, b = load(P(c0)), load(P(c3d))
    H, W = a.shape[:2]
    out = {}
    if c4:
        c = load(P(c4)); d = np.abs(a - c).max(2)
        out["classic_round_trip"] = dict(identical_pixels=round(float((d == 0).mean()), 5),
                                         mean_abs=round(float(d.mean()), 3), max_abs=int(d.max()),
                                         pixels_over_24=int((d > 24).sum()))
    dx, dy, peak = phase_shift(a, b)
    out["global_shift_px"] = dict(dx=dx, dy=dy, peak=round(peak, 1))
    cam = camera_for(lines, c0["log"])
    objs, player = objects_at(lines, c0["log"])
    out["camera_extent"] = cam
    mask = np.zeros((H, W), bool)
    rows = []
    if cam and player:
        zref = player["z"]
        items = [("player", (player["x"], player["y"], player["z"], ""))] + sorted(objs.items())
        for k, v in items:
            px, py, s = project(cam, W, H, *v[:3], zref)
            if not (0 <= px < W and 0 <= py < H): continue
            r = int(s * (0.55 if k.startswith("car") else 0.3))
            x0, y0 = max(0, int(px) - r), max(0, int(py) - r)
            mask[y0:int(py) + r, x0:int(px) + r] = True
            m = patch_offset(a, b, int(px), int(py), max(r, 8), max(6, int(s * 0.35)))
            row = dict(id=k, x=round(v[0], 2), y=round(v[1], 2), z=round(v[2], 2), px=int(px), py=int(py))
            if m:
                ncc, ox, oy = m
                row.update(ncc=round(ncc, 3), off_px=(ox, oy), off_tiles=round(math.hypot(ox, oy) / s, 3))
            rows.append(row)
        out["px_per_tile"] = round(H / (cam[3] - cam[2]), 1)
    out["objects"] = rows
    # terrain parity: away from objects, and away from the HUD's top/bottom bands
    band = np.zeros((H, W), bool); band[int(H * 0.12):int(H * 0.88), :] = True
    terr = band & ~mask
    d = np.abs(a - b).mean(2)
    out["terrain"] = dict(mean_abs=round(float(d[terr].mean()), 2),
                          share_over_32=round(float((d[terr] > 32).mean()), 4))
    sheet_rows.append((tag, [P(e) for e in (c0, c3d, get("2_third"), get("3_first"), c4) if e], d, rows, cam))
    return out


def check_walks(lines, ev):
    clock = frame_clock(lines)
    pl = [(t, player_of(s)) for _, t, s in lines if s.startswith("view: player x=")]
    pl = [(t, p) for t, p in pl if p]
    out = {}
    downs = [e for e in ev if e["name"] in ("key_down", "key_up")]
    for i, e in enumerate(downs):
        if e["name"] != "key_down": continue
        up = next((u for u in downs[i + 1:] if u["name"] == "key_up"), None)
        if not up: continue
        t0, t1 = e["t"] + 0.35, up["t"]          # skip the first steps (start-up)
        samp = [(t, p) for t, p in pl if t0 <= t <= t1]
        if len(samp) < 3: continue
        view, key = e["view"], e["key"]
        rec = out.setdefault(view, dict(speed=[], turn=[], fps=[]))
        f0, f1 = frame_at(clock, samp[0][0]), frame_at(clock, samp[-1][0])
        if f0 is None or f1 is None or f1 - f0 < 5: continue
        frames = f1 - f0
        rec["fps"].append(frames / (samp[-1][0] - samp[0][0]))
        if key == "Up":
            dist = sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for (_, a), (_, b) in zip(samp, samp[1:]))
            rec["speed"].append(dist / frames)
        else:
            ang = 0.0
            for (_, a), (_, b) in zip(samp, samp[1:]):
                d = math.atan2(b["fy"], b["fx"]) - math.atan2(a["fy"], a["fx"])
                d = (d + math.pi) % (2 * math.pi) - math.pi
                ang += abs(d)
            rec["turn"].append(math.degrees(ang) / frames)
    summ = {}
    for v, r in out.items():
        summ[v] = {k: (round(float(np.median(x)), 4) if x else None) for k, x in r.items()}
        summ[v]["segments"] = {k: len(x) for k, x in r.items()}
    return summ


def check_memory(run, ev):
    snaps = {}
    for e in ev:
        if e["name"] != "mem": continue
        p = os.path.join(run, f"bev_mem_{e['label']}.json")
        if os.path.exists(p): snaps[e["label"]] = json.load(open(p))
    if not snaps: return None
    out = {"snapshots": {}}
    base = None
    for label, r in snaps.items():
        if "error" in r: out["snapshots"][label] = dict(error=r["error"]); continue
        diffs = {d["at"]: d for s in r["sections"] if s.get("executable") for d in s["diffs"]}
        if base is None: base = (label, diffs)
        out["snapshots"][label] = dict(code_patch_sites=len(diffs), code_bytes=sum(d["n"] for d in diffs.values()),
                                       view_rect={k: v["ratio"] for k, v in r["view_rect"].items()},
                                       added_vs_first=sorted(set(diffs) - set(base[1])),
                                       removed_vs_first=sorted(set(base[1]) - set(diffs)))
    if base:
        out["sites_at_first_snapshot"] = [dict(at=d["at"], n=d["n"], disk=d["disk"], live=d["live"])
                                          for d in base[1].values()]
    return out


def check_spawn(lines, ev):
    """the game's view rectangle and live peds per view, from the renderer's log"""
    view = "classic"; rects, live = {}, {}
    marks = sorted((e["log"], e) for e in ev if e["name"] in ("shot", "walk_start"))
    for off, _, t in lines:
        if t.startswith("view: Classic (top down)"): view = "classic"
        elif t == "view: Third person": view = "third"
        elif t == "view: First person": view = "first"
        m = VIEWRECT.match(t)
        if m: rects.setdefault(view, set()).add(f"{m.group(2)}x{m.group(3)} ({m.group(6)})")
        if t.startswith("view: peds"):
            mm = re.search(r"live=(\d+)", t)
            if mm: live.setdefault(view, []).append(int(mm.group(1)))
    return dict(game_view_rect={k: sorted(v) for k, v in rects.items()},
                live_peds_median={k: int(np.median(v)) for k, v in live.items()})


# ---------------------------------------------------------------- sheet
def make_sheet(rows, path):
    if not rows: return
    tw, th = 427, 240
    labels = ["classic", "3D, classic camera", "third person", "first person", "classic again", "|classic - 3D|"]
    img = Image.new("RGB", (tw * 6, (th + 20) * len(rows) + 4), (20, 20, 20))
    dr = ImageDraw.Draw(img)
    for r, (tag, paths, diff, objs, cam) in enumerate(rows):
        y = r * (th + 20) + 20
        for c, p in enumerate(paths[:5]):
            im = Image.open(p).convert("RGB")
            if c in (0, 1):   # mark where the log puts every object
                d = ImageDraw.Draw(im)
                for o in objs:
                    col = (255, 60, 60) if o["id"] == "player" else (60, 255, 60) if o["id"].startswith("car") else (80, 200, 255)
                    d.ellipse([o["px"] - 6, o["py"] - 6, o["px"] + 6, o["py"] + 6], outline=col, width=2)
            img.paste(im.resize((tw, th)), (c * tw, y))
        dm = np.clip(diff * 3, 0, 255).astype(np.uint8)
        img.paste(Image.fromarray(dm).convert("RGB").resize((tw, th)), (5 * tw, y))
        for c, l in enumerate(labels):
            dr.text((c * tw + 4, y - 16), f"{tag}: {l}" if c == 0 else l, fill=(230, 230, 230))
    img.save(path)


# ---------------------------------------------------------------- report
def verdicts(rep):
    v = []
    for tag, f in rep["freeze"].items():
        if not f: continue
        ok = f["max_move"] <= 0.01 and not f["despawned"] and not f["spawned"] and (f["player_max_move"] or 0) <= 0.01
        v.append((f"world frozen through the view cycle ({tag})", ok,
                  f"{f['objects']} objects, {f['samples']} samples over {f['seconds']} s, {f['view_switches']} switches, "
                  f"max move {f['max_move']} blocks, spawned {len(f['spawned'])}, despawned {len(f['despawned'])}"))
    for tag, f in rep["frames"].items():
        if not f: continue
        rt = f.get("classic_round_trip")
        if rt:
            v.append((f"classic frame unchanged after classic->third->first->classic ({tag})",
                      rt["identical_pixels"] > 0.98 and rt["pixels_over_24"] < 0.01 * 1280 * 720,
                      f"{rt['identical_pixels'] * 100:.2f}% identical pixels, mean |diff| {rt['mean_abs']}"))
        g = f["global_shift_px"]
        v.append((f"3D world registered on the classic frame ({tag})", abs(g["dx"]) <= 2 and abs(g["dy"]) <= 2,
                  f"shift {g['dx']},{g['dy']} px"))
        offs = [o["off_tiles"] for o in f["objects"] if "off_tiles" in o and o.get("ncc", 0) > 0.3]
        if offs:
            v.append((f"3D bodies on the game's sprites ({tag})", float(np.median(offs)) <= 0.15,
                      f"{len(offs)} matched objects, median offset {np.median(offs):.3f} tiles, worst {max(offs):.3f}"))
    w = rep["walks"]
    base = w.get("classic") or {}
    for view in ("third", "first", "classic2"):
        r = w.get(view)
        if not r or not base.get("speed") or not r.get("speed"): continue
        rel = r["speed"] / base["speed"] - 1
        v.append((f"walking speed per game frame, {view} vs classic", abs(rel) <= 0.05,
                  f"{r['speed']:.4f} vs {base['speed']:.4f} blocks/frame ({rel * 100:+.1f}%)"))
        if r.get("turn") and base.get("turn"):
            relt = r["turn"] / base["turn"] - 1
            v.append((f"turn rate per game frame, {view} vs classic", abs(relt) <= 0.10,
                      f"{r['turn']:.2f} vs {base['turn']:.2f} deg/frame ({relt * 100:+.1f}%)"))
        if r.get("fps") and base.get("fps"):
            v.append((f"game frames per second, {view} vs classic", r["fps"] >= base["fps"] * 0.9,
                      f"{r['fps']:.1f} vs {base['fps']:.1f}"))
    m = rep["memory"]
    if m:
        s = m["snapshots"]
        cls = [k for k in s if "classic" in k and "error" not in s[k]]
        gnd = [k for k in s if ("third" in k or "first" in k) and "error" not in s[k]]
        if cls and gnd:
            same = all(not s[k]["added_vs_first"] and not s[k]["removed_vs_first"] for k in s if "error" not in s[k])
            v.append(("gta2.exe code identical in every view", same,
                      f"{s[cls[0]]['code_patch_sites']} patched sites, same set in {len(s)} snapshots" if same else "differs, see memory"))
            vr = {k: s[k]["view_rect"] for k in s if "error" not in s[k]}
            v.append(("game's spawn/cull window: classic as shipped", all(abs(r - 1) < 1e-3 for k in cls for r in vr[k].values()),
                      "; ".join(f"{k}: {vr[k]}" for k in vr)))
    return v


def main():
    run = sys.argv[1]
    md = sys.argv[2] if len(sys.argv) > 2 else os.path.join(run, "bev_parity_report.md")
    sheet = sys.argv[3] if len(sys.argv) > 3 else os.path.join(run, "bev_parity_sheet.png")
    ev = json.load(open(os.path.join(run, "bev_events.json")))["events"]
    lines = read_log(run)
    tags = sorted({e["moment"] for e in ev if e["name"] == "moment_start"})
    rows = []
    rep = dict(run=os.path.basename(os.path.normpath(run)),
               paused_with=next((e["key"] for e in ev if e["name"] == "paused"), None),
               freeze={t: check_freeze(lines, ev, t) for t in tags},
               frames={t: check_frames(run, lines, ev, t, rows) for t in tags},
               walks=check_walks(lines, ev), memory=check_memory(run, ev), spawn=check_spawn(lines, ev),
               faults=sum(1 for _, _, t in lines if "FAULT" in t))
    rep["verdicts"] = [dict(check=c, ok=bool(o), detail=d) for c, o, d in verdicts(rep)]
    json.dump(rep, open(os.path.join(run, "bev_parity_report.json"), "w"), indent=1, default=str)
    make_sheet(rows, sheet)
    with open(md, "w") as f:
        f.write(f"# BEV parity: {rep['run']}\n\npaused with `{rep['paused_with']}`; faults {rep['faults']}; sheet `{os.path.basename(sheet)}`\n\n")
        f.write("| check | result | detail |\n|---|---|---|\n")
        for r in rep["verdicts"]:
            f.write(f"| {r['check']} | {'PASS' if r['ok'] else 'FAIL'} | {r['detail']} |\n")
        f.write("\n```json\n" + json.dumps({k: rep[k] for k in ("walks", "spawn")}, indent=1, default=str) + "\n```\n")
    for r in rep["verdicts"]:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + ": " + r["detail"])


if __name__ == "__main__":
    main()
