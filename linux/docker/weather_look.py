#!/usr/bin/env python3
"""QB-35/QB-43 look check (docs/weather.md): the plain renderer at several times of day and in
rain and fog, at one Downtown spot, chase and first-person views on foot. Drives the live
[weather] keys (re-read every 2 s): time_of_day=1 puts the street views' sun on the clock,
hour_hhmm sets the clock, clock_paused holds it, rain/fog/cloud percent set the weather,
wet_percent forces the roads' wetness, fade_seconds=0 makes each change immediate.
Shots in /out/w_*.png, marks in /out/marks.txt. Env: WX_SPOT (index, default 0), WX_VISUALS (1)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import mark, shot, view, warp
INI = T.INI

def setk(section, key, val):
    s = open(INI, encoding="latin-1").read()
    if f"[{section}]" not in s: s += f"\n[{section}]\n"
    head, sec = s.split(f"[{section}]", 1)
    nxt = re.search(r"(?m)^\[", sec)
    body, rest = (sec[:nxt.start()], sec[nxt.start():]) if nxt else (sec, "")
    if re.search(rf"(?m)^{key}=.*$", body): body = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", body)
    else: body = f"\n{key}={val}" + body
    open(INI, "w", encoding="latin-1").write(head + f"[{section}]" + body + rest)
    mark(f"SET {section} {key}={val}")

def weather(rain=0, fog=0, cloud=0, wet=-1, wind=30):
    setk("weather", "rain_percent", rain); setk("weather", "fog_percent", fog)
    setk("weather", "cloud_percent", cloud); setk("weather", "wet_percent", wet); setk("weather", "wind_percent", wind)

def main():
    T.Q.start("weather_look")
    vis = os.environ.get("WX_VISUALS", "1")
    setk("visuals", "enabled", vis)
    for k, v in (("enabled", 1), ("time_of_day", 1), ("clock_paused", 1), ("fade_seconds", 0), ("hour_hhmm", 1000)):
        setk("weather", k, v)
    weather()
    spots = [(164.5, 149.5), (122.5, 155.5), (124.5, 212.5)]
    spot = spots[int(os.environ.get("WX_SPOT", "0"))]
    warp(*spot, None, why="weather spot")
    time.sleep(2.0)
    HOURS = [("day", 1000), ("golden", 1720), ("blue", 1825), ("night", 2230)]
    WX = [("clear", dict()), ("rain", dict(rain=100, cloud=100, wet=100, wind=40)), ("fog", dict(fog=90, cloud=60))]
    for v in ("third", "first"):
        view(v); time.sleep(4.0)
        if v == "first": T.clear_of_cars()
        for hname, hh in HOURS:
            setk("weather", "hour_hhmm", hh); time.sleep(0.4)
            for wname, kw in WX:
                if v == "first" and wname == "fog": continue
                weather(**kw); time.sleep(2.6); shot(f"w_{v}_{hname}_{wname}")
    # The roads drying after the rain stops (no forced wetness), at night in the chase view.
    view("third"); time.sleep(1.5)
    setk("weather", "fade_seconds", 4); weather(rain=100, cloud=100, wet=-1, wind=60)
    for i in range(4): time.sleep(5.0); shot(f"w_wetting_{i}")
    weather(rain=0, cloud=30, wet=-1)
    for i in range(3): time.sleep(5.0); shot(f"w_drying_{i}")
    # Off again: the frame as it was.
    setk("weather", "enabled", 0); time.sleep(2.6); shot("w_off_after")
    view("classic"); time.sleep(1.5); shot("w_classic_after")
    open("/out/.keys_done", "w").close()

if __name__ == "__main__":
    main()
