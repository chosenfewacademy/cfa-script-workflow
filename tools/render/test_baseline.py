"""The regression check accepts the baseline's own numbers and catches the v5 regressions."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baseline_check as B
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
base = {"duration": 23.0, "shot_lengths": [5.76, 4.91, 7.3, 5.03], "motion_gate": {"pass": True, "median_shot_s": 4.83, "motion_px_s": 4.37, "similarity": {"pass": True}},
        "i2v": {"mode": "hailuo", "clips": 1}}
check("baseline report passes its own check", all(ok for _, ok, _ in B.compare(base, B.BASELINE_OCT28)), [r for r in B.compare(base, B.BASELINE_OCT28) if not r[1]])
v5 = {"duration": 26.4, "shot_lengths": [5.8, 2.1, 3.9, 7.8], "motion_gate": {"pass": False, "median_shot_s": 3.9, "motion_px_s": 3.0, "similarity": {"pass": False}},
      "i2v": {"mode": "kling-ref", "clips": 0, "degraded": [6]}, "held_neighbour": [2]}
bad = [n for n, ok, _ in B.compare(v5) if not ok]
check("v5 regressions are caught (gate, no clip, degraded, model, motion, re-angle, hold)", len(bad) >= 7, bad)
import json, copy
v8 = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline_v8_report.json")))
rows = B.compare(v8)
check("v8 locked report passes the default (v8) baseline", all(ok for _, ok, _ in rows), [r for r in rows if not r[1]])
for name, mut in (("low bitrate", lambda r: r["motion_gate"]["sharpness"].update(kbps=5200)),
                  ("blurred edge", lambda r: r["motion_gate"]["edges"].update(**{"pass": False})),
                  ("over-upscaled still", lambda r: r["motion_gate"]["sharpness"]["upscale"].append([6, 2.4])),
                  ("second phone", lambda r: r["still_props"]["media/scene_004.png"].update(ok=False)),
                  ("off-script shot", lambda r: r["motion_gate"].update(fidelity={"pass": False, "fails": [["media/scene_005.png", "no phone"]]})),
                  ("lost motion clip", lambda r: r.update(i2v={"mode": "hailuo", "clips": 0}, shots=[dict(x, type="image") for x in r["shots"]]))):
    r = copy.deepcopy(v8); mut(r)
    check("v8 baseline catches: " + name, not all(ok for _, ok, _ in B.compare(r)))
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
