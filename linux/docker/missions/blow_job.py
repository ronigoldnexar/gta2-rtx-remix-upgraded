#!/usr/bin/env python3
"""BLOW JOB! (Residential, the Rednecks' first job, ste_re1) played through both
stages in the street views, on the shared district runner's primitives.

The job (`assets-src/missions/ste_m/ste_re1.mis`): a rigged Pickup (model 41,
CREATE_GANG_CAR at 24.0,41.5) into the 3x1 block at Fat Boy Jim's trailer
(48.5,20.5), fire to arm the car bomb, get out; when it is wrecked inside the
block (2012) a second Pickup is created at 24.0,44.5 for the 3x1 block at the
barricade (111.5,77.5; the arrow stands on 110.5,77.5), the same again, and
the job pays $30,000 (2021, 2999). A death or an arrest ends the job.

What the earlier runs did not see (PLAYTHROUGH-10, from the renderer's logs):

- pt8_ste2 and pt9_ste5 were **not** stage-2 failures. In both the player died
  in the stage-1 blast (health 0, lives 5 -> 4 one second after 2012) and the
  job ended there (6152 / 6150); the "second Pickup" they then drove was a
  traffic Pickup of the same model. The cause was the escape: `arm_and_run`'s
  routed escape point lay east of the car (60.5,20.5) while the car faced west,
  so the player turned round on the spot for a second and then ran into the
  trailer's corner, 1.5 blocks from the bomb. pt7_ste5, the one complete run,
  ran straight on along the car's heading (west, 11 blocks in the fuse).
  The bomb's fuse is about 3 s of wall time at GTA2_SPEED=2 (2006 -> 2012:
  3.2, 2.8, 2.5 s in pt7_ste5, pt8_ste2, pt9_ste5).
- The stage-2 Pickup carries a kind-3 arrow from the moment it is created:
  the mission line's `tcar` is its position (24.0,44.5 in all three runs), so
  it is found from the game, not from a fixed spawn.

So this runner: the same line-up parks as `play_ste_re1`; an escape that holds
Up the moment he is out and runs along fixed legs away from the blast (west
along the field rows 20-22 at the trailer, north-west up the road columns
105-108 at the barricade); the second Pickup taken where `tcar` says it is,
after a short lie-low while the blast's wanted level is up; JOB COMPLETE
watched for and shot.

Usage (inside the container; gamerun/keys_blow_job.sh):
    DISTRICT=ste python3 /work/missions/blow_job.py
"""
import math, os, sys, time
sys.path.insert(0, "/work")
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = ""      # the shared runner sets the session up and plays nothing itself
sys.argv = sys.argv[:1]
import mission_play_districts as P   # starts the session: level, views, world, arrows baseline
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
NAME = "ste_re1"
TRAILER = (48.5, 20.5)            # stage 1 block (3 x 1), arrow 48.5,20.5
BARRICADE = (110.5, 77.5)         # stage 2 arrow; the block is 111.5,77.5 3 x 1 (cells 110-112, row 77)
# Escape routes, each a list of legs, about 12 blocks from the blast. The player leaves the car
# on its right side (y south: right = (-hy, hx); pt9_ste5 facing west came out north, pt10_bj3 facing
# north came out east), and a route that crosses the car or the trailer costs the fuse (pt10_bj3:
# out on the east side, the west route sent him round the car's nose, 1.5 blocks from it at the blast)
ESCAPES = {
    1: {"west": [(44.0, 21.7), (37.0, 22.2), (31.0, 22.4)],          # the field rows 20-21 and the road on 22-23
        "east": [(53.5, 21.8), (59.0, 22.3), (63.5, 22.5)]},
    2: {"north": [(107.5, 74.5), (106.6, 68.0), (106.6, 64.5)],      # the road columns 105-108 (rows 58-95)
        "south": [(107.5, 80.5), (106.6, 86.0), (106.6, 89.5)]},
}
BUST_KEYS = {"6155", "6159"}       # "I hope the Cops..." (pt7_ste1, pt7_ste4): arrested
LIE_LOW = float(os.environ.get("BJ_LIE_LOW", "25"))   # game seconds to wait for the blast's wanted level to go


def ms():
    return M.mission_state() or {}

def status(money0, lives0):
    """complete / failed / dead / busted / running, from the game's own fields"""
    st = ms()
    if not st: return "running", st
    if st.get("msg") in M.COMPLETE_KEYS or st.get("money", 0) >= money0 + 10000 or st.get("msg") == "2021":
        return "complete", st
    if st.get("msg") in M.FAILED_KEYS: return "failed", st
    if st.get("msg") in BUST_KEYS: return "busted", st
    if st.get("health") == 0 or st.get("lives", lives0) < lives0: return "dead", st
    return "running", st

def shots(prefix, n=3, gap=0.6):
    for i in range(n):
        M.shot(f"{prefix}_{i}"); time.sleep(gap)


def fire_bomb(armed_msgs):
    """fire (Control) until the game says the bomb is armed; never with the car out of the block"""
    M.mark("arming the explosives")
    # the on-foot view now, while the car stands in the block: a view change after the exit
    # costs 2 s a V press, most of the fuse
    M.ensure_view("classic")
    m0 = ms().get("msg")
    for k in range(8):
        if ms().get("msg") in ("2004", "2017"):
            say(f"arm: the car is out of the block (msg {ms().get('msg')}); not firing"); return False
        if k == 3: tap("Tab", 0.3); time.sleep(0.5)     # the weapon slot, in case the bomb is not selected
        xdo("keydown", "Control_L"); time.sleep(0.4); xdo("keyup", "Control_L"); time.sleep(0.6)
        if ms().get("msg") in armed_msgs: return True
        if ms().get("msg") != m0 and M.objective() is None: return True
    return False

def pick_escape(n, car, heading, p):
    """the route whose first leg leads away from the car on the side he got out on"""
    hx, hy = heading
    side = (-hy, hx)                                   # the right-hand door
    vx, vy = p[0] - car[0], p[1] - car[1]; nv = math.hypot(vx, vy)
    if nv > 0.15: side = ((side[0] + vx / nv) / 2, (side[1] + vy / nv) / 2)
    best = None
    for name, legs in ESCAPES[n].items():
        dx, dy = legs[0][0] - p[0], legs[0][1] - p[1]; d = math.hypot(dx, dy) or 1.0
        dx, dy = dx / d, dy / d
        score = dx * side[0] + dy * side[1] + 0.4 * (dx * hx + dy * hy)
        say(f"escape {name}: score {score:.2f}")
        if best is None or score > best[0]: best = (score, name, legs)
    return best[1], best[2]

def run_legs(legs, secs):
    """Up held from the first moment, steering pulses toward each leg in turn; no unstick
    moves (a step back is the fuse's last second)"""
    t0 = time.time(); k = 0
    xdo("keydown", "Up")
    try:
        while (time.time() - t0) * D.SPEED < secs and k < len(legs):
            s = D.wait_state()
            if not s: break
            tx, ty = legs[k]
            if math.hypot(tx - s["x"], ty - s["y"]) < 1.2:
                k += 1; continue
            a = D.angle_to(s, tx, ty)
            if abs(a) > 0.15:
                key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
                xdo("keydown", key); time.sleep(min(abs(a) / max(D.rate, 2.0), 0.35)); xdo("keyup", key)
            time.sleep(0.1)
    finally:
        xdo("keyup", "Up")
    return D.wait_state()

def run_clear(n, car, heading, secs=14.0):
    """out of the car and away from the bomb: the fuse is about 3 s of wall time at
    GTA2_SPEED=2 (2006 -> 2012 in 3.2, 2.8, 2.5 s), and a turn on the spot or a route round
    the car (pt8_ste2, pt9_ste5, pt10_bj3) is a lost life and the job"""
    t0 = time.time()
    tap("Return", 0.25)
    for _ in range(12):
        s = D.wait_state()
        if s and not s["driving"]: break
        time.sleep(0.1)
    s = D.wait_state()
    name, legs = pick_escape(n, car, heading, (s["x"], s["y"]))
    M.mark(f"out of the car at {s['x']:.1f},{s['y']:.1f}, running clear {name}")
    s = run_legs(legs, secs)
    say(f"run_clear: at {s['x']:.1f},{s['y']:.1f} after {(time.time() - t0) * D.SPEED:.1f} game s" if s else "run_clear: no state")
    return s


def lie_low(secs):
    """the blast leaves wanted level 1 (pt7_ste1/4: arrested out of the crawling Pickup):
    stand still a while for the cop points to decay before taking the fragile car"""
    w0 = ms().get("wanted", 0)
    if w0 <= 0: return True
    M.mark(f"wanted level {w0} after the blast: lying low up to {secs:.0f} s")
    t0 = time.time()
    while (time.time() - t0) * D.SPEED < secs:
        if ms().get("wanted", 0) <= 0:
            M.mark(f"wanted level gone after {(time.time() - t0) * D.SPEED:.0f} game s"); return True
        time.sleep(1.0)
    M.mark(f"still wanted ({ms().get('wanted')}): going on")
    return False


def take_pickup(stage, money0, lives0):
    """into the stage's Pickup, found where the game's kind-3 arrow says it is (tcar)"""
    for attempt in range(4):
        st = ms(); tc = st.get("tcar")
        o = M.objective()
        if tc and tc[0] > 0:
            cx, cy = tc
        elif o and o[3] in (3, 4):
            cx, cy = o[0], o[1]
        else:
            cx, cy = (24.0, 41.5) if stage == 1 else (24.0, 44.5)
        M.mark(f"stage {stage}: the Pickup at {cx:.1f},{cy:.1f} (tcar {tc}), try {attempt + 1}")
        s = D.wait_state()
        if s and s["driving"]:
            s = M.leave_car()
        # walk near first, re-reading tcar on the way (a gang car can be driven off)
        if s and math.hypot(s["x"] - cx, s["y"] - cy) > 12:
            s = M.walk3(world, cx, cy, None, tol=8.0, budget=240)
            tc2 = ms().get("tcar")
            if tc2 and tc2[0] > 0 and math.hypot(tc2[0] - cx, tc2[1] - cy) > 2.0:
                say(f"take_pickup: the Pickup moved to {tc2[0]:.1f},{tc2[1]:.1f}"); continue
        s = P.enter_parked(cx, cy, budget=200, why=f"the Pickup {stage}")
        out, st = status(money0, lives0)
        if out != "running": return None
        if s and s["driving"] and st.get("carmodel") == 41:
            time.sleep(1.0)
            if ms().get("tcarhp", -1) == -1:       # the arrow left the car he sits in: it is the mission car
                return s
            say(f"take_pickup: in a model-41 car, but the arrow is still on a car at {ms().get('tcar')}: out")
            s = M.leave_car()
        elif s and s["driving"]:
            say(f"take_pickup: in a car of model {st.get('carmodel')}, not the Pickup: out")
            s = M.leave_car()
    return None


def stage(n, money0, lives0):
    box = (TRAILER if n == 1 else BARRICADE)
    armed_msgs = ("2006",) if n == 1 else ("2018",)
    parked_msgs = ("2005",) if n == 1 else ("2016",)
    s = take_pickup(n, money0, lives0)
    if not (s and s["driving"]):
        out, _ = status(money0, lives0)
        return out if out != "running" else "no pickup"
    P.FP["until"] = 0.0
    M.shot(f"{NAME}_incar{n}")
    o = P.wait_arrow(20, kinds=(1,))
    x, y = (o[0], o[1]) if o else box
    for tries in range(4):
        ok, s = P.park_in_block(x, y, 3.0, 1.0, money0, parked_msgs=parked_msgs)
        out, st = status(money0, lives0)
        if out != "running": return out
        say(f"stage {n}: after the park: carhp {st.get('carhp')} msg {st.get('msg')} at {s['x']:.2f},{s['y']:.2f}" if s else "no state")
        M.shot(f"{NAME}_block{n}")
        if st.get("msg") in parked_msgs or st.get("msg") in ("2008", "2019"):
            if fire_bomb(armed_msgs): break
        if not (s and s["driving"]):
            s = take_pickup(n, money0, lives0)
            if not s: return "lost the pickup"
    else:
        return "not armed"
    cs = D.wait_state()
    hx, hy = M.heading(cs)
    M.mark(f"stage {n}: armed at {cs['x']:.2f},{cs['y']:.2f} heading {hx:.2f},{hy:.2f}")
    run_clear(n, (cs['x'], cs['y']), (hx, hy))
    # the blast and its verdict
    t0 = time.time(); shot_done = False
    while (time.time() - t0) * D.SPEED < 60:
        out, st = status(money0, lives0)
        if n == 2 and out == "complete":
            if not shot_done: shots(f"{NAME}_complete", n=4, gap=0.5); shot_done = True
            return "complete"
        if out != "running": return out
        m = st.get("msg")
        if n == 1 and m == "2012" and st.get("tcar") and st["tcar"][0] > 0:
            M.mark(f"stage 1 done (2012): the second Pickup at {st['tcar'][0]:.1f},{st['tcar'][1]:.1f}, wanted {st.get('wanted')}")
            M.shot(f"{NAME}_blast1")
            return "next"
        if m in ("2008", "2019", "2004", "2017"):
            say(f"stage {n}: the game wants the bomb armed (msg {m}): back to the Pickup")
            return stage(n, money0, lives0)
        time.sleep(0.3)
    return "no blast"


def main():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: {entry.get('title', '')} (missions/blow_job.py)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = P.answer(entry)
    say("answered:", ok, key); M.shot(f"{NAME}_phone")
    if not ok:
        M.mark(f"mission {NAME}: phone not answered"); return "phone not answered"
    started = P.TITLES.get(key)
    if started and started.get("mission") != NAME:
        M.mark(f"the phone next door answered: {started['mission']} {started.get('title', '')}")
        return "wrong phone"
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    st = ms(); money0 = st.get("money", 0); lives0 = st.get("lives", 5)
    M.LIVES0[0] = lives0
    M.SLOW_CAP = 2.0
    r = stage(1, money0, lives0)
    M.mark(f"stage 1: {r}")
    if r == "next":
        lie_low(LIE_LOW)
        r = stage(2, money0, lives0)
        M.mark(f"stage 2: {r}")
    out, st = status(money0, lives0)
    if r == "complete" or out == "complete":
        r = "complete"
    M.mark(f"mission {NAME}: {r} ({time.time() - t_m:.0f}s wall) money {st.get('money')} lives {st.get('lives')}")
    M.shot(f"{NAME}_end")
    time.sleep(4)
    return r


if __name__ == "__main__":
    r = main()
    say("RESULT", NAME, r)
    M.mark(f"done blow_job={r}")
