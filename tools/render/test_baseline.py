"""The regression check accepts the baseline's own numbers and catches the v5 regressions."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baseline_check as B
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
base = {"duration": 23.0, "shot_lengths": [5.76, 4.91, 7.3, 5.03], "motion_gate": {"pass": True, "median_shot_s": 4.83, "motion_px_s": 4.37, "similarity": {"pass": True}},
        "i2v": {"mode": "hailuo", "clips": 1}}
check("baseline report passes its own check", all(ok for _, ok, _ in B.compare(base)), [r for r in B.compare(base) if not r[1]])
v5 = {"duration": 26.4, "shot_lengths": [5.8, 2.1, 3.9, 7.8], "motion_gate": {"pass": False, "median_shot_s": 3.9, "motion_px_s": 3.0, "similarity": {"pass": False}},
      "i2v": {"mode": "kling-ref", "clips": 0, "degraded": [6]}, "held_neighbour": [2]}
bad = [n for n, ok, _ in B.compare(v5) if not ok]
check("v5 regressions are caught (gate, no clip, degraded, model, motion, re-angle, hold)", len(bad) >= 7, bad)
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
