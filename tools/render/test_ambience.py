#!/usr/bin/env python3
"""Offline unit test for per-scene ElevenLabs ambience (urlopen mocked; $0)."""
import io, os, subprocess, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import render as R
fails = 0
def check(c, m):
    global fails; print(("PASS " if c else "FAIL ") + m); fails += 0 if c else 1
d = tempfile.mkdtemp(prefix="cfa-amb-")
snd = os.path.join(d, "s.mp3")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=3:a=0.3", "-ac", "2", snd], check=True)
calls = []
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
def fake(req, timeout=0):
    import json; b = json.loads(req.data); calls.append(b)
    if "fail" in b["text"]: raise OSError("HTTP 500")
    return Resp(open(snd, "rb").read())
urllib.request.urlopen = fake
segs = [{"index": 1, "sfx": "shop bell, room tone"}, {"index": 2, "sfx": "Shop bell, room tone"}, {"index": 3, "sfx": "music and voices"},
        {"index": 4, "sfx": ""}, {"index": 5, "sfx": "fail please"}, {"index": 6, "sfx": "street traffic"}]
shots = [{"beats": [1], "start": 0, "duration": 2.0}, {"beats": [2], "start": 2, "duration": 2.0}, {"beats": [3], "start": 4, "duration": 2},
         {"beats": [4], "start": 6, "duration": 2}, {"beats": [5], "start": 8, "duration": 2}, {"beats": [6], "start": 10, "duration": 40}]
amb, info = R.scene_ambience(shots, segs, "k", d)
check(len(calls) == 3, "one ElevenLabs call per distinct description (cached, case-insensitive): %d" % len(calls))
check(all("no music, no voices" in c["text"] and "voices" not in c["text"].split(",")[0] for c in calls), "music/voice words stripped, ambient-only prompt")
check(max(c["duration_seconds"] for c in calls) == 22.0 and min(c["duration_seconds"] for c in calls) >= 1.0, "duration clamped to 1-22 s")
check(len(amb) == 3 and info["errors"] and info["generated"] == 2, "failed scene skipped, others placed: %s" % info)
check(R.scene_ambience(shots, segs, None, d)[0] == [], "no key -> no ambience")
out = R.build_sfx_track([("impact", 1.0, 0.8)], 12.0, d, amb)
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
check(abs(dur - 12.0) < 0.1, "sfx + ambience track spans the voice (%.2fs)" % dur)
print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
