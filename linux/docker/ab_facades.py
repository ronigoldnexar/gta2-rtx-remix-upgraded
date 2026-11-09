#!/usr/bin/env python3
"""ASSET-BUILDINGS facade probe: at each spot (AB_SPOTS, JSON [[sx,sy,fx,fy],...]) the player is
warped on foot to (sx,sy) and frames are taken: classic (the BEV tile art), third person facing
the wall at (fx,fy), first person facing it, and first person turned along the street.
Frames /out/ab_<i>_<view>.png. Run with GTA2_DIRECT_KEYS=1, GTA2DX9_SCENE_NO_CAR=1 and
INI_SED='s/^scene_key=.*/scene_key=F11/'."""
import json, os, sys, time
sys.path.insert(0, "/work")
os.environ.setdefault("SCENE_KEY", "F11")
import tour_lib as T
import a3_lib as A
import qa_lib as Q

spots = json.loads(os.environ["AB_SPOTS"])
for i, sp in enumerate(spots):
    sx, sy, fx, fy = sp[:4]
    T.warp(sx, sy, why=f"ab spot {i}")
    time.sleep(1.5)
    T.shot(f"ab_{i}_classic")
    A.face(fx, fy)
    T.view("third"); time.sleep(1.0); T.shot(f"ab_{i}_third")
    T.view("first"); time.sleep(0.8); T.shot(f"ab_{i}_first")
    T.look("Left", 0.45); T.shot(f"ab_{i}_firstL")
    T.look("Right", 0.9); T.shot(f"ab_{i}_firstR")
    T.view("classic")
A.finish()
