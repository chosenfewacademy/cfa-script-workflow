"""Regression check of a test-clip report against the baseline the user rated best (test_clip_vision, job 784d459c2dca, Oct 28 22:46).
Usage: python3 baseline_check.py out/report.json  -> prints PASS/FAIL lines, exit 1 on any regression."""
import json, sys

BASELINE = {"seconds": 23.0, "median_shot_s": 4.83, "motion_px_s": 4.37, "i2v_clips": 1, "i2v_mode": "hailuo", "shots": 5}


def compare(r, base=BASELINE):
    """Return [(name, ok, detail)] for a render report (dict)."""
    g = r.get("motion_gate") or {}
    i2v = r.get("i2v") or {}
    sec = float(r.get("duration") or (r.get("test_clip") or {}).get("seconds") or 0)
    lens = [float(x) for x in (r.get("shot_lengths") or [])]
    out = [
        ("length 15-30s", 15.0 <= sec <= 30.5, sec),
        ("motion gate passes", bool(g.get("pass")), g.get("fails")),
        ("real motion clip made (>= baseline's %d)" % base["i2v_clips"], int(i2v.get("clips") or 0) >= base["i2v_clips"], i2v.get("clips")),
        ("no action shot degraded to a still", not i2v.get("degraded"), i2v.get("degraded")),
        ("same motion model as baseline (%s)" % base["i2v_mode"], i2v.get("mode") == base["i2v_mode"], i2v.get("mode")),
        ("motion >= 80%% of baseline %.2f px/s" % base["motion_px_s"], float(g.get("motion_px_s") or 0) >= 0.8 * base["motion_px_s"], g.get("motion_px_s")),
        ("median shot within 3.0-6.0s (baseline %.2f)" % base["median_shot_s"], 3.0 <= float(g.get("median_shot_s") or 0) <= 6.0, g.get("median_shot_s")),
        ("no shot under 2s or over 8s", all(2.0 <= x <= 8.0 for x in lens) if lens else True, lens),
        ("similarity (no re-angled copies) passes", bool((g.get("similarity") or {}).get("pass", True)), (g.get("similarity") or {}).get("fails")),
        ("no held neighbour shots", not r.get("held_neighbour"), r.get("held_neighbour")),
    ]
    return out


if __name__ == "__main__":
    rows = compare(json.load(open(sys.argv[1])))
    for n, ok, x in rows:
        print(("PASS " if ok else "FAIL ") + n, "" if ok else x)
    sys.exit(0 if all(ok for _, ok, _ in rows) else 1)
