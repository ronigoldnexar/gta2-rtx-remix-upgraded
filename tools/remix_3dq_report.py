#!/usr/bin/env python3
"""REMIX-3D-QUALITY: the first-person own-figure shadow A/B from a run of linux/docker/remix3dq_take.py.

    python3 tools/remix_3d_parity.py <run dir> <run seconds>      # the continuity report and its frames
    python3 tools/remix_3dq_report.py <run dir> <run seconds> [out dir]

Cuts this take's own marks (_sh_, _tg_, _dg_, _clk_) into <out dir>/frames with remix_3d_parity's
video_start/cut, then writes the sheets below, plus tagged_<moment>.png (third person: figure drawn
plainly | with the player-model copies), diag_<moment>.png (the hash diagnostic steps in order) and
clock_<moment>.png (two classic frames a minute apart).

Per moment with shadow marks (<moment>_sh_on_K / _sh_off_K / _sh_third_K, K = 0..3 headings) it writes
<out dir>/shadow_<moment>.png: third person | first person, own shadow on | the same, off |
|on - off| x4, one row per heading; and shadow_report.json / .md with, per heading, the share of
pixels that differ by more than 12 (of 255) between on and off, and the mean luma change there
(negative: darker, a shadow). The HUD corners are masked. What "on" must show: a darker patch on
the ground where the body stands between the sun and the street, and nothing of the body itself.
"""
import json, os, re, sys
import numpy as np
from PIL import Image, ImageDraw

W, H = 640, 360


def load(path):
    return np.asarray(Image.open(path).convert("RGB").resize((W, H), Image.BILINEAR)).astype(np.float32)


def mask():
    m = np.ones((H, W), bool)
    m[: H // 3, : W // 4] = False
    m[: H // 5, W * 3 // 4:] = False
    m[H * 2 // 3:, : W // 4] = False
    return m


def strip(paths, path, labels):
    """the frames side by side, two per row, each labelled"""
    if not paths: return
    cols = 2 if len(paths) > 1 else 1
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols, (H + 18) * rows), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    for k, (p, lab) in enumerate(zip(paths, labels)):
        x, y = (k % cols) * W, (k // cols) * (H + 18)
        sheet.paste(Image.open(p).convert("RGB").resize((W, H), Image.BILINEAR), (x, y + 18))
        dr.text((x + 6, y + 3), lab, fill=(255, 220, 120))
    sheet.save(path)


def main():
    run, secs = sys.argv[1], float(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(run, "r3d")
    frames = os.path.join(out, "frames")
    os.makedirs(frames, exist_ok=True)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import remix_3d_parity as R
    t0 = R.video_start(run, secs)
    own = [(t, l) for t, l in R.marks(run) if re.search(r"_(sh|tg|dg|clk)_", l)]
    for t, l in own:
        R.cut(os.path.join(run, "game.mp4"), t - t0, os.path.join(frames, f"{l}.png"))
    groups = {}
    for _, l in own:
        m = re.match(r"(.*?)_(tg|dg|clk)_(.*)", l)
        if m: groups.setdefault((m.group(2), m.group(1)), []).append(l)
    for (kind, mo), labels in groups.items():
        name = {"tg": "tagged", "dg": "diag", "clk": "clock"}[kind]
        strip([os.path.join(frames, f"{l}.png") for l in labels], os.path.join(out, f"{name}_{mo}.png"), labels)
    names = sorted(os.listdir(frames))
    moments = sorted({re.sub(r"_sh_(on|off|third)_\d+\.png$", "", n) for n in names if "_sh_" in n})
    rows, report = [], {}
    M = mask()
    for mo in moments:
        per = []
        tiles = []
        for k in range(16):
            p = {t: os.path.join(frames, f"{mo}_sh_{t}_{k}.png") for t in ("third", "on", "off")}
            if not all(os.path.exists(v) for v in p.values()):
                continue
            third, on, off = (load(p[t]) for t in ("third", "on", "off"))
            lon, loff = on.mean(2), off.mean(2)
            d = np.abs(lon - loff)
            changed = (d > 12) & M
            share = float(changed.mean() / M.mean())
            dl = float((lon - loff)[changed].mean()) if changed.any() else 0.0
            per.append(dict(heading=k, changed_share=round(share, 4), mean_luma_change=round(dl, 1),
                            lower_half_share=round(float(changed[H // 2:].mean() / M[H // 2:].mean()), 4)))
            diff = np.clip(np.abs(on - off) * 4, 0, 255)
            tiles.append([third, on, off, diff])
        if not tiles:
            continue
        report[mo] = per
        sheet = Image.new("RGB", (W * 4, (H + 22) * len(tiles) + 24), (20, 20, 20))
        dr = ImageDraw.Draw(sheet)
        dr.text((6, 6), f"{mo}: third person | first person, own shadow ON | OFF | |on-off| x4", fill=(255, 255, 255))
        for r, (row, st) in enumerate(zip(tiles, per)):
            y = 24 + r * (H + 22)
            for c, img in enumerate(row):
                sheet.paste(Image.fromarray(img.astype(np.uint8)), (c * W, y + 18))
            dr.text((6, y + 2), f"heading {st['heading']}: {100 * st['changed_share']:.1f}% of pixels changed, "
                                f"mean luma {st['mean_luma_change']:+.1f} there", fill=(255, 220, 120))
        path = os.path.join(out, f"shadow_{mo}.png")
        sheet.save(path)
        rows.append(path)
    json.dump(report, open(os.path.join(out, "shadow_report.json"), "w"), indent=1)
    with open(os.path.join(out, "shadow_report.md"), "w") as f:
        f.write("| moment | heading | changed % | lower half % | mean luma change |\n|---|---|---|---|---|\n")
        for mo, per in report.items():
            for st in per:
                f.write(f"| {mo} | {st['heading']} | {100 * st['changed_share']:.2f} | "
                        f"{100 * st['lower_half_share']:.2f} | {st['mean_luma_change']:+.1f} |\n")
    print("\n".join(rows))
    print(open(os.path.join(out, "shadow_report.md")).read())


if __name__ == "__main__":
    main()
