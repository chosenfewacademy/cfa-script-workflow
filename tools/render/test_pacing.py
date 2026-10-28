"""Shot pacing (Oct 28): ~2 s cuts on tense beats, 3-4 s on calm beats, slow drift kept; video untouched."""
import render as R

def words_for(start, end, step=0.4):
    out, t = [], start
    while t < end - 0.2:
        out.append(["w", round(t, 3), round(t + 0.3, 3)]); t += step
    return out

def parts(shots, idx):
    return [s for s in shots if s["start"] >= shots_src[idx]["start"] - 1e-6 and s["end"] <= shots_src[idx]["end"] + 1e-6]

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " -- " + str(info)))
    fails += 0 if ok else 1

shots_src = [
    {"index": 1, "start": 0.0, "end": 8.0, "role": "hook", "text": "It is gone.", "mediaType": "image", "motion": "zoom_in"},
    {"index": 2, "start": 8.0, "end": 20.0, "role": "resolve", "text": "The shop smelled of oil, the way it had for years.", "mediaType": "image", "motion": "pan_right"},
    {"index": 3, "start": 20.0, "end": 28.0, "role": "tension", "text": "The account was empty.", "mediaType": "image", "motion": "zoom_in"},
    {"index": 4, "start": 28.0, "end": 36.0, "role": "tension", "text": "He counted the boxes.", "mediaType": "image", "motion": "zoom_in"},
    {"index": 5, "start": 36.0, "end": 46.0, "role": "turn", "text": "It is gone.", "mediaType": "video", "motion": "push_in"},
]
words = words_for(0, 46)
segs = [{"start": 28.2, "end": 35.5, "pace": "tense"}]
out = R.split_drift([dict(s) for s in shots_src], words, segs=segs)
def durs(i): return [round(s["end"] - s["start"], 2) for s in parts(out, i)]

h, c, t, m, v = durs(0), durs(1), durs(2), durs(3), durs(4)
check("tense hook split into ~2 s cuts", len(h) >= 3 and max(h) <= 2.9 and min(h) >= 1.2, h)
check("calm beat split into 3-4 s parts", len(c) >= 3 and all(2.6 <= d <= 4.3 for d in c), c)
check("crisis words ('empty') make a tension beat tense", max(t) <= 2.9 and len(t) >= 3, t)
check("tool-marked pace=tense beat gets ~2 s cuts", max(m) <= 2.9 and len(m) >= 3, m)
check("video shots are never split", v == [10.0], v)
check("every part keeps a slow drift (no static parts)", all(s.get("motion") not in (None, "static") for s in out), [s.get("motion") for s in out])
check("parts carry pace labels", {s.get("pace") for s in out} == {"tense", "calm"}, {s.get("pace") for s in out})
check("parts tile the timeline with no gaps", all(abs(out[k]["end"] - out[k + 1]["start"]) < 1e-6 for k in range(len(out) - 1)) and out[-1]["end"] == 46.0)
# stress: 300 random shots stay contiguous, no part under 1.2 s
import random
random.seed(7); st, t0 = [], 0.0
for i in range(300):
    d = random.uniform(1.0, 14.0); st.append({"index": i + 1, "start": round(t0, 3), "end": round(t0 + d, 3), "role": random.choice(["hook", "tension", "resolve", "turn"]), "text": random.choice(["calm words", "now it is gone", ""]), "mediaType": random.choice(["image", "image", "video"])}); t0 += d
o2 = R.split_drift(st, words_for(0, t0), segs=[])
check("stress: 300 shots split contiguous, every split part >= 1.2 s", all(abs(o2[k]["end"] - o2[k + 1]["start"]) < 1e-6 for k in range(len(o2) - 1)) and all(s["end"] - s["start"] >= 1.19 for s in o2 if s.get("part") == "b"), len(o2))
print("%d failed" % fails)
raise SystemExit(1 if fails else 0)
