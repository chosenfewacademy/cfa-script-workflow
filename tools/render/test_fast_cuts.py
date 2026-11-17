"""Fast Cuts cut style (opt-in): 1-3 s shots, each shot's own words, cutaways, hard cuts; v8 stays the default.
$0: no network (keys stripped from the environment for the end-to-end render)."""
import json, os, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("CFA_CAPTIONS", None)
import render as R
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)

# style resolution: v8 is the default, the bundle opts in, the CLI overrides, junk falls back to v8
check("default cut style is v8", R.cut_style({}) == "v8" and R.cut_style(None) == "v8")
check("bundle cutStyle fast_cuts opts in", R.cut_style({"cutStyle": "fast_cuts"}) == "fast_cuts")
check("spelling variants accepted", R.cut_style({"cutStyle": "Fast-Cuts"}) == "fast_cuts")
check("CLI overrides the bundle", R.cut_style({"cutStyle": "fast_cuts"}, "v8") == "v8" and R.cut_style({}, "fast_cuts") == "fast_cuts")
check("unknown style falls back to v8", R.cut_style({"cutStyle": "tiktok"}) == "v8")
check("v8 locked look unchanged", R.SHARPEN_VF == ",unsharp=3:3:0.9:3:3:0,cas=0.35" and R.FINAL_MIN_KBPS == 8000 and R.MIN_HOLD == 1.6 and R.DRIFT_MAX == 3.2)
check("fast cuts limits 1-3 s", (R.FAST_MIN_HOLD, R.FAST_MAX, R.FAST_GATE_MEDIAN_MAX) == (1.0, 3.0, 3.0))
check("fast cuts tightens pauses (0.3 / 0.25 s); v8 pauses untouched by default", R.FAST_PAUSES == (0.3, 0.25))
hold = R.split_fast_cuts([{"index": 1, "beats": [1], "start": 0.0, "end": 3.2, "duration": 3.2, "media": "q.png", "mediaType": "image", "motion": "static", "text": "q"}], [], [{"index": 1}])
check("a still just over 3 s with no cutaway stays one picture (no same-frame re-show)", len(hold) == 1, hold)
check("held quotes still move (v8: every still has a slow linear move)", hold[0]["motion"] == "zoom_in", hold[0].get("motion"))
check("no captions in fast cuts (captions stay off by default)", R.CAPTIONS_ON is False and "no captions" in R.FAST_EDL_NOTE)

words = [["w%d" % i, i * 0.4, i * 0.4 + 0.3] for i in range(40)]   # 16 s of words
segs = [{"index": 1, "cutaways": ["media/b.png", "media/c.png"]}, {"index": 2}, {"index": 3}]
shots = [{"index": 1, "beats": [1], "start": 0.0, "end": 6.0, "duration": 6.0, "media": "media/a.png", "mediaType": "image", "text": "x", "transition_in": "cut", "transition_duration": 0.0},
         {"index": 2, "beats": [2], "start": 6.0, "end": 8.0, "duration": 2.0, "media": "media/d.png", "mediaType": "image", "text": "y", "transition_in": "dissolve", "transition_duration": 0.8},
         {"index": 3, "beats": [3], "start": 8.0, "end": 15.0, "duration": 7.0, "media": "media/e.png", "mediaType": "image", "text": "z", "transition_in": "cut", "transition_duration": 0.0}]
out = R.split_fast_cuts([dict(x) for x in shots], words, segs)
d = [x["end"] - x["start"] for x in out]
check("every shot with enough pictures is 1-3 s", all(1.0 - 1e-6 <= v <= 3.0 + 1e-6 for x, v in zip(out, d) if x["beats"] != [3]), d)
check("timeline covered with no gaps", abs(out[0]["start"]) < 1e-6 and abs(out[-1]["end"] - 15.0) < 1e-6 and all(abs(a["end"] - b["start"]) < 1e-6 for a, b in zip(out, out[1:])))
check("long beat with cutaways shows a new picture per part", [x["media"] for x in out if x["beats"] == [1]] == ["media/a.png", "media/b.png", "media/c.png"], [x["media"] for x in out])
check("cutaway parts are marked", sum(1 for x in out if x.get("fast_cutaway")) == 2)
check("a beat with no cutaways is never reframed or re-shown: it stays one picture", [x["media"] for x in out if x["beats"] == [3]] == ["media/e.png"] and not any(x.get("fast_reframe") for x in out))
check("no picture appears in two shots", len({x["media"] for x in out}) == len(out), [x["media"] for x in out])
check("every join is a hard cut (no dissolves eating 1-3 s shots)", all(x["transition_in"] == "cut" and x["transition_duration"] == 0.0 for x in out[1:]))
check("each part carries its own words as its line", out[1]["line"] and out[1]["line"] != out[0]["line"] and out[0]["line"].startswith("w0"), [x["line"] for x in out[:3]])
check("indexes renumbered", [x["index"] for x in out] == list(range(1, len(out) + 1)))
vid = [{"index": 1, "beats": [9], "start": 0.0, "end": 5.0, "duration": 5.0, "media": "m.mp4", "mediaType": "video"}]
check("a clip with no cutaways stays one running shot", len(R.split_fast_cuts(vid, words, [{"index": 9}])) == 1)
vc = R.split_fast_cuts([dict(vid[0])], words, [{"index": 9, "cutaways": ["media/k.png"]}])
check("a long clip cuts to its cutaway, never freezes", [x["mediaType"] for x in vc] == ["video", "image"] and abs(vc[-1]["end"] - 5.0) < 1e-6, [(x["mediaType"], x["start"], x["end"]) for x in vc])
lip = [{"index": 1, "beats": [9], "start": 0.0, "end": 5.0, "duration": 5.0, "media": "t.mp4", "mediaType": "lipsync"}]
check("talking (lip-sync) shots are never split", len(R.split_fast_cuts(lip, words, [{"index": 9, "cutaways": ["media/k.png"]}])) == 1)
sp = [{"index": 1, "beats": [1], "start": 0.0, "end": 2.0, "duration": 2.0, "mediaType": "image"}, {"index": 2, "beats": [2], "start": 2.0, "end": 3.1, "duration": 1.1, "mediaType": "image"},
      {"index": 3, "beats": [3], "start": 3.1, "end": 5.0, "duration": 1.9, "mediaType": "image"}]
spg = [{"index": 1, "start": 0.0}, {"index": 2, "start": 2.3}, {"index": 3, "start": 3.1}]
R.apply_shot_plan([dict(x) for x in sp], spg)
fsp = R.apply_shot_plan([dict(x) for x in sp], spg, R.FAST_SNAP_MIN)
check("fast cuts: a short quote's cut still lands on its first word", abs(fsp[1]["start"] - 2.3) < 1e-6 and abs(R.apply_shot_plan([dict(x) for x in sp], spg)[1]["start"] - 2.0) < 1e-6, [x["start"] for x in fsp])
g = R.fast_cuts_gate(out)
check("gate fails the 7 s still that had no distinct pictures, naming it", not g["pass"] and g["long_stills"] == [len(out)] and "add more distinct stills" in g["fails"][0], g)
g = R.fast_cuts_gate([x for x in out if x["beats"] != [3]])
check("gate passes a 1-3 s cut", g["pass"] and g["median_s"] <= 3.0, g)
g2 = R.fast_cuts_gate([dict(shots[0]), dict(shots[2])])
check("gate fails 6-7 s stills", not g2["pass"] and g2["long_stills"] == [1, 3], g2)

# end-to-end: a synthetic fast-cuts bundle renders 1-3 s shots, no captions, report records the style
d0 = tempfile.mkdtemp()
def ff(*a): subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)
os.makedirs(os.path.join(d0, "b", "media"))
cols = ["red", "green", "blue", "yellow", "purple", "orange"]
sys.path.insert(0, HERE)
from test_unique_shots import unique_still
for i, c in enumerate(cols):
    unique_still(os.path.join(d0, "b", "media", "s%d.png" % i), seed=100 + i)
ff("-f", "lavfi", "-i", "sine=f=200:d=12", "-ar", "44100", os.path.join(d0, "b", "voiceover.mp3"))
W = [["word%d" % i, round(i * 0.4, 2), round(i * 0.4 + 0.3, 2)] for i in range(30)]
bundle = {"format": "cfa-final-edit-bundle", "version": 1, "title": "fast cuts test", "voiceover": "voiceover.mp3", "words": W, "cutStyle": "fast_cuts",
          "segments": [{"index": 1, "text": " ".join(w[0] for w in W[:15]), "media": "media/s0.png", "mediaType": "image", "characters": "NONE", "start": 0.0, "end": 6.0,
                        "cutaways": ["media/s1.png", "media/s2.png"]},
                       {"index": 2, "text": " ".join(w[0] for w in W[15:]), "media": "media/s3.png", "mediaType": "image", "characters": "NONE", "start": 6.0, "end": 12.0,
                        "cutaways": ["media/s4.png", "media/s5.png", "media/missing.png"]}]}
json.dump(bundle, open(os.path.join(d0, "b", "bundle.json"), "w"))
z = os.path.join(d0, "b.zip")
with zipfile.ZipFile(z, "w") as zf:
    for root, _, fs in os.walk(os.path.join(d0, "b")):
        for f in fs:
            p = os.path.join(root, f); zf.write(p, os.path.relpath(p, os.path.join(d0, "b")))
env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "FAL_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "CFA_CAPTIONS")}
out_dir = os.path.join(d0, "out")
r = subprocess.run([sys.executable, os.path.join(HERE, "render.py"), z, "-o", out_dir, "--no-grok", "--no-score", "--no-whisper", "--no-ambience", "--no-sfx",
                    "--keys-env", "/dev/null", "--beat-pause", "0", "--sentence-pause", "0"], capture_output=True, text=True, env=env)
check("fast-cuts render exits 0", r.returncode == 0, (r.stdout + r.stderr)[-1500:])
if r.returncode == 0:
    rep = json.load(open(os.path.join(out_dir, "report.json")))
    sl = [s["duration"] for s in rep["shots"]]
    check("report records cut_style fast_cuts", rep.get("cut_style") == "fast_cuts")
    check("6 distinct pictures, each 1-3 s", len(rep["shots"]) == 6 and len({s["media"] for s in rep["shots"]}) == 6 and all(0.99 <= v <= 3.01 for v in sl), sl)
    check("missing cutaway dropped, not rendered", all("missing" not in str(s["media"]) for s in rep["shots"]))
    check("fast cuts gate pass", rep["motion_gate"].get("fast_cuts", {}).get("pass") is True, rep["motion_gate"].get("fast_cuts"))
    check("no captions burned (captions.ass has no Dialogue lines)", "Dialogue:" not in open(os.path.join(out_dir, "captions.ass")).read())
    check("1080p, duration == voice", rep["resolution"] == "1920x1080" and abs(rep["duration"] - 12.0) < 0.2, (rep["resolution"], rep["duration"]))
    check("v8 sharpness floor holds (>= 8 Mbps)", (rep["motion_gate"].get("sharpness") or {}).get("kbps", 0) >= 8000, rep["motion_gate"].get("sharpness"))
    # same bundle, v8 forced from the CLI: no cutaways used, v8 path
    out2 = os.path.join(d0, "out2")
    r2 = subprocess.run([sys.executable, os.path.join(HERE, "render.py"), z, "-o", out2, "--no-grok", "--no-score", "--no-whisper", "--no-ambience", "--no-sfx",
                         "--keys-env", "/dev/null", "--beat-pause", "0", "--sentence-pause", "0", "--cut-style", "v8"], capture_output=True, text=True, env=env)
    rep2 = json.load(open(os.path.join(out2, "report.json"))) if r2.returncode == 0 else {}
    check("--cut-style v8 keeps the v8 edit (no cutaways, no fast gate)", rep2.get("cut_style") == "v8" and "fast_cuts" not in rep2.get("motion_gate", {})
          and not any(s["media"] in ("media/s1.png", "media/s2.png", "media/s4.png", "media/s5.png") for s in rep2.get("shots", [])), (r2.stderr[-400:], rep2.get("cut_style")))
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
