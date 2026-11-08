#!/usr/bin/env python3
"""PLAYTHROUGH-8 respray probe (Industrial): does a numeric CAR_SHOP (bil.mis shop12,
64.5,90.5, `CAR_SHOP 0`) repair a damaged car? F9 into the nearest parked car, a few
wall hits, then into the shop; carhp and money from the mission line before and after."""
import os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
D.start(); s = D.wait_state(40); D.calibrate_turn()
world = M.World("bil")
VIEW = ["classic"]
def view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(1.2); VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
M.VIEW_HOOK[0] = view; view("third")
SHOP = (float(os.environ.get("SHOP_X", "64.5")), float(os.environ.get("SHOP_Y", "90.5")))
s = M.any_car2(world, budget=150)
say("in car:", s["driving"], M.mission_state())
M.mark("in a car")
for k in range(3):
    xdo("keydown", "Up"); time.sleep(1.5); xdo("keyup", "Up"); hold("Down", 0.8)
ms = M.mission_state(); say("after hits:", ms); M.mark(f"after hits carhp {ms.get('carhp')} money {ms.get('money')}")
M.shot("before")
s = M.drive3(world, SHOP[0], SHOP[1] - 3.0, tol=1.0, budget=200, slow=True, precious=True)
say("at the driveway:", s["x"], s["y"], M.mission_state())
for k in range(10):
    s = D.wait_state(); ms = M.mission_state()
    say(f"creep {k}: {s['x']:.2f},{s['y']:.2f} carhp {ms.get('carhp')} money {ms.get('money')} msg {ms.get('msg')}")
    if abs(s["y"] - SHOP[1]) < 0.4: break
    a = D.angle_to(s, SHOP[0], SHOP[1])
    if abs(a) > 0.2: xdo("keydown", "Right" if a > 0 else "Left")
    xdo("keydown", "Up"); time.sleep(0.35); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left"); time.sleep(0.4)
for k in range(8):
    time.sleep(1.5); ms = M.mission_state(); s = D.wait_state()
    say(f"in the shop {k}: {s['x']:.2f},{s['y']:.2f} carhp {ms.get('carhp')} money {ms.get('money')} msg {ms.get('msg')}")
M.shot("in_shop")
M.drive3(world, SHOP[0], SHOP[1] - 4.0, tol=1.0, budget=40, slow=True, precious=True)
time.sleep(2); ms = M.mission_state(); M.mark(f"after the shop carhp {ms.get('carhp')} money {ms.get('money')}"); M.shot("after")
import shutil; shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
open("/out/.keys_done", "w").close()
