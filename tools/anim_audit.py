#!/usr/bin/env python3
"""ANIM-BLEND-AUDIT analyser: measures the drawn figures' animation defects from a run made with
GTA2DX9_LOG_JOINTS=1 (gamerun/anim_audit.py drives the scenario) and ranks them.

    python3 tools/anim_audit.py <run dir> [--frames] [--json out.json] [--npc]

Reads <run>/gta2dx9.log ("figj:" lines: the posed feet, pelvis, head and hands in the world per
frame) and <run>/marks.txt (step begin/end and burst start times). Measures, per frame of the
player's figure (and, with --npc, of the people within 1.5 blocks of him):

  skate     a planted foot (within 2.5 cm of its resting ankle height, both frames) that moves
            over the ground, cm per frame; the quality bar's target is < 2 cm
  pop       a joint that jumps in one frame in the body's own frame (relative to the drawn root
            and heading): its move this frame over 8 cm and over 3 x the median of its moves in
            the 8 frames around it. A clip dropped or swapped without a blend is one; a 0.15-0.25 s
            crossfade (the same change over 5-8 frames) or a sprint's steady 15 cm a frame is not.
  snap      a harsh blend: a joint's jerk (second difference) over 20 cm and 2.5 x its surroundings
  teleport  the drawn root moving more than 0.10 block (38 cm) in one frame
  sink      the lower foot more than 4 cm under its resting height (through the ground)
  float     both feet more than 15 cm over their resting height for 4+ frames while upright
  spin      the drawn heading turning faster than 600 deg/s
  lag       the drawn root more than 0.12 block from where the game has him

Every event carries the clips drawn the frame before and the frame of the event ("idle -> walk",
"run+punch"), so a defect names its transition. Events are grouped by (step, kind, transition),
ranked by how far over the threshold the worst one is and how often it happens, and printed as
a table; --frames cuts the worst frame of each of the top groups (and its neighbours) out of the
step's burst video into <run>/audit/ with a contact sheet. Distances: 1 block = 3.80 m (the
0.46-block figure is a 1.75 m adult). See docs/anim-audit.md."""
import argparse, json, math, os, re, statistics, subprocess, sys
from collections import defaultdict

CM = 175.0 / 0.46            # cm per block
LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\] figj: (.*)$")
KV = re.compile(r"(\w+)=(\S+)")
JOINTS = ("lf", "rf", "pv", "he", "lh", "rh")
# The frames: the middle of the 1280x720 picture, where the chase camera keeps him, at 2x
# (--wide: the whole picture).
ZOOM = "crop=640:360:320:220,scale=640:360"
GAME_JUMP = 0.2 * CM          # the game moved him 0.2 block (3 x a sprint frame) in one frame: a warp, respawn or frame hitch
WARP = 1.5 * CM               # a root jump this long is a warp or respawn (the figure snaps by design)
THRESH = dict(warp=WARP, snap=20.0, skate=2.0, pop=8.0, teleport=38.0, sink=4.0, float=15.0, spin=600.0, lag=0.12 * CM)
WEIGHT = dict(warp=0.0, snap=0.5, skate=1.0, pop=1.4, teleport=1.6, sink=0.8, float=0.8, spin=1.0, lag=0.5)


def tsec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def vec(s):
    return tuple(float(v) for v in s.split(","))


def parse_log(path, npc):
    rows = {}
    with open(path, "rb") as f:
        for raw in f:
            if b"figj:" not in raw: continue
            m = LINE.match(raw.decode("latin-1").rstrip())
            if not m: continue
            kv = dict(KV.findall(m.group(5)))
            if kv.get("own") != "1" and not npc: continue
            key = (int(kv["f"]), kv["o"])
            if key in rows: continue          # one line per figure and frame
            r = dict(t=tsec(*m.group(1, 2, 3, 4)), f=key[0], o=kv["o"], own=kv["own"] == "1",
                     st=int(kv["st"]), sub=kv["sub"], act=int(kv["act"]), at=float(kv["at"]), aw=float(kv["aw"]),
                     tr=int(kv["tr"]), ww=float(kv["ww"]), rw=float(kv["rw"]), lod=int(kv["lod"]),
                     hd=float(kv["hd"]), game=vec(kv["game"]), drawn=vec(kv["drawn"]), gy=float(kv["gy"]),
                     A=kv.get("A", "-"), B=kv.get("B", "-"), w=float(kv.get("w", "0")), O=kv.get("O", "-"), L=kv.get("L", "-"),
                     rag=kv.get("rag", "0") == "1")
            for j in JOINTS: r[j] = vec(kv[j])
            rows[key] = r
    by = defaultdict(list)
    for (f, o), r in rows.items(): by[o].append(r)
    for o in by: by[o].sort(key=lambda r: r["f"])
    return by


def parse_marks(path):
    steps, bursts = [], {}
    if not os.path.exists(path): return steps, bursts
    open_steps = {}
    for line in open(path):
        p = line.split()
        if len(p) < 4 or p[1].count(":") != 2 or "." not in p[1]: continue   # tour_lib's WARP lines share the file
        hh, mm, rest = p[1].split(":"); ss, ms = rest.split(".")
        t = tsec(hh, mm, ss, ms)
        if p[2] == "step" and len(p) >= 5:
            if p[4] == "begin": open_steps[p[3]] = t
            elif p[4] == "end" and p[3] in open_steps: steps.append((p[3], open_steps.pop(p[3]), t))
        elif p[2] == "burst":
            bursts[p[3]] = t
    return steps, bursts


def weights(r):
    """the clips drawn and their effective weights: the pair (A toward B by w), then each layer
    (L=clip:w|...) blended over all before it, as model_store applies them"""
    ws = {r["A"]: 1.0}
    def over(c, w):
        for k in ws: ws[k] *= 1.0 - w
        ws[c] = ws.get(c, 0.0) + w
    if r["B"] != "-" and r["w"] > 0: over(r["B"], r["w"])
    for part in r.get("L", "-").split("|"):
        if ":" in part:
            c, w = part.rsplit(":", 1); over(c, float(w))
    return ws


def lead(r):
    """the leading clip (the most weight) and the overlay: what a transition changes"""
    ws = weights(r)
    s = max(ws.items(), key=lambda kv: kv[1])[0]
    return s + (f"+{r['O']}" if r["O"] != "-" else "")


trans_table = {}


def clipsig(r):
    """what is drawn: the leading clip (and a second one carrying 30 % or more), the overlay"""
    ws = sorted(weights(r).items(), key=lambda kv: -kv[1])
    s = ws[0][0]
    if len(ws) > 1 and ws[1][1] >= 0.3: s = f"{ws[0][0]}>{ws[1][0]}" if ws[0][1] < 0.6 else f"{ws[0][0]}/{ws[1][0]}"
    if r["O"] != "-": s += f"+{r['O']}"
    if r["rag"]: s += "+ragdoll"
    return s


def local(r, j):
    """joint j relative to the drawn root, in the heading's frame (x right, y up, z forward), cm"""
    x, y, z = r[j]
    dx, dz = x - r["drawn"][0], z - r["drawn"][1]
    h = r["hd"]; ch, sh = math.cos(h), math.sin(h)
    fwd = dx * sh + dz * ch
    right = dx * ch - dz * sh
    return (right * CM, (y - r["gy"]) * CM, fwd * CM)


def dist(a, b):
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


def step_of(t, steps):
    for name, a, b in steps:
        if a - 0.3 <= t <= b + 0.3: return name
    return "-"


def analyse(series, steps):
    events = []
    per_step = defaultdict(lambda: defaultdict(list))
    per_clip = defaultdict(lambda: defaultdict(list))
    global trans_table
    trans_table = defaultdict(list)
    for o, rs in series.items():
        if len(rs) < 5: continue
        own = rs[0]["own"]
        # resting ankle height: the lower foot while standing in the idle, else the 10th percentile
        rest = [min(r["lf"][1], r["rf"][1]) - r["gy"] for r in rs if r["A"].startswith("idle") and r["w"] < 0.05 and r["act"] == 0]
        allh = sorted(min(r["lf"][1], r["rf"][1]) - r["gy"] for r in rs)
        h0 = statistics.median(rest) if len(rest) > 10 else allh[len(allh) // 10]
        plant = h0 + 2.5 / CM
        loc = [{j: local(r, j) for j in JOINTS} for r in rs]
        moves, jerks = {}, {}
        for i in range(1, len(rs)):
            if rs[i]["f"] - rs[i - 1]["f"] == 1 and rs[i]["lod"] == 0:
                moves[i] = {j: dist(loc[i][j], loc[i - 1][j]) for j in JOINTS}
        for i in range(1, len(rs) - 1):
            if rs[i]["f"] - rs[i - 1]["f"] == 1 and rs[i + 1]["f"] - rs[i]["f"] == 1 and rs[i]["lod"] == 0:
                jerks[i] = {j: math.sqrt(sum((loc[i + 1][j][k] - 2 * loc[i][j][k] + loc[i - 1][j][k]) ** 2 for k in range(3))) for j in JOINTS}
        floating = 0
        for i in range(1, len(rs)):
            a, b = rs[i - 1], rs[i]
            if b["f"] - a["f"] != 1 or b["lod"] != 0: floating = 0; continue
            st = step_of(b["t"], steps)
            trans = clipsig(a) if clipsig(a) == clipsig(b) else f"{clipsig(a)} -> {clipsig(b)}"
            ctx = dict(o=o, own=own, f=b["f"], t=b["t"], step=st, trans=trans, clip=clipsig(b), st=b["st"], act=b["act"])
            ps = per_step[st]
            byclip = per_clip[(own, clipsig(b))]
            dr = math.hypot(b["drawn"][0] - a["drawn"][0], b["drawn"][1] - a["drawn"][1]) * CM
            gj = math.hypot(b["game"][0] - a["game"][0], b["game"][1] - a["game"][1]) * CM
            if dr > WARP or gj > GAME_JUMP:
                events.append(dict(ctx, kind="warp", v=dr)); floating = 0; continue
            # skate: a planted foot moving over the ground
            worst = 0.0
            for j in ("lf", "rf"):
                if a[j][1] - a["gy"] < plant and b[j][1] - b["gy"] < plant:
                    d = math.hypot(b[j][0] - a[j][0], b[j][2] - a[j][2]) * CM
                    worst = max(worst, d)
            ps["skate"].append(worst); byclip["skate"].append(worst)
            if worst > THRESH["skate"]: events.append(dict(ctx, kind="skate", v=worst))
            # teleport and spin of the root
            ps["root"].append(dr)
            if dr > THRESH["teleport"]: events.append(dict(ctx, kind="teleport", v=dr))
            dh = (b["hd"] - a["hd"] + math.pi) % (2 * math.pi) - math.pi
            spin = abs(math.degrees(dh)) * 30.0
            ps["spin"].append(spin)
            if spin > THRESH["spin"]: events.append(dict(ctx, kind="spin", v=spin))
            lag = math.hypot(b["drawn"][0] - b["game"][0], b["drawn"][1] - b["game"][1]) * CM
            if lag > THRESH["lag"]: events.append(dict(ctx, kind="lag", v=lag))
            # sink / float of the feet (not while a ragdoll or the knock-down holds him)
            low = min(b["lf"][1], b["rf"][1]) - b["gy"]
            if not b["rag"] and b["act"] not in (4, 9):
                sink = (h0 - low) * CM
                if sink > THRESH["sink"]: events.append(dict(ctx, kind="sink", v=sink))
                fl = (low - h0) * CM
                floating = floating + 1 if fl > THRESH["float"] and b["st"] not in (3, 4) else 0
                if floating == 4: events.append(dict(ctx, kind="float", v=fl))
            # pops: a joint that jumps in one frame in the body's own frame: its move this frame
            # over 8 cm and over 3 x the median of its moves in the 8 frames around (a clip dropped
            # or swapped without a blend; a 0.15-0.25 s crossfade spreads the same change over
            # 5-8 frames and is not one, nor is a sprint's steady 15 cm a frame).
            if i in moves:
                pw, pj = 0.0, ""
                for j in JOINTS:
                    mv = moves[i][j]
                    around = [moves[k][j] for k in range(i - 4, i + 5) if k != i and k in moves]
                    base = statistics.median(around) if len(around) >= 4 else 0.0
                    if mv > THRESH["pop"] and mv > 3.0 * base and mv - 3.0 * base > pw - 0.0: pw, pj = mv, j
                ps["pop"].append(pw); byclip["pop"].append(pw)
                if pj: events.append(dict(ctx, kind="pop", v=pw, joint=pj))
            # snaps: a harsh blend, the jerk (second difference) over 20 cm and 2.5 x its surroundings
            if i in jerks:
                jworst, jname = 0.0, ""
                for j in JOINTS:
                    jerk = jerks[i][j]
                    around = [jerks[k][j] for k in range(i - 7, i + 8) if abs(k - i) > 1 and k in jerks]
                    base = statistics.median(around) if len(around) >= 4 else 0.0
                    if jerk > THRESH["snap"] and jerk > 2.5 * base and jerk > jworst: jworst, jname = jerk, j
                ps["jerk"].append(max(jerks[i].values()))
                if jname:
                    c = rs[i + 1]
                    t2 = trans if clipsig(b) == clipsig(c) or "->" in trans else f"{clipsig(b)} -> {clipsig(c)}"
                    events.append(dict(ctx, kind="snap", v=jworst, joint=jname, trans=t2))
        # transitions: each change of the leading clip (or of the overlay), and the largest joint
        # jump in the body frame within 3 frames of it, over the median move around (spike, cm)
        for i in range(1, len(rs)):
            a, b = rs[i - 1], rs[i]
            if b["f"] - a["f"] != 1 or b["lod"] != 0: continue
            da, db = lead(a), lead(b)
            if da == db: continue
            spike, joint = 0.0, ""
            for k in range(i - 2, i + 4):
                if k not in moves: continue
                for j in JOINTS:
                    around = [moves[m][j] for m in range(k - 6, k + 7) if abs(m - k) > 3 and m in moves]
                    base = statistics.median(around) if len(around) >= 3 else 0.0
                    if moves[k][j] - base > spike: spike, joint = moves[k][j] - base, j
            trans_table[(own, f"{da} -> {db}")].append((spike, b["f"], joint, step_of(b["t"], steps), b["t"]))
    return events, per_step, per_clip


def group(events):
    g = defaultdict(list)
    for e in events:
        g[(e["own"], e["step"], e["kind"], e["trans"])].append(e)
    out = []
    for (own, st, kind, trans), es in g.items():
        w = max(es, key=lambda e: e["v"])
        ratio = w["v"] / THRESH[kind]
        score = WEIGHT[kind] * ratio * (1.0 + math.log(len(es))) * (1.0 if own else 0.4)
        out.append(dict(own=own, step=st, kind=kind, trans=trans, n=len(es), worst=w["v"], score=score, at=w))
    out.sort(key=lambda d: -d["score"])
    return out


def cut_frames(run, groups, bursts, steps, top, sheet="sheet.png", tag=""):
    os.makedirs(os.path.join(run, "audit"), exist_ok=True)
    made = []
    for k, g in enumerate(groups[:top]):
        st = g["step"]; e = g["at"]
        vid = os.path.join(run, f"b_{st}.mp4")
        if st not in bursts or not os.path.exists(vid): continue
        off = e["t"] - bursts[st]
        files = []
        for d in (-2, 0, 2):
            out = os.path.join(run, "audit", f"{tag}{k:02d}_{st}_{g['kind']}_{d + 2}.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, off + d / 30.0):.3f}", "-i", vid,
                            "-frames:v", "1", "-vf", ZOOM, out])
            if os.path.exists(out): files.append(out)
        g["frames"] = files; made.append(g)
    rows = [g for g in made if len(g.get("frames", [])) == 3]
    if not rows: return made
    # The contact sheet with ffmpeg (no PIL needed): a row per defect, before / event / after,
    # labelled; each row a 1920x384 strip, then all stacked.
    font = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",) if os.path.exists(f)), None)
    strips = []
    for i, g in enumerate(rows):
        label = f"#{i} {g['step']} {g['kind']} {g['worst']:.1f} (x{g['n']}) {g['trans']}  [-2f | event | +2f]"
        label = label.replace(":", " ").replace("'", "").replace("%", "pct").replace(",", " ")
        out = os.path.join(run, "audit", f"row_{i:02d}.png")
        draw = f",drawtext=fontfile={font}:text='{label}':x=8:y=6:fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.6" if font else ""
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for f in g["frames"]: cmd += ["-i", f]
        cmd += ["-filter_complex", "[0][1][2]hstack=3,scale=1920:-2,pad=1920:384:0:24:black" + draw, "-frames:v", "1", out]
        subprocess.run(cmd)
        if os.path.exists(out): strips.append(out)
    if strips:
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for f in strips: cmd += ["-i", f]
        cmd += ["-filter_complex", "".join(f"[{k}]" for k in range(len(strips))) + f"vstack={len(strips)}" if len(strips) > 1 else "null",
                "-frames:v", "1", os.path.join(run, "audit", sheet)]
        subprocess.run(cmd)
        for f in strips: os.unlink(f)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--npc", action="store_true")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--json")
    ap.add_argument("--wide", action="store_true", help="whole frames instead of the 2x middle")
    a = ap.parse_args()
    series = parse_log(os.path.join(a.run, "gta2dx9.log"), a.npc)
    steps, bursts = parse_marks(os.path.join(a.run, "marks.txt"))
    if not series:
        print("no figj: lines (run with GTA2DX9_LOG_JOINTS=1)"); return 2
    events, per_step, per_clip = analyse(series, steps)
    warps = [e for e in events if e["kind"] == "warp"]
    events = [e for e in events if e["kind"] != "warp"]
    groups = group(events)
    print(f"figures: {len(series)}  frames (player): {sum(len(v) for v in series.values() if v and v[0]['own'])}  steps: {len(steps)}  events: {len(events)}")
    print("\nper step (player): frames, skate p95/max cm/frame, pop p99/max cm, root max cm/frame, spin max deg/s")
    order = [s[0] for s in steps] + ["-"]
    for st in order:
        ps = per_step.get(st)
        if not ps or not ps["skate"]: continue
        def pct(v, q): v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0
        print(f"  {st:12s} {len(ps['skate']):5d}  skate {pct(ps['skate'], .95):5.1f}/{max(ps['skate']):5.1f}  pop {pct(ps['pop'], .99):5.1f}/{max(ps['pop'] or [0]):5.1f}"
              f"  root {max(ps['root']):5.1f}  spin {max(ps['spin']):6.0f}")
    print(f"\nwarps and hitches (the game moved him over 0.2 block in a frame, or the figure over 1.5: a dev warp, a respawn, a hitch;"
          f" the figure snaps or is pulled along by design, not ranked): {len(warps)}")
    print("\nper clip (player): frames, skate mean/p95 cm/frame, pop p95/max cm")
    for (own, clip), pc in sorted(per_clip.items(), key=lambda kv: -len(kv[1]["skate"])):
        if not own or len(pc["skate"]) < 8: continue
        sk = sorted(pc["skate"]); po = sorted(pc["pop"] or [0.0])
        print(f"  {clip:34s} {len(sk):5d}  skate {sum(sk)/len(sk):5.1f}/{sk[int(.95*len(sk))]:5.1f}  pop {po[int(.95*len(po))]:5.1f}/{po[-1]:5.1f}")
    print("\ntransitions (player): each change of the leading clip; spike = largest one-frame joint jump within"
          " 3 frames over the median move around it, cm (a clean crossfade < 8)")
    rowsT = sorted(((k[1], v) for k, v in trans_table.items() if k[0]), key=lambda kv: -max(x[0] for x in kv[1]))
    for name, v in rowsT:
        sp = sorted(x[0] for x in v); w = max(v)
        print(f"  {name:44s} n={len(v):3d}  spike mean {sum(sp)/len(sp):5.1f}  max {sp[-1]:5.1f}  (f={w[1]} {w[2]} {w[3]})")
    print("\nranked defects (score = weight x worst/threshold x (1+ln n)):")
    for i, g in enumerate(groups[:a.top * 2]):
        e = g["at"]
        print(f"  {i:2d} {g['score']:6.1f} {'P' if g['own'] else 'N'} {g['step']:12s} {g['kind']:8s} worst {g['worst']:6.1f} x{g['n']:<4d} f={e['f']} st={e['st']} act={e['act']}"
              f"{' joint=' + e['joint'] if 'joint' in e else ''}  {g['trans']}")
    global ZOOM
    if a.wide: ZOOM = "scale=640:360"
    if a.frames:
        cut_frames(a.run, groups, bursts, steps, a.top)
        # the worst instance of each of the worst locomotion transitions (no overlay), as groups
        tg = []
        for name, v in rowsT:
            if "+" in name: continue
            w = max(v)
            if w[0] < 8.0 or w[3] == "-": continue
            tg.append(dict(step=w[3], kind="transition", trans=name, n=len(v), worst=w[0], at=dict(t=w[4], f=w[1])))
        cut_frames(a.run, tg, bursts, steps, 8, sheet="sheet_transitions.png", tag="t")
    if a.json:
        json.dump(dict(groups=[{k: v for k, v in g.items() if k != "at"} | {"f": g["at"]["f"], "t": g["at"]["t"]} for g in groups],
                       steps=steps), open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
