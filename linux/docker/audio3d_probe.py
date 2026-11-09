#!/usr/bin/env python3
"""QB-13 positional audio: headless check of a scripted run's sound against the renderer's log.

Inputs in the run folder (gamerun/keys_qb13_audio.sh writes them):
  audio.wav     the PulseAudio null sink's monitor (what the game played), 16-bit stereo
  phases.txt    "HH:MM:SS.nnn <phase>" marks, UTC (rec_start, classic, third, end)
  gta2dx9.log   with [audio] log_every=N: "audio3d: yaw Y game (gx,gy) -> cam right R ahead A from ..." lines

For each 0.5 s window of the street-view phase it measures the stereo balance of the recording,
(R - L) / (R + L) of the RMS levels, and predicts it twice from the logged sounds (nearer sounds
weigh more): once from the camera-frame offset the hook gave the game (`right`) and once from the
game's own top-down offset (`gx`). With the hook working the recording follows the camera frame:
corr(measured, camera) > corr(measured, top-down). It also counts how many positioned sounds the
top-down pan put on the wrong side of the street-view camera.

  python3 audio3d_probe.py <run dir> [--window 0.5]
"""
import argparse
import math
import re
import sys
import wave
from array import array
from datetime import datetime

LINE = re.compile(r"^\[(\d\d:\d\d:\d\d\.\d{3})\] audio3d: yaw (-?[\d.]+) game \((-?[\d.]+),(-?[\d.]+)\) -> cam right (-?[\d.]+) ahead (-?[\d.]+)")


def secs(hms):
    t = datetime.strptime(hms[:15], "%H:%M:%S.%f")
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6


def corr(a, b):
    n = len(a)
    if n < 3:
        return float("nan")
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return float("nan")
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--window", type=float, default=0.5)
    ap.add_argument("--phase", default="third")
    ap.add_argument("--table", action="store_true", help="print every window")
    args = ap.parse_args()

    phases = {}
    for line in open(f"{args.run}/phases.txt"):
        hms, name = line.split()[:2]
        phases[name] = secs(hms)
    rec0 = phases["rec_start"]
    start = phases[args.phase]
    end = phases.get("end", start + 1e9)

    w = wave.open(f"{args.run}/audio.wav")
    rate, ch = w.getframerate(), w.getnchannels()
    pcm = array("h", w.readframes(w.getnframes()))
    if ch != 2:
        sys.exit("need a stereo recording")
    total_s = len(pcm) / 2 / rate
    peak = max(abs(v) for v in pcm) if pcm else 0
    print(f"recording: {total_s:.1f} s at {rate} Hz, peak {peak} ({20 * math.log10(max(peak, 1) / 32768):.1f} dBFS)")

    sounds = []   # (t, yaw, gx, gy, right, ahead)
    for line in open(f"{args.run}/gta2dx9.log", errors="replace"):
        m = LINE.match(line)
        if m:
            sounds.append((secs(m.group(1)),) + tuple(float(m.group(i)) for i in range(2, 7)))
    inphase = [s for s in sounds if start <= s[0] < end]
    print(f"audio3d lines: {len(sounds)} in the log, {len(inphase)} in phase '{args.phase}'")
    if not inphase:
        sys.exit("no positioned sounds logged in the phase: is [audio] log_every set and the street view on?")
    yaws = [s[1] for s in inphase]
    flipped = sum(1 for s in inphase if abs(s[2]) > 0.5 and abs(s[4]) > 0.5 and (s[2] > 0) != (s[4] > 0))
    sided = sum(1 for s in inphase if abs(s[2]) > 0.5 and abs(s[4]) > 0.5)
    print(f"camera yaw over the phase: {min(yaws):.0f}..{max(yaws):.0f} deg")
    print(f"sounds off to one side: {sided}; on the opposite side in the top-down pan: {flipped} "
          f"({100.0 * flipped / max(sided, 1):.0f} %)")

    meas, pcam, pgame, level, yawsw = [], [], [], [], []
    t = start
    while t + args.window <= end:
        a = int((t - rec0) * rate)
        b = int((t + args.window - rec0) * rate)
        if a < 0 or b * 2 > len(pcm):
            t += args.window
            continue
        sl = sl_r = 0.0
        for i in range(a, b):
            sl += pcm[2 * i] ** 2
            sl_r += pcm[2 * i + 1] ** 2
        n = max(b - a, 1)
        rl, rr = math.sqrt(sl / n), math.sqrt(sl_r / n)
        win = [s for s in inphase if t <= s[0] < t + args.window]
        if rl + rr > 100 and win:
            ws = [1.0 / (1.0 + s[4] ** 2 + s[5] ** 2) for s in win]
            tot = sum(ws)
            pcam.append(sum(wi * max(-1, min(1, s[4] / 3)) for wi, s in zip(ws, win)) / tot)
            pgame.append(sum(wi * max(-1, min(1, s[2] / 3)) for wi, s in zip(ws, win)) / tot)
            meas.append((rr - rl) / (rr + rl))
            level.append(rl + rr)
            yawsw.append(sorted(s[1] for s in win)[len(win) // 2])
            if args.table:
                ys = sorted(s[1] for s in win)
                print(f"  t+{t - start:5.1f}s yaw {ys[len(ys) // 2]:5.0f}  L {rl:6.0f} R {rr:6.0f}  measured {meas[-1]:+.2f}"
                      f"  camera-frame {pcam[-1]:+.2f}  top-down {pgame[-1]:+.2f}  ({len(win)} sounds)")
        t += args.window
    c_cam, c_game = corr(meas, pcam), corr(meas, pgame)
    if meas:
        # The loudest quarter of the windows: in the spin test that is the looped ambient source
        # west of the start, so its balance should swing with the heading (positional=1) or stay
        # on one side (positional=0).
        cut = sorted(level)[3 * len(level) // 4]
        loud = [(m, y) for m, y, lv in zip(meas, yawsw, level) if lv >= cut]
        lm = [m for m, _ in loud]
        print(f"loudest quarter ({len(loud)} windows): balance {min(lm):+.2f}..{max(lm):+.2f}; "
              f"left {sum(1 for m in lm if m < -0.1)}, right {sum(1 for m in lm if m > 0.1)}, centre {sum(1 for m in lm if abs(m) <= 0.1)}")
    print(f"windows with sound and logged sources: {len(meas)}")
    if meas:
        print(f"measured balance (R-L)/(R+L): mean {sum(meas) / len(meas):+.3f}, "
              f"range {min(meas):+.2f}..{max(meas):+.2f}")
    print(f"corr(measured, camera-frame prediction) = {c_cam:+.3f}")
    print(f"corr(measured, top-down prediction)     = {c_game:+.3f}")
    ok = not math.isnan(c_cam) and (math.isnan(c_game) or c_cam > c_game)
    print("PASS: the recording follows the street camera" if ok else
          "FAIL or inconclusive (with positional=0 the two predictions are the same: the expected baseline)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
