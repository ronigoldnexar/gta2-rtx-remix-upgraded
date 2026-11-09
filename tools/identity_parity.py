#!/usr/bin/env python3
"""IDENTITY-SYSTEM cross-mode parity check (docs/identity-system.md section 2.5).

    python3 tools/identity_parity.py out/<run1> [out/<run2> ...] [--report report.md] [--sheet sheet.png]
            [--de 30] [--iou 0.35]

Each run is a session of linux/docker/keys_identity_parity.sh with GTA2DX9_IDENTITY_PROBE=1:
idp_*.png shots, idp_shots.txt (shot -> wall time) and the renderer's log, whose lines

    identity: player key 0 remap 25 -> <model> ... fp <hex>
    identity: vehicle model M sprite S paint r,g,b -> <model> ... fp <hex>
    identity probe: <what> view <0 classic|1 third|2 first> frame F t <unix s.ms> obj <hex> rect x0 y0 x1 y1 fp <hex> ...

say what each entity's identity record is and where the entity is on screen in each view.

Checks (each failure is a FAIL line; the exit status is the number of failures, capped at 100):
  1 record   the player has one record per session (no CHANGED line) and every probe line of him, in
             every view, carries that fingerprint; the same for the car he drives.
  2 sessions with several runs: the player's fingerprint is the same in every session, and a vehicle
             record with the same inputs (model, sprite, paint) has the same fingerprint everywhere.
  3 colour   the player's (and his car's) dominant colour in the classic frame against the third- and
             first-person frames, and every car's classic sprite against its 3D model at the classic
             camera (the frame 1 s after V with a 12 s camera move): CIE76 delta-E <= --de.
  4 shape    every car: the 3D model's drawn pixels against its sprite's at the classic camera,
             IoU >= --iou (the silhouette the game drew is where and how big the model stands).
Needs numpy and Pillow.
"""
import argparse, glob, json, math, os, re, sys

import numpy as np
from PIL import Image, ImageDraw

PROBE = re.compile(r"identity probe: (\w+) view (\d) frame (\d+) t (\d+)\.(\d+) obj ([0-9a-f]+) rect (-?\d+) (-?\d+) (-?\d+) (-?\d+) "
                   r"fp ([0-9a-f]+) model (\S+) shown ([\d.]+),([\d.]+),([\d.]+) ([\d.]+),([\d.]+),([\d.]+)")
PLAYER = re.compile(r"identity: player( CHANGED)? key (-?\d+) remap (-?\d+) body (-?\d+) -> (\S+).* top ([\d.]+),([\d.]+),([\d.]+) "
                    r"bottom ([\d.]+),([\d.]+),([\d.]+) fp ([0-9a-f]+)")
VEHICLE = re.compile(r"identity: vehicle( CHANGED)? model (-?\d+) sprite (-?\d+) paint (\d+),(\d+),(\d+) -> (.+?) tint .* fp ([0-9a-f]+)")
SLEEVE = re.compile(r"identity: first-person sleeves .* -> the player's shirt ([\d.]+),([\d.]+),([\d.]+) \(fp ([0-9a-f]+)\)")
SHOT = re.compile(r"idp shot (\S+) t=([\d.]+)")
VIEW_OF = {"0classic": 0, "0classic_b": 0, "1at_classic_cam": 1, "2third": 1, "3first": 2, "4classic": 0}


def lab(rgb):
    """sRGB 0..255 -> CIE Lab (D65)."""
    c = np.asarray(rgb, dtype=float) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = m @ c / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def delta_e(a, b):
    return float(np.linalg.norm(lab(a) - lab(b)))


def subject(img, rect, pad=0.35):
    """The entity's pixels inside `rect`: those unlike the ring of background round it. Returns
    (dominant colour, mask, clipped rect) or None. Dominant: the median of the largest of the
    pixels' luminance thirds (so a shirt wins over a face, a body over its glass)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(w, int(math.ceil(x1))), min(h, int(math.ceil(y1)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    pw, ph = int((x1 - x0) * pad) + 3, int((y1 - y0) * pad) + 3
    X0, Y0, X1, Y1 = max(0, x0 - pw), max(0, y0 - ph), min(w, x1 + pw), min(h, y1 + ph)
    outer = img[Y0:Y1, X0:X1].reshape(-1, 3).astype(float)
    ring_mask = np.ones((Y1 - Y0, X1 - X0), bool)
    ring_mask[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = False
    ring = img[Y0:Y1, X0:X1][ring_mask].astype(float)
    if len(ring) < 8:
        return None
    bg = np.median(ring, axis=0)
    inner = img[y0:y1, x0:x1].astype(float)
    dist = np.linalg.norm(inner - bg, axis=2)
    mask = dist > 28
    px = inner[mask]
    if len(px) < 12:
        return None
    lum = px @ np.array([0.299, 0.587, 0.114])
    q = np.quantile(lum, [1 / 3, 2 / 3])
    parts = [px[lum <= q[0]], px[(lum > q[0]) & (lum <= q[1])], px[lum > q[1]]]
    # the third whose colours agree best (smallest spread) among the larger ones: the cloth / paint
    best = min((p for p in parts if len(p) >= len(px) // 4), key=lambda p: float(np.mean(np.std(p, axis=0))), default=px)
    return np.median(best, axis=0), mask, (x0, y0, x1, y1)


def mask_iou(shape, s0, s1):
    """IoU of the two subjects' drawn pixels (subject() masks) in frame coordinates: the sprite's
    opaque pixels against the model's, not their rectangles (a sprite quad is mostly transparent)."""
    h, w = shape[:2]
    m = [np.zeros((h, w), bool), np.zeros((h, w), bool)]
    for k, s in enumerate((s0, s1)):
        x0, y0, x1, y1 = s[2]
        m[k][y0:y1, x0:x1] = s[1]
    inter = np.logical_and(m[0], m[1]).sum(); union = np.logical_or(m[0], m[1]).sum()
    return float(inter) / float(union) if union else 0.0


def rect_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def load_run(run):
    logp = os.path.join(run, "gta2dx9.log")
    text = open(logp, errors="replace").read() if os.path.exists(logp) else ""
    probes = []
    for m in PROBE.finditer(text):
        g = m.groups()
        probes.append(dict(what=g[0], view=int(g[1]), frame=int(g[2]), t=int(g[3]) + int(g[4]) / 1000.0, obj=g[5],
                           rect=tuple(float(v) for v in g[6:10]), fp=g[10], model=g[11],
                           top=tuple(float(v) for v in g[12:15]), bottom=tuple(float(v) for v in g[15:18])))
    players = [dict(changed=bool(m.group(1)), model=m.group(5), remap=int(m.group(3)), top=tuple(float(v) for v in m.group(6, 7, 8)),
                    bottom=tuple(float(v) for v in m.group(9, 10, 11)), fp=m.group(12)) for m in PLAYER.finditer(text)]
    vehicles = [dict(changed=bool(m.group(1)), model=int(m.group(2)), sprite=int(m.group(3)), paint=tuple(int(v) for v in m.group(4, 5, 6)),
                     name=m.group(7).strip(), fp=m.group(8)) for m in VEHICLE.finditer(text)]
    sleeves = [dict(shirt=tuple(float(v) for v in m.group(1, 2, 3)), fp=m.group(4)) for m in SLEEVE.finditer(text)]
    shots = {}
    sp = os.path.join(run, "idp_shots.txt")
    if os.path.exists(sp):
        for m in SHOT.finditer(open(sp).read()):
            shots[m.group(1)] = float(m.group(2))
    m = RENDER.search(text)
    render = (int(m.group(1)), int(m.group(2))) if m else (1280, 720)
    return dict(run=run, probes=probes, players=players, vehicles=vehicles, sleeves=sleeves, shots=shots, render=render)


def probes_at(R, t, view, window=1.2):
    """The probe lines of `view` nearest the wall time t (one per object: the nearest line)."""
    best = {}
    for p in R["probes"]:
        if p["view"] != view or abs(p["t"] - t) > window:
            continue
        k = (p["what"], p["obj"])
        if k not in best or abs(p["t"] - t) < abs(best[k]["t"] - t):
            best[k] = p
    return best


RENDER = re.compile(r"render size (\d+)x(\d+)")


def to_shot(p, R, img):
    """A probe rectangle in the shot's pixels. Classic (view 0) rectangles are the game's own
    screen coordinates (640x480), which the renderer stretches to its render size; the 3D ones are
    the device viewport (the render size). Then to the shot's size."""
    rw, rh = R.get("render", (img.shape[1], img.shape[0]))
    x0, y0, x1, y1 = p["rect"]
    if p["view"] == 0:
        x0, x1 = x0 * rw / 640.0, x1 * rw / 640.0
        y0, y1 = y0 * rh / 480.0, y1 * rh / 480.0
    kx, ky = img.shape[1] / rw, img.shape[0] / rh
    return (x0 * kx, y0 * ky, x1 * kx, y1 * ky)


def on_screen(rect, img, need=0.6):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    ix = max(0.0, min(w, x1) - max(0, x0)); iy = max(0.0, min(h, y1) - max(0, y0))
    return ix * iy / area >= need and (x1 - x0) >= 6 and (y1 - y0) >= 6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--report", default=None)
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--de", type=float, default=30.0)
    ap.add_argument("--iou", type=float, default=0.4)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    fails, lines, result = [], [], {"runs": []}

    def fail(msg):
        fails.append(msg); lines.append("FAIL " + msg)

    def ok(msg):
        lines.append("ok   " + msg)

    runs = [load_run(r) for r in a.runs]
    sheet_rows = []
    for R in runs:
        name = os.path.basename(R["run"].rstrip("/"))
        lines.append(f"\n## {name}")
        rr = {"run": name}
        # ---- 1 record ------------------------------------------------------------------
        if not R["players"]:
            fail(f"{name}: no 'identity: player' record in the log (a DLL without IDENTITY-SYSTEM, or the level never loaded)")
            result["runs"].append(rr); continue
        pfps = sorted({p["fp"] for p in R["players"]})
        P = R["players"][0]
        rr["player"] = P
        if len(pfps) != 1 or any(p["changed"] for p in R["players"]):
            fail(f"{name}: the player's record changed within the session: {pfps}")
        else:
            ok(f"{name}: player record {P['fp']} ({P['model']}, remap {P['remap']}, top {P['top']}, bottom {P['bottom']})")
        bad = sorted({(p["view"], p["fp"]) for p in R["probes"] if p["what"] in ("player", "sleeve") and p["fp"] != P["fp"]})
        if bad:
            fail(f"{name}: probe lines of the player with another fingerprint (view, fp): {bad[:6]}")
        else:
            views = sorted({p["view"] for p in R["probes"] if p["what"] in ("player", "sleeve")})
            ok(f"{name}: player probed in views {views}, one fingerprint")
        for s in R["sleeves"]:
            if s["fp"] != P["fp"]:
                fail(f"{name}: first-person sleeves tinted from record {s['fp']}, the player's is {P['fp']}")
            else:
                ok(f"{name}: first-person sleeves take the player's shirt {s['shirt']}")
        mycar = {}
        for p in R["probes"]:
            if p["what"] == "mycar" and p["fp"] != "00000000":
                mycar.setdefault(p["obj"], set()).add((p["view"], p["fp"]))
        for obj, s in mycar.items():
            fps = {fp for _, fp in s}
            (fail if len(fps) > 1 else ok)(f"{name}: his car {obj}: views {sorted({v for v, _ in s})}, fingerprints {sorted(fps)}")
        # ---- 3/4 frames ------------------------------------------------------------------
        imgs = {}
        for shot, t in R["shots"].items():
            path = os.path.join(R["run"], f"idp_{shot}.png")
            if os.path.exists(path):
                imgs[shot] = (np.asarray(Image.open(path).convert("RGB")), t)
        for phase in ("foot", "car"):
            subj = "player" if phase == "foot" else "mycar"
            c = imgs.get(f"{phase}_0classic_b") or imgs.get(f"{phase}_0classic")
            if not c:
                lines.append(f"     {name} {phase}: no classic shot"); continue
            cprobes = probes_at(R, c[1], 0)
            row = {"phase": phase, "panels": []}
            ref = None
            for k, p in cprobes.items():
                if k[0] == subj:
                    r0 = to_shot(p, R, c[0])
                    s = subject(c[0], r0) if on_screen(r0, c[0]) else None
                    if s is not None:
                        ref = s[0]; row["panels"].append(("classic", c[0], r0, ref))
            if ref is None:
                fail(f"{name} {phase}: the {subj} was not found in the classic frame (no probe rectangle near the shot, or nothing drawn there)")
            for shot, label in ((f"{phase}_2third", "third"), (f"{phase}_3first", "first")):
                if shot not in imgs:
                    continue
                im, t = imgs[shot]
                view = 1 if label == "third" else 2
                ps = probes_at(R, t, view)
                cand = [p for k, p in ps.items() if (k[0] == subj or (label == "first" and phase == "foot" and k[0] == "sleeve"))
                        and on_screen(to_shot(p, R, im), im)]
                if not cand:
                    lines.append(f"     {name} {phase} {label}: no probe rectangle of the {subj} (not drawn in this view: "
                                 f"{'his body is hidden in first person on foot unless he holds a weapon' if label == 'first' else 'behind the camera?'})")
                    continue
                p = cand[0]
                r1 = to_shot(p, R, im)
                s = subject(im, r1)
                if s is None or ref is None:
                    lines.append(f"     {name} {phase} {label}: rectangle {p['rect']} has no subject pixels"); continue
                de = delta_e(ref, s[0])
                row["panels"].append((label, im, r1, s[0]))
                msg = (f"{name} {phase}: {subj} classic {tuple(int(v) for v in ref)} vs {label} {tuple(int(v) for v in s[0])} "
                       f"(probe {p['what']}): delta-E {de:.1f} (limit {a.de:.0f})")
                (fail if de > a.de else ok)(msg)
            # every car: classic sprite against its model at the classic camera
            at = None
            for cand in (f"{phase}_1at_classic_cam", f"{phase}_1at_classic_cam_b"):
                f = imgs.get(cand)
                # the switch may not have reached the screen yet on a loaded host: still the classic frame
                if f is not None and float(np.mean(np.abs(f[0].astype(float) - c[0].astype(float)))) >= 3.0:
                    at = f; break
            if at is None:
                lines.append(f"     {name} {phase}: no frame after V differs from the classic one; classic-camera comparison skipped")
            if at:
                aprobes = probes_at(R, at[1], 1)
                n = nbad = 0
                for k, p in cprobes.items():
                    if k[0] not in ("car", "mycar", "player"):
                        continue
                    q = aprobes.get(k) or aprobes.get(("mycar" if k[0] == "car" else "car", k[1]))
                    if not q:
                        continue
                    r0, r1 = to_shot(p, R, c[0]), to_shot(q, R, at[0])
                    if not (on_screen(r0, c[0]) and on_screen(r1, at[0])):
                        continue
                    s0, s1 = subject(c[0], r0), subject(at[0], r1)
                    iou = mask_iou(c[0].shape, s0, s1) if (s0 is not None and s1 is not None) else rect_iou(r0, r1)
                    if s0 is None or s1 is None:
                        continue
                    n += 1
                    de = delta_e(s0[0], s1[0])
                    bad = de > a.de or (k[0] != "player" and iou < a.iou)   # a figure's sprite quad is mostly transparent
                    nbad += bad
                    msg = (f"{name} {phase}: {'player' if k[0] == 'player' else 'car'} {k[1]} {q['model']} classic {tuple(int(v) for v in s0[0])} vs 3D {tuple(int(v) for v in s1[0])} "
                           f"delta-E {de:.1f}, drawn-pixel IoU {iou:.2f}")
                    (fail if bad else ok)(msg)
                    if len(row["panels"]) < 12:
                        kind = "player" if k[0] == "player" else "car " + k[1][-4:]
                        row["panels"].append((f"{kind} classic", c[0], r0, s0[0]))
                        row["panels"].append((f"{kind} 3D@classic", at[0], r1, s1[0]))
                lines.append(f"     {name} {phase}: {n} cars compared at the classic camera, {nbad} over the limits")
            sheet_rows.append((name, row))
        result["runs"].append(rr)
    # ---- 2 sessions --------------------------------------------------------------------
    if len(runs) > 1:
        lines.append("\n## Across sessions")
        pf = {os.path.basename(R["run"].rstrip("/")): sorted({p["fp"] for p in R["players"]}) for R in runs}
        allfp = {fp for v in pf.values() for fp in v}
        (fail if len(allfp) != 1 else ok)(f"player fingerprint per session: {pf}")
        byinputs = {}
        for R in runs:
            for v in R["vehicles"]:
                byinputs.setdefault((v["model"], v["sprite"], v["paint"]), set()).add(v["fp"])
        split = {k: sorted(v) for k, v in byinputs.items() if len(v) > 1}
        (fail if split else ok)(f"vehicle records: {len(byinputs)} distinct (model, sprite, paint) inputs; "
                                f"{len(split)} with more than one fingerprint {list(split.items())[:4]}")
    text = "# Identity parity\n\n" + "\n".join(lines) + f"\n\n{len(fails)} failure(s)\n"
    print(text)
    if a.report:
        open(a.report, "w").write(text)
    if a.json:
        json.dump({"fails": fails, **result}, open(a.json, "w"), indent=1, default=str)
    if a.sheet and any(row['panels'] for _, row in sheet_rows):
        tiles = []
        for name, row in sheet_rows:
            for label, im, rect, col in row["panels"]:
                x0, y0, x1, y1 = [int(v) for v in rect]
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                half = max(40, int(max(x1 - x0, y1 - y0) * 0.8))
                crop = Image.fromarray(im).crop((cx - half, cy - half, cx + half, cy + half)).resize((200, 200))
                d = ImageDraw.Draw(crop)
                k = 200 / (2 * half)
                d.rectangle([(x0 - cx + half) * k, (y0 - cy + half) * k, (x1 - cx + half) * k, (y1 - cy + half) * k], outline=(255, 0, 255))
                d.rectangle([0, 176, 200, 200], fill=tuple(int(v) for v in col))
                d.text((3, 3), f"{name[:10]} {row['phase']} {label}"[:34], fill=(255, 255, 0))
                tiles.append(crop)
        cols = 6
        sheet = Image.new("RGB", (200 * cols, 200 * ((len(tiles) + cols - 1) // cols)), (20, 20, 20))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * 200, (i // cols) * 200))
        sheet.save(a.sheet)
    sys.exit(min(100, len(fails)))


if __name__ == "__main__":
    main()
