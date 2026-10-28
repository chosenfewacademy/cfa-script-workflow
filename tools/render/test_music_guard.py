"""Music spend guard + per-episode cache (mocked, $0)."""
import os, sys, json, tempfile, subprocess, glob
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m); fails += 0 if c else 1

if len(sys.argv) > 1 and sys.argv[1] == "--child":
    import render as R
    log = sys.argv[2]
    def fake(total, arc, style, key, work, src="el"):
        open(log, "a").write(src + "\n")
        out = os.path.join(work, "score.mp3")
        subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=%.1f" % min(total, 20), "-b:a", "128k", out])
        return out, R.music_plan(total, arc, style)
    R.compose_music = lambda *a: (None, "HTTP 401") if os.environ.get("EL_FAIL") else fake(*a)
    R.compose_music_fal = lambda *a: fake(*a, src="fal")
    sys.argv = ["render.py"] + sys.argv[3:]
    R.main(); sys.exit(0)

import render as R
check(abs(R.music_cost(40) - 0.455) < 0.01, "40 s clip est $%.3f" % R.music_cost(40))
check(R.music_guard(40, 1.0)[0] and not R.music_guard(300, 1.0)[0], "$1 cap: 40 s allowed, 5-min refused")
check(not R.music_guard(40, 0)[0] and not R.music_guard(40, None)[0], "cap 0/None never composes")
check(not R.music_guard(40, 1.0, spent=0.7)[0], "already-spent counts toward cap")
import random; random.seed(3); bad = 0
for _ in range(5000):
    t, cap, sp = random.uniform(1, 1200), random.uniform(-1, 10), random.uniform(0, 5)
    ok, est, _ = R.music_guard(t, cap, sp)
    bad += ok and sp + est > cap + 1e-9
check(bad == 0, "5000 random cases never over cap")
check(R.music_cache_key({"videoId": "v23"}, "cinematic") == "v23__cinematic", "cache key episode+style")

import test_render as T
with tempfile.TemporaryDirectory() as d:
    z, _ = T.make_bundle(os.path.join(d, "src"))
    keys = os.path.join(d, "k.env"); open(keys, "w").write("ELEVENLABS_API_KEY=x\nFAL_KEY=x\n")
    calls = os.path.join(d, "calls.log"); cache = os.path.join(d, "cache")
    def run(out, cap, env2=None):
        env = dict(os.environ, CFA_MUSIC_CACHE=cache, **(env2 or {}))
        r = subprocess.run([sys.executable, __file__, "--child", calls, z, "-o", out, "--no-grok", "--no-whisper",
                            "--no-ambience", "--keys-env", keys, "--music-cap", str(cap)], capture_output=True, text=True, env=env)
        g = glob.glob(os.path.join(out, "**", "report.json"), recursive=True)
        if r.returncode: print(r.stdout[-600:], r.stderr[-600:])
        return r, (json.load(open(g[0])).get("music", {}) if g else {})
    n = lambda: len(open(calls).read().split()) if os.path.exists(calls) else 0
    r, m = run(os.path.join(d, "o0"), 0.01)
    check(r.returncode == 0 and n() == 0 and m.get("guard"), "cap < est: 0 paid calls, render ok")
    r, m = run(os.path.join(d, "o1"), 1.0, {"EL_FAIL": "1"})
    check(r.returncode == 0 and n() == 1 and m.get("billed_usd", 0) > 0, "EL fail -> fal once, billed recorded %s" % m.get("source"))
    for k in range(3):
        r, m = run(os.path.join(d, "o%d" % (k + 2)), 1.0)
    check(n() == 1 and m.get("source") == "cache" and m.get("billed_usd") == 0, "3 reruns reuse cache: 1 paid call total")
print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
