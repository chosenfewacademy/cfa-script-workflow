"""Music plan respects ElevenLabs chunk limits; foley plan/placement is sane (mocked, $0)."""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m); fails += 0 if c else 1
# music: stress many totals/turns
import random
random.seed(1)
for _ in range(2000):
    total = random.uniform(8, 900)
    arc = {"hook_end": random.uniform(0, total), "turn": random.choice([None, random.uniform(0, total)])}
    plan = R.music_plan(total, arc, random.choice(list(R.MUSIC_STYLES) + ["nope"]))
    bad = [c["duration_ms"] for c in plan if not (3000 <= c["duration_ms"] <= 120000)]
    if bad or not plan:
        check(False, "total %.1f plan out of limits %s" % (total, bad)); break
else:
    check(True, "2000 random plans: every chunk within 3000..120000 ms")
p = R.music_plan(299.18, {"hook_end": 3.67, "turn": 108.31}, "cinematic")
check(abs(sum(c["duration_ms"] for c in p) - 300680) < 50, "the failing episode (299 s) keeps its full length: %d ms in %d chunks" % (sum(c["duration_ms"] for c in p), len(p)))
check(any("continues" in c["text"] for c in p), "long resolve section split into continuation parts")
check(R.MUSIC_UNDER_DB[2] == 17.0, "music target 17 dB under voice")
# foley (Oct 28 audit: phone buzz removed, spoken line only, sparse, quiet, off by default)
segs = [{"index": i, "text": t, "prompt": pr} for i, (t, pr) in enumerate([("His phone buzzed.", "phone on desk"), ("He typed fast.", ""), ("Nothing here.", "laptop keyboard, phone screen, app"),
        ("She wrote it in the notebook.", ""), ("The door bell rang.", ""), ("Phone again.", ""), ("He set the wrench down.", ""), ("The invoice.", "")], 1)]
shots = [{"beats": [i], "start": 3.0 * (i - 1), "duration": 3.0} for i in range(1, 9)]
plan = R.foley_plan(shots, segs)
check(not any(k == "phone" for k, _ in plan) and "phone" not in [k for k, _, _ in R.FOLEY_KINDS], "no phone-vibration foley at all: %s" % plan)
check(not any(abs(t - 6.4) < 0.01 for _, t in plan), "image-prompt words never trigger foley (beat 3 prompt has keyboard/phone)")
check(plan and plan[0][0] == "typing", "spoken 'typed' gets typing: %s" % plan)
check(all(b[1] - a[1] >= 20 for a, b in zip(plan, plan[1:])) and R.FOLEY_GAP >= 20, "foley hits spaced >= 20 s")
check(R.FOLEY_GAIN <= 0.2, "foley gain <= 0.2")
check(R.FOLEY_DEFAULT_ON is False, "foley off by default")
segs2 = [{"index": 1, "text": "He typed the invoice on the keyboard."}]
big = [{"beats": [1], "start": 5.0 * k, "duration": 5.0} for k in range(500)]
bp = R.foley_plan(big, segs2)
check(len(bp) <= 2500 / 20 + 1 and len(bp) <= R.FOLEY_MAX, "500 shots: %d hits (<= 1 per 20 s, capped)" % len(bp))
calls = []
with tempfile.TemporaryDirectory() as w:
    wav = os.path.join(w, "x.mp3")
    subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=900:d=1.5", wav])
    data = open(wav, "rb").read()
    out, info = R.scene_foley(big, segs2, "k", w, fetch=lambda pr: calls.append(pr) or data)
    check(len(calls) == 1 and info["placed"] == len(bp), "one generation per kind (cached): %d calls, %d placed" % (len(calls), info["placed"]))
    out2, info2 = R.scene_foley(shots, segs, "k", w, fetch=lambda pr: (_ for _ in ()).throw(OSError("down")))
    check(out2 == [] and info2["errors"], "API failure -> no foley, no crash")
    trk = R.build_sfx_track([], 30.0, w, out[:6])
    vol = subprocess.run(["ffmpeg", "-i", trk, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    check("max_volume" in vol and "-inf" not in vol.split("max_volume")[1][:20], "foley mixes into the sfx track (audible)")
print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
