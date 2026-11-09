#!/usr/bin/env python3
"""Visual regression differ (QA-REGRESSION; docs/visual-regression.md).

    vreg_diff.py seed  <golden set dir> <run dir> [<run dir> ...] [--rev REV] [--note TEXT]
    vreg_diff.py check <golden set dir> <run dir> [--out DIR] [--label TEXT]

A golden set is two or more capture runs of the same build (tools/vreg/run_capture.sh): every
sample of a shot is kept, because the street is alive (people and cars go where they like) and
one frame cannot say what "the same" looks like.

The comparison works on tiles: each frame is reduced to 320x180 (box filter: sub-pixel camera
jitter and texture shimmer average out) and cut into a 16x9 grid of 20x20 tiles. Per tile two
distances: `pix`, the mean absolute difference of the pixels (a model, texture or shadow that
changed), and `mean`, the largest difference of the tile's mean colour per channel (a tint,
lighting or fog change too smooth for `pix` to stand out). A run's tile distance is the
smallest distance to any golden sample (a car that was in one sample is matched by another).

Tolerance per tile, learned from the samples (leave-one-out): each sample is compared with the
others the same way, and the largest such distance is that tile's noise. A tile has CHANGED when
its distance passes max(floor, NOISE_K * noise + margin); floors and margins below. A shot:
  FAIL  if more than FAIL_FRAC of its tiles changed, or a global check trips (frame missing,
        black, magenta (undrawn) pixels appear, colour drained to grey, brightness shifted);
  WARN  if more than WARN_FRAC changed;
  SKIP  if the run's warp landed elsewhere than the golden's (not a rendering question);
  PASS  otherwise.
check writes <out>/report.json, report.md and, for every WARN/FAIL shot, a sheet
(golden | run | changed tiles in red) <out>/sheet_<shot>.png. Exit status 1 if any shot FAILs.
"""
import argparse, glob, hashlib, json, os, re, shutil, sys, time
import numpy as np
from PIL import Image, ImageDraw

W, H, TX, TY = 320, 180, 16, 9                    # reduced frame and tile grid (20x20 tiles)
FLOOR = {"pix": 0.045, "mean": 0.035, "detail": 0.30}   # never flag below these (0..1 units; detail: relative)
MARGIN = {"pix": 0.015, "mean": 0.012, "detail": 0.08}
NOISE_K = 1.25
WARN_FRAC, FAIL_FRAC = 0.05, 0.12                # of the 144 tiles: 8 / 18 tiles


_cache = {}


def load(path):
    """the frame reduced to 320x180, and its fine detail per tile (mean |Laplacian| of the 640x360
    grey image, 16x9 tiles): texture sharpness and grain, which the reduction averages away"""
    if path in _cache: return _cache[path]
    im = Image.open(path).convert("RGB")
    a = np.asarray(im.resize((W, H), Image.BOX), dtype=np.float32) / 255.0
    g = np.asarray(im.convert("L").resize((2 * W, 2 * H), Image.BOX), dtype=np.float32) / 255.0
    lap = np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    lap = np.pad(lap, 1)
    det = lap.reshape(TY, 2 * H // TY, TX, 2 * W // TX).mean(axis=(1, 3))
    _cache[path] = r = Frame(a, det)
    return r


class Frame:
    def __init__(self, a, det): self.a, self.det = a, det


def tiles(a):
    return a.reshape(TY, H // TY, TX, W // TX, 3).transpose(0, 2, 1, 3, 4)   # ty, tx, 20, 20, 3


def dist(fa, fb):
    ta, tb = tiles(fa.a), tiles(fb.a)
    pix = np.abs(ta - tb).mean(axis=(2, 3, 4))
    mean = np.abs(ta.mean(axis=(2, 3)) - tb.mean(axis=(2, 3))).max(axis=2)
    # relative change of the fine detail; flat tiles (sky, shade) do not count
    detail = np.abs(fa.det - fb.det) / (np.maximum(fa.det, fb.det) + 0.02)
    return {"pix": pix, "mean": mean, "detail": detail}


def stats(f):
    a = f.a
    lum = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    chroma = a.max(axis=2) - a.min(axis=2)
    magenta = (a[..., 0] > 0.85) & (a[..., 2] > 0.85) & (a[..., 1] < 0.2)
    return dict(lum=float(lum.mean()), chroma=float(chroma.mean()), magenta=float(magenta.mean()))


def shots_of(run):
    return {os.path.basename(p)[3:-4]: p for p in sorted(glob.glob(os.path.join(run, "vr_*.png")))}


def records(run):
    out = {}
    p = os.path.join(run, "vreg.jsonl")
    if os.path.exists(p):
        for line in open(p):
            try:
                r = json.loads(line); out[r["shot"]] = r
            except ValueError:
                pass
    return out


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


# ---------------------------------------------------------------- seed
def seed(args):
    runs = args.runs
    if len(runs) < 2:
        print("seed: at least two runs of the same build are needed to learn the noise (three is better)")
    # every shot that at least two runs have (one run is enough with a single run); each shot keeps
    # the samples of the runs that took it, so shots added to the list later can join a golden set
    have = {r: set(shots_of(r)) for r in runs}
    shots = {s for r in runs for s in have[r] if sum(s in have[q] for q in runs) >= min(2, len(runs))}
    if args.shots:   # only the shots the current list takes (a pose renamed or dropped leaves old frames behind)
        lst = json.load(open(args.shots))
        names = ({"spawn_classic", "spawn_third", "spawn_first"} | {f"spawn_{q['name']}" for q in lst.get("spawn_poses", [])}
                 | {f"{p['name']}_{q['name']}" for p in lst["points"] for q in p["poses"]})
        shots &= names
    os.makedirs(args.golden, exist_ok=True)
    manifest = dict(rev=args.rev, note=args.note, made=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                    runs=[os.path.abspath(r) for r in runs], grid=[TX, TY], size=[W, H], shots={})
    noise = {}
    for shot in sorted(shots):
        samples = []
        srcs = [r for r in runs if shot in have[r]]
        for i, r in enumerate(srcs):
            dst = os.path.join(args.golden, f"{shot}.{i}.png")
            shutil.copyfile(os.path.join(r, f"vr_{shot}.png"), dst)
            samples.append(load(dst))
        rec = records(srcs[0]).get(shot, {})
        lands = [records(r).get(shot, {}).get("at") for r in srcs]
        n = {k: np.zeros((TY, TX), np.float32) for k in FLOOR}
        for i in range(len(samples)):
            others = [dist(samples[i], samples[j]) for j in range(len(samples)) if j != i]
            if not others: continue
            for k in n:
                n[k] = np.maximum(n[k], np.min([o[k] for o in others], axis=0))
        noise[shot] = {k: np.round(v, 4).tolist() for k, v in n.items()}
        manifest["shots"][shot] = dict(samples=len(samples), sha=[sha(os.path.join(args.golden, f"{shot}.{i}.png")) for i in range(len(samples))],
                                       at=lands, landed=rec.get("landed"), view=rec.get("view"),
                                       stats=stats(samples[0]),
                                       noise_tiles_over_floor=int(sum((n[k] * NOISE_K + MARGIN[k] > FLOOR[k]).sum() for k in n)))
    json.dump(manifest, open(os.path.join(args.golden, "manifest.json"), "w"), indent=1)
    json.dump(noise, open(os.path.join(args.golden, "noise.json"), "w"))
    print(f"seeded {len(shots)} shots ({sum(manifest['shots'][s]['samples'] for s in shots)} samples from {len(runs)} runs) into {args.golden}")
    # self-check: every sample against the others must pass
    bad = 0
    if len(runs) < 2: return
    for shot in sorted(shots):
        for i, r in enumerate([q for q in runs if shot in have[q]]):
            res = judge_shot(args.golden, manifest, noise, shot, os.path.join(r, f"vr_{shot}.png"), None, exclude=i)
            if res["verdict"] in ("FAIL", "WARN"):
                bad += 1; print(f"  self-check: sample {i} {shot}: {res['verdict']} {res['why']}")
    print(f"self-check (leave-one-out): {bad} WARN/FAIL of {sum(manifest['shots'][s]['samples'] for s in shots)}")


# ---------------------------------------------------------------- check
def judge_shot(gdir, manifest, noise, shot, run_png, run_rec, exclude=None):
    m = manifest["shots"][shot]
    res = dict(shot=shot, verdict="PASS", why="", changed=0, frac=0.0)
    if not run_png or not os.path.exists(run_png):
        res.update(verdict="FAIL", why="frame missing (the capture did not reach this shot)"); return res
    if run_rec and m.get("at") and m["at"][0] and run_rec.get("at"):
        g, r = m["at"][0], run_rec["at"]
        if abs(g[0] - r[0]) + abs(g[1] - r[1]) > 1.5 or abs(g[2] - r[2]) > 0.6:
            res.update(verdict="SKIP", why=f"player at {r} not {g}: the warp landed elsewhere"); return res
    run = load(run_png)
    idx = [i for i in range(m["samples"]) if i != exclude]
    if not idx:
        res.update(verdict="SKIP", why="no golden sample to compare with"); return res
    golds = [load(os.path.join(gdir, f"{shot}.{i}.png")) for i in idx]
    ds = [dist(run, g) for g in golds]
    d = {k: np.min([x[k] for x in ds], axis=0) for k in FLOOR}
    nz = noise.get(shot, {})
    changed = np.zeros((TY, TX), bool)
    for k in FLOOR:
        n = np.array(nz.get(k, np.zeros((TY, TX))), np.float32)
        thr = np.maximum(FLOOR[k], NOISE_K * n + MARGIN[k])
        changed |= d[k] > thr
    res["changed"] = int(changed.sum()); res["frac"] = round(float(changed.mean()), 3)
    res["tiles"] = changed.astype(int).tolist()
    sr = stats(run); sg = [stats(g) for g in golds]
    res["stats"] = dict(run=sr, golden=sg[0])
    why = []
    if sr["lum"] < 0.03 and min(s["lum"] for s in sg) > 0.08: why.append("black frame")
    if sr["magenta"] > 0.005 and max(s["magenta"] for s in sg) < 0.001: why.append(f"magenta (undrawn) {sr['magenta']:.1%}")
    gch = min(s["chroma"] for s in sg)
    if gch > 0.05 and sr["chroma"] < 0.5 * gch: why.append(f"colour drained (chroma {sr['chroma']:.3f} vs {gch:.3f})")
    lo, hi = min(s["lum"] for s in sg), max(s["lum"] for s in sg)
    if sr["lum"] < lo - 0.08 or sr["lum"] > hi + 0.08: why.append(f"brightness {sr['lum']:.2f} vs {lo:.2f}-{hi:.2f}")
    if why or res["frac"] > FAIL_FRAC:
        res["verdict"] = "FAIL"
    elif res["frac"] > WARN_FRAC:
        res["verdict"] = "WARN"
    res["why"] = "; ".join(why + ([f"{res['changed']} of {TX * TY} tiles changed"] if res["changed"] else []))
    res["_nearest"] = idx[int(np.argmin([x["pix"].mean() for x in ds]))]
    return res


def sheet(path, gpng, rpng, tiles_):
    g = Image.open(gpng).convert("RGB").resize((640, 360)); r = Image.open(rpng).convert("RGB").resize((640, 360))
    h = r.copy(); dr = ImageDraw.Draw(h, "RGBA"); tw, th = 640 / TX, 360 / TY
    for y in range(TY):
        for x in range(TX):
            if tiles_[y][x]: dr.rectangle([x * tw, y * th, (x + 1) * tw - 1, (y + 1) * th - 1], fill=(255, 0, 0, 90), outline=(255, 0, 0, 255))
    out = Image.new("RGB", (1920, 380), (20, 20, 20)); d = ImageDraw.Draw(out)
    for i, (im, label) in enumerate(((g, "golden (nearest sample)"), (r, "this run"), (h, "changed tiles"))):
        out.paste(im, (i * 640, 20)); d.text((i * 640 + 6, 4), label, fill=(255, 255, 255))
    out.save(path)


def check(args):
    gdir = args.golden
    manifest = json.load(open(os.path.join(gdir, "manifest.json")))
    noise = json.load(open(os.path.join(gdir, "noise.json")))
    out = args.out or os.path.join(args.run, "vreg_report")
    os.makedirs(out, exist_ok=True)
    have, recs = shots_of(args.run), records(args.run)
    results = []
    for shot in sorted(manifest["shots"]):
        res = judge_shot(gdir, manifest, noise, shot, have.get(shot), recs.get(shot))
        if res["verdict"] in ("WARN", "FAIL") and shot in have:
            sp = os.path.join(out, f"sheet_{shot}.png")
            sheet(sp, os.path.join(gdir, f"{shot}.{res.get('_nearest', 0)}.png"), have[shot], res.get("tiles", [[0] * TX] * TY))
            res["sheet"] = sp
        res.pop("_nearest", None)
        results.append(res)
    # the renderer log's health, as stage_smoke.sh judges it: faults and model/texture read errors fail the run
    log = os.path.join(args.run, "gta2dx9.log"); health = {}
    if os.path.exists(log):
        txt = open(log, encoding="latin-1").read()
        health = dict(faults=txt.count("FAULT"),
                      read_errors=len(re.findall(r"models: .*could not be read|cars.by_model .*not loaded|models: no .*manifest", txt)),
                      models_loaded=bool(re.search(r"models: .* nodes", txt)),
                      camera_fixed=txt.count("regress: camera fixed"))
        why = [k for k, bad in (("FAULT lines", health["faults"]), ("model/texture read errors", health["read_errors"]),
                                ("no model loaded", not health["models_loaded"])) if bad]
        if why:
            results.append(dict(shot="(renderer log)", verdict="FAIL", why=", ".join(why) + f": {health}", changed=0, frac=0.0))
    count = {v: sum(r["verdict"] == v for r in results) for v in ("PASS", "WARN", "FAIL", "SKIP")}
    rep = dict(golden=os.path.abspath(gdir), golden_rev=manifest.get("rev"), run=os.path.abspath(args.run), label=args.label,
               counts=count, health=health, extra_shots=sorted(set(have) - set(manifest["shots"])), results=results,
               thresholds=dict(floor=FLOOR, margin=MARGIN, noise_k=NOISE_K, warn_frac=WARN_FRAC, fail_frac=FAIL_FRAC))
    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1)
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write(f"# vreg {args.label or ''}: {args.run} against {gdir} (golden rev {manifest.get('rev')})\n\n")
        f.write(" ".join(f"{k} {v}" for k, v in count.items()) + f"; renderer log {health}\n\n| shot | verdict | changed tiles | why |\n|---|---|---|---|\n")
        for r in results:
            f.write(f"| {r['shot']} | {r['verdict']} | {r['changed']} ({r['frac']:.0%}) | {r['why']} |\n")
    print(f"vreg {args.label or ''}: " + " ".join(f"{k}={v}" for k, v in count.items()) + f"  (report {out}/report.md)")
    for r in results:
        if r["verdict"] != "PASS": print(f"  {r['verdict']:4} {r['shot']}: {r['why']}")
    return 1 if count["FAIL"] else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("golden"); s.add_argument("runs", nargs="+")
    s.add_argument("--rev", default="?"); s.add_argument("--note", default="")
    s.add_argument("--shots", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots.json"),
                   help="the shot list whose shots are seeded (default tools/vreg/shots.json; '' for every shot)")
    c = sub.add_parser("check"); c.add_argument("golden"); c.add_argument("run")
    c.add_argument("--out"); c.add_argument("--label", default="")
    a = ap.parse_args()
    if a.cmd == "seed": seed(a); return 0
    return check(a)


if __name__ == "__main__":
    sys.exit(main())
