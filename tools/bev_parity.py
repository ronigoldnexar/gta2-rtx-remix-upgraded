#!/usr/bin/env python3
"""BEV parity check: does a 3D view show the same world, run by the same mechanics, as
the classic bird's-eye view? Reads one run of gamerun/bev_parity.py (keys script
keys_bev_parity.sh) and reports, with frames from both views of the same moment:

  1. switches        - the player stands still while the views cycle classic->third->first->
                        classic; every logged object (player, cars, peds, every 2 frames) is
                        tracked through each switch: no jump, and the live peds before/after.
                        (GTA2's pause is not reachable by key in these runs, so the world moves;
                        every frame is compared with the objects at that frame's own time.)
  2. classic round trip - the classic camera and terrain before and after the cycle.
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
# Who patches what in gta2.exe's code (address ranges of the live-vs-disk diffs, 9.6 build),
# and whether it reaches the game's rules. From the DLL sources named; check_memory labels
# every diff with this and flags any it cannot place.
PATCH_OWNERS = [
    (0x00417600, 0x00417D00, "voice_over.cpp EngineSoundInstall: engine sample rate/volume calls", "audio"),
    (0x0041E7F0, 0x0041E7F4, "world_view.cpp ApplyGamePatches: view half-width operand", "SPAWN/CULL WINDOW"),
    (0x0041E8E4, 0x0041E8E8, "world_view.cpp ApplyGamePatches: view aspect operand", "SPAWN/CULL WINDOW"),
    (0x004411B0, 0x004411BA, "gibs.cpp: ped death handler, observed then resumed", "observer"),
    (0x00459690, 0x00459695, "intro_movie.cpp: front-end movie read", "movie"),
    (0x0045A61F, 0x0045A624, "hud_pass.cpp: HUD draw call", "presentation"),
    (0x004806C9, 0x004806CE, "hud_pass.cpp InstallMessageHide: stage-end message (script still advances)", "presentation"),
    (0x00481DF0, 0x00481E63, "intro_movie.cpp: Bink surface and lock/unlock calls", "movie"),
    (0x004B24E3, 0x004B24E9, "voice_over.cpp: radio stereo/mono store", "audio"),
    (0x004B2B6B, 0x004B2B75, "voice_over.cpp: radio downgrade", "audio"),
    (0x004BE060, 0x004BE066, "gibs.cpp: object draw entry, observed then resumed", "observer"),
    (0x004C2120, 0x004C2129, "voice_over.cpp: text lookup", "audio"),
    (0x004C8514, 0x004C8529, "hud_pass.cpp: arrow draw calls", "presentation"),
    (0x004CA440, 0x004CA520, "hud_pass.cpp: the HUD's 19 part calls", "presentation"),
    (0x004D0820, 0x004D0825, "debug_overlay.cpp OptionsButtonInstall: Options opens the F4 panel", "front end"),
    (0x004D144D, 0x004D1452, "intro_movie.cpp: startup movie read", "movie"),
]
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


def patch_offset_at(a, b, ca, cb, r, search):
    """where b's patch around cb best matches a around ca: (NCC of gradient magnitude, dx, dy)"""
    H, W = a.shape[:2]
    (xa, ya), (xb, yb) = ca, cb
    if min(xa - r - search, ya - r - search, xb - r, yb - r) < 0: return None
    if xa + r + search > W or ya + r + search > H or xb + r > W or yb + r > H: return None
    pa = grad(a[ya - r - search:ya + r + search, xa - r - search:xa + r + search].mean(2))
    pb = grad(b[yb - r:yb + r, xb - r:xb + r].mean(2))
    pb = pb - pb.mean(); nb = np.sqrt((pb * pb).sum()) + 1e-6
    best = (-2.0, 0, 0)
    for dy in range(-search, search + 1, 2):
        for dx in range(-search, search + 1, 2):
            q = pa[search + dy:search + dy + 2 * r, search + dx:search + dx + 2 * r]
            q = q - q.mean()
            ncc = float((q * pb).sum() / (np.sqrt((q * q).sum()) + 1e-6) / nb)
            if ncc > best[0]: best = (ncc, dx, dy)
    return best


def ink(img, cx, cy, r):
    """what of the frame around (cx, cy) stands out from the ring of ground around it: the
    object's sprite, or its 3D body seen from the camera. (pixel count, centroid dx, dy from
    (cx, cy), median colour of those pixels) or None near the frame's edge"""
    H, W = img.shape[:2]
    R = int(r * 1.7)
    if cx - R < 0 or cy - R < 0 or cx + R > W or cy + R > H: return None
    box = img[cy - R:cy + R, cx - R:cx + R]
    yy, xx = np.mgrid[-R:R, -R:R]
    inner = (np.abs(xx) < r) & (np.abs(yy) < r)
    bg = np.median(box[~inner], axis=0)
    on = inner & (np.abs(box - bg).max(2) > 40)
    n = int(on.sum())
    if n == 0: return (0, 0.0, 0.0, None)
    return (n, float(xx[on].mean()), float(yy[on].mean()), [int(c) for c in np.median(box[on], axis=0)])


def day_seconds(epoch):
    return epoch % 86400.0   # the renderer's log stamps are UTC wall time, as the container's clock


def timeline(lines):
    """[(t, frame, kind, {key: (x, y, z, extra)})] for cars, peds, and the player"""
    out = []
    for _, t, s in lines:
        if s.startswith("view: cars") or s.startswith("view: peds"):
            m = FRAME.match(s)
            out.append((t, int(m.group(1)) if m else None, "car" if s.startswith("view: cars") else "ped",
                        parse_objects(s)))
        elif s.startswith("view: player x="):
            p = player_of(s)
            if p: out.append((t, None, "player", {"player": (p["x"], p["y"], p["z"], "")}))
    clock = frame_clock(lines)   # the player line has no frame number: from the others' clock
    return [(t, f if f is not None else (round(frame_at(clock, t)) if clock else None), k, o) for t, f, k, o in out]


def objects_at_time(tl, t):
    """every object's position at wall time t, interpolated between the samples around it"""
    res = {}
    for kind in ("car", "ped", "player"):
        ks = [e for e in tl if e[2] == kind]
        before = [e for e in ks if e[0] <= t][-1:] or ks[:1]
        after = [e for e in ks if e[0] > t][:1] or before
        if not before: continue
        (t0, _, _, o0), (t1, _, _, o1) = before[0], after[0]
        w = 0.0 if t1 <= t0 else min(1.0, max(0.0, (t - t0) / (t1 - t0)))
        for k, v in o0.items():
            if k in o1:
                u = o1[k]
                res[k] = tuple(v[i] + (u[i] - v[i]) * w for i in range(3)) + (v[3],)
            else:
                res[k] = v
    return res


def camera_at(lines, t):
    """the last camera extent the renderer logged before wall time t"""
    best = None
    for _, tt, s in lines:
        if tt > t: break
        m = CAM.match(s)
        if m: best = tuple(float(m.group(i)) for i in range(2, 6))
    return best


def check_switches(lines, tl, ev):
    """around each view switch: did anything jump, and did the set of live objects change"""
    out = []
    peds_live = [(t, int(re.search(r"live=(\d+)", s).group(1))) for _, t, s in lines
                 if s.startswith("view: peds") and "live=" in s]
    for e in ev:
        if e["name"] != "switch": continue
        ts = day_seconds(e["t"])
        nxt = [day_seconds(x["t"]) for x in ev if x["name"] in ("switch", "moment_end") and x["t"] > e["t"]]
        tend = min(nxt) if nxt else ts + 10
        win = [x for x in tl if ts - 3.0 <= x[0] <= ts + 3.0 and x[1] is not None]
        tracks = {}
        for t, f, kind, objs in win:
            for k, v in objs.items():
                tracks.setdefault(k, []).append((f, t, v))
        jumps, steps_all = [], []
        for k, tr in tracks.items():
            tr.sort()
            for (f0, t0, a), (f1, t1, b) in zip(tr, tr[1:]):
                if f1 <= f0: continue
                step = math.dist(a[:2], b[:2]) / (f1 - f0)
                steps_all.append(step)
                # a car at speed does ~0.4 blocks a frame; anything faster is a teleport
                if step > 0.6: jumps.append(dict(id=k, frames=(f0, f1), step=round(step, 3), at=round(t1 - ts, 2)))
        before = [n for t, n in peds_live if ts - 2.5 <= t < ts]
        after = [n for t, n in peds_live if ts + 1.5 <= t < tend]
        out.append(dict(moment=e.get("moment"), to=e.get("to"), objects=len(tracks),
                        teleports=jumps, max_step=round(max(steps_all, default=0.0), 3),
                        live_peds_before=int(np.median(before)) if before else None,
                        live_peds_after=int(np.median(after)) if after else None))
    return out


def project(cam, W, H, x, y, z, zref):
    x0, x1, y0, y1 = cam
    s = H / (y1 - y0)
    D = ((y1 - y0) * 0.5) / math.tan(math.radians(FOV_DEG) * 0.5)
    k = D / max(D - (z - zref), 0.5)   # nearer the camera, larger and further out
    return W / 2 + (x - (x0 + x1) / 2) * s * k, H / 2 + (y - (y0 + y1) / 2) * s * k, s


COLOUR_MAX = 60.0  # RGB distance between the median colours of sprite and 3D body
NCC_MIN = 0.5      # below this the 3D body and the sprite do not look alike enough to locate
GRAB_DELAY = 0.1   # x11grab's first frame comes about this long after ffmpeg starts


def shot_time(e):
    return day_seconds(e.get("t_before", e["t"] - 0.3) + GRAB_DELAY)


def place(cam, W, H, objs, zref):
    """{key: (px, py, radius)} for every logged object inside the frame"""
    out = {}
    for k, v in objs.items():
        px, py, s = project(cam, W, H, *v[:3], zref)
        if 0 <= px < W and 0 <= py < H:
            out[k] = (px, py, int(s * (0.55 if k.startswith("car") else 0.3)), s)
    return out


def object_mask(H, W, placed):
    m = np.zeros((H, W), bool)
    for px, py, r, _ in placed.values():
        m[max(0, int(py) - r):int(py) + r, max(0, int(px) - r):int(px) + r] = True
    return m


def check_frames(run, lines, tl, ev, tag, sheet_rows):
    shots = {e["label"]: e for e in ev if e["name"] == "shot" and e["label"].startswith(tag)}
    get = lambda suffix: next((e for k, e in shots.items() if k.endswith(suffix)), None)
    c0, c3d, c4 = get("0_classic"), get("1_3d_at_classic_camera"), get("4_classic_again")
    if not (c0 and c3d): return None
    P = lambda e: os.path.join(run, f"bev_{e['label']}.png")
    a, b = load(P(c0)), load(P(c3d))
    H, W = a.shape[:2]
    ta, tb = shot_time(c0), shot_time(c3d)
    cam = camera_at(lines, ta)
    out = dict(camera_extent=cam, seconds_between=round(tb - ta, 2))
    if not cam: return out
    oa, ob = objects_at_time(tl, ta), objects_at_time(tl, tb)
    zref = oa.get("player", (0, 0, 2.0))[2]
    pa, pb = place(cam, W, H, oa, zref), place(cam, W, H, ob, zref)
    out["px_per_tile"] = round(H / (cam[3] - cam[2]), 1)
    band = np.zeros((H, W), bool); band[int(H * 0.12):int(H * 0.88), :] = True   # HUD rows out
    # 1. the round trip: the classic camera back where it was, the terrain as it was
    if c4:
        tc = shot_time(c4); cam4 = camera_at(lines, tc)
        c = load(P(c4)); pc = place(cam, W, H, objects_at_time(tl, tc), zref)
        keep = band & ~object_mask(H, W, pa) & ~object_mask(H, W, pc)
        d = np.abs(a - c).max(2)
        dx, dy, _ = phase_shift(a, c)
        out["classic_round_trip"] = dict(camera_before=cam, camera_after=cam4, shift_px=(dx, dy),
                                         terrain_identical=round(float((d[keep] == 0).mean()), 4),
                                         terrain_mean_abs=round(float(d[keep].mean()), 3),
                                         terrain_over_24=round(float((d[keep] > 24).mean()), 4))
    # 2. the 3D content from the classic camera against the game's own frame
    dx, dy, peak = phase_shift(a, b)
    out["global_shift_px"] = dict(dx=dx, dy=dy, peak=round(peak, 1))
    rows = []
    for k in sorted(set(pa) & set(pb), key=lambda k: (k != "player", k)):
        (xa, ya, r, s), (xb, yb, _, _) = pa[k], pb[k]
        row = dict(id=k, x=round(oa[k][0], 2), y=round(oa[k][1], 2), z=round(oa[k][2], 2), px=int(xa), py=int(ya),
                   moved_tiles=round(math.dist(oa[k][:2], ob[k][:2]), 3))
        # b's patch at b's position, searched for in a around a's position
        m = patch_offset_at(a, b, (int(xa), int(ya)), (int(xb), int(yb)), max(r, 8), max(6, int(s * 0.35)))
        if m:
            ncc, ox, oy = m
            row.update(ncc=round(ncc, 3), off_px=(ox, oy), off_tiles=round(math.hypot(ox, oy) / s, 3))
        if k.startswith("car"): row["model"] = oa[k][3].split(":")[0]
        ia, ib = ink(a, int(xa), int(ya), r), ink(b, int(xb), int(yb), r)
        if ia and ib and ia[0] > 0:
            row.update(ink_classic=ia[0], ink_3d=ib[0], size_ratio=round(ib[0] / ia[0], 2))
            if ib[0] > 0:
                # where the drawn pixels sit around each frame's own logged position
                row["centroid_off_tiles"] = round(math.hypot(ib[1] - ia[1], ib[2] - ia[2]) / s, 3)
                row["colour_classic"], row["colour_3d"] = ia[3], ib[3]
                row["colour_dist"] = round(math.dist(ia[3], ib[3]), 1)
        rows.append(row)
    out["objects"] = rows
    keep = band & ~object_mask(H, W, pa) & ~object_mask(H, W, pb)
    d = np.abs(a - b).mean(2)
    out["terrain"] = dict(mean_abs=round(float(d[keep].mean()), 2), share_over_32=round(float((d[keep] > 32).mean()), 4))
    sheet_rows.append((tag, [P(e) for e in (c0, c3d, get("2_third"), get("3_first"), c4) if e], d,
                       [dict(id=k, px=int(v[0]), py=int(v[1])) for k, v in pa.items()],
                       [dict(id=k, px=int(v[0]), py=int(v[1])) for k, v in pb.items()]))
    return out


def check_walks(lines, ev):
    """per game frame, from consecutive player samples while a key is held: walking speed
    (the free-walking rate is the upper part of the distribution, since a wall or a
    pedestrian in the way only ever slows him) and turn rate; game frames per wall second"""
    clock = frame_clock(lines)
    pl = [(t, player_of(s)) for _, t, s in lines if s.startswith("view: player x=")]
    pl = [(t, p) for t, p in pl if p]
    out = {}
    downs = [e for e in ev if e["name"] in ("key_down", "key_up")]
    for i, e in enumerate(downs):
        if e["name"] != "key_down": continue
        up = next((u for u in downs[i + 1:] if u["name"] == "key_up"), None)
        if not up: continue
        t0, t1 = day_seconds(e["t"]) + 0.25, day_seconds(up["t"])   # past the first step
        samp = [(t, frame_at(clock, t), p) for t, p in pl if t0 <= t <= t1]
        view, key = e["view"], e["key"]
        rec = out.setdefault(view, dict(speed=[], turn=[], fps=[]))
        if len(samp) >= 2 and samp[-1][0] > samp[0][0]:
            rec["fps"].append((samp[-1][1] - samp[0][1]) / (samp[-1][0] - samp[0][0]))
        for (ta, fa, a), (tb, fb, b) in zip(samp, samp[1:]):
            n = fb - fa
            if n < 0.5: continue
            if key == "Up":
                rec["speed"].append(math.dist((a["x"], a["y"]), (b["x"], b["y"])) / n)
            else:
                d = math.atan2(b["fy"], b["fx"]) - math.atan2(a["fy"], a["fx"])
                d = (d + math.pi) % (2 * math.pi) - math.pi
                rec["turn"].append(abs(math.degrees(d)) / n)
    summ = {}
    for v, r in out.items():
        q = lambda x, p: round(float(np.percentile(x, p)), 4) if x else None
        summ[v] = dict(speed=q(r["speed"], 80), speed_median=q(r["speed"], 50), turn=q(r["turn"], 80),
                       turn_median=q(r["turn"], 50), fps=q(r["fps"], 50),
                       samples=dict(speed=len(r["speed"]), turn=len(r["turn"])))
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
        sites = []
        for d in base[1].values():
            at = int(d["at"], 16)
            own = next((o for o in PATCH_OWNERS if o[0] <= at < o[1]), None)
            sites.append(dict(at=d["at"], n=d["n"], owner=own[2] if own else "UNKNOWN", kind=own[3] if own else "UNKNOWN"))
        out["sites_at_first_snapshot"] = sites
        out["unknown_sites"] = [x["at"] for x in sites if x["owner"] == "UNKNOWN"]
        kinds = {}
        for x in sites: kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
        out["sites_by_kind"] = kinds
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
    for r, (tag, paths, diff, objs_a, objs_b) in enumerate(rows):
        y = r * (th + 20) + 20
        for c, p in enumerate(paths[:5]):
            im = Image.open(p).convert("RGB")
            if c in (0, 1):   # mark where the log puts every object at that frame's time
                d = ImageDraw.Draw(im)
                for o in (objs_a if c == 0 else objs_b):
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
    for sw in rep["switches"]:
        name = f"no object jumps at the switch to {sw['to']} ({sw['moment']})"
        v.append((name, not sw["teleports"], f"{sw['objects']} objects tracked +-3 s, largest step "
                  f"{sw['max_step']} blocks/frame, {len(sw['teleports'])} jumps over 0.6"))
    for tag, f in rep["frames"].items():
        if not f or "objects" not in f: continue
        rt = f.get("classic_round_trip")
        if rt:
            same_cam = rt["camera_before"] and rt["camera_after"] and max(
                abs(x - y) for x, y in zip(rt["camera_before"], rt["camera_after"])) < 0.05
            v.append((f"classic view one key away: camera and frame back after classic->third->first->classic ({tag})",
                      bool(same_cam) and abs(rt["shift_px"][0]) <= 1 and abs(rt["shift_px"][1]) <= 1 and rt["terrain_over_24"] < 0.01,
                      f"camera {rt['camera_before']} -> {rt['camera_after']}, shift {rt['shift_px']} px, terrain "
                      f"{rt['terrain_identical'] * 100:.1f}% identical, {rt['terrain_over_24'] * 100:.2f}% differ by >24"))
        g = f["global_shift_px"]
        v.append((f"3D world registered on the classic frame ({tag})", abs(g["dx"]) <= 2 and abs(g["dy"]) <= 2,
                  f"shift {g['dx']},{g['dy']} px, terrain mean |diff| {f['terrain']['mean_abs']}"))
        objs = f["objects"]
        offs = [o["off_tiles"] for o in objs if "off_tiles" in o and o.get("ncc", 0) >= NCC_MIN]
        if objs:
            v.append((f"3D bodies drawn where the game's sprites are ({tag})", bool(offs) and float(np.median(offs)) <= 0.15,
                      f"{len(offs)} of {len(objs)} objects look alike (gradient NCC >= {NCC_MIN}); "
                      + (f"median offset {np.median(offs):.3f} tiles, worst {max(offs):.3f}" if offs else "no position to compare")
                      + "; unlike: " + (", ".join(f"{o['id']} (NCC {o.get('ncc')})" for o in objs if o.get("ncc", 0) < NCC_MIN) or "none")))
            cs = [o for o in objs if o["id"].startswith("car") and "colour_dist" in o]
            if cs:
                bad = [o for o in cs if o["colour_dist"] > COLOUR_MAX]
                v.append((f"car paint: 3D body the colour of the game's sprite ({tag})", not bad,
                          f"{len(cs) - len(bad)} of {len(cs)} within {COLOUR_MAX} RGB; off: " + (", ".join(
                              f"{o['id']} {o['model']} sprite {o['colour_classic']} vs 3D {o['colour_3d']}" for o in bad) or "none")))
            co = [o["centroid_off_tiles"] for o in objs if "centroid_off_tiles" in o and 0.5 <= o.get("size_ratio", 0) <= 2]
            if co:
                v.append((f"3D bodies centred where the sprites are (drawn-pixel centroids, {tag})", float(np.median(co)) <= 0.15,
                          f"median {np.median(co):.3f} tiles over {len(co)}, worst {max(co):.3f}"))
            for kind in ("player", "ped", "car"):
                rs = [o["size_ratio"] for o in objs if "size_ratio" in o and o["id"].startswith(kind)]
                if rs:
                    v.append((f"{kind}: 3D body covers as much of the top-down frame as the sprite ({tag})",
                              0.5 <= float(np.median(rs)) <= 2.0,
                              f"3D/sprite covered pixels, median {np.median(rs):.2f} over {len(rs)}"))
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
            v.append(("every patch in gta2.exe's code accounted for (no unknown site)", not m.get("unknown_sites"),
                      f"{m.get('sites_by_kind')}; unknown {m.get('unknown_sites')}"))
            v.append(("gta2.exe code identical in every view", same,
                      f"{s[cls[0]]['code_patch_sites']} patched sites, same set in {len(s)} snapshots" if same else "differs, see memory"))
            vr = {k: s[k]["view_rect"] for k in s if "error" not in s[k]}
            # classic: the game's window widened to the frame's aspect only (spawn_offscreen=1:
            # nothing spawns inside the margins a 16:9 frame adds); the shape stays the game's
            widen = rep.get("frame_aspect", 16 / 9) / (4 / 3)
            ok = all(abs(vr[k]["view_half_scale"] - widen) < 0.01 and abs(vr[k]["view_aspect"] * widen - 1) < 0.01
                     for k in cls)
            v.append(("game's spawn/cull window in classic: the shipped window, widened to the frame only", ok,
                      "; ".join(f"{k}: half-width x{vr[k]['view_half_scale']}, aspect x{vr[k]['view_aspect']}" for k in cls)))
            g = [k for k in gnd]
            v.append(("game's spawn/cull window in the 3D views (by design, [camera] GameViewScale)", None,
                      "; ".join(f"{k}: half-width x{vr[k]['view_half_scale']}, aspect x{vr[k]['view_aspect']}" for k in g)
                      + ": cars and peds are created and removed over a larger, square window while a 3D view is up"))
    return v


def status(ok):
    return "NOTE" if ok is None else "PASS" if ok else "FAIL"


def main():
    run = sys.argv[1]
    md = sys.argv[2] if len(sys.argv) > 2 else os.path.join(run, "bev_parity_report.md")
    sheet = sys.argv[3] if len(sys.argv) > 3 else os.path.join(run, "bev_parity_sheet.png")
    ev = json.load(open(os.path.join(run, "bev_events.json")))["events"]
    lines = read_log(run)
    tl = timeline(lines)
    tags = sorted({e["moment"] for e in ev if e["name"] == "moment_start"})
    rows = []
    rep = dict(run=os.path.basename(os.path.normpath(run)),
               switches=check_switches(lines, tl, ev),
               frames={t: check_frames(run, lines, tl, ev, t, rows) for t in tags},
               walks=check_walks(lines, ev), memory=check_memory(run, ev), spawn=check_spawn(lines, ev),
               faults=sum(1 for _, _, t in lines if "FAULT" in t))
    rep["verdicts"] = [dict(check=c, ok=o, detail=d) for c, o, d in verdicts(rep)]
    json.dump(rep, open(os.path.join(run, "bev_parity_report.json"), "w"), indent=1, default=str)
    make_sheet(rows, sheet)
    with open(md, "w") as f:
        f.write(f"# BEV parity: {rep['run']}\n\nfaults {rep['faults']}; sheet `{os.path.basename(sheet)}`\n\n")
        f.write("| check | result | detail |\n|---|---|---|\n")
        for r in rep["verdicts"]:
            f.write(f"| {r['check']} | {status(r['ok'])} | {r['detail']} |\n")
        f.write("\n```json\n" + json.dumps({k: rep[k] for k in ("walks", "spawn", "switches")}, indent=1, default=str) + "\n```\n")
    for r in rep["verdicts"]:
        print(status(r["ok"]), r["check"] + ": " + r["detail"])


if __name__ == "__main__":
    main()
