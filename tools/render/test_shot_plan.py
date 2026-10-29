"""Phrase shot plan: motivated motion, story-led transitions, J-cuts, cut-on-movement easing, similarity + phrase gates."""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, "" if ok else x); ok or fails.append(n)
segs = [{"index": 1, "start": 0.0, "planMotion": "hold", "planLink": "cut", "planDir": 1},
        {"index": 2, "start": 3.0, "planMotion": "track", "planLink": "cut", "planDir": 1},
        {"index": 3, "start": 6.0, "planMotion": "track", "planLink": "push_link", "planDir": 1},
        {"index": 4, "start": 9.0, "planMotion": "hold", "planLink": "jcut", "planDir": 1},
        {"index": 5, "start": 12.0, "planMotion": "push_in", "planLink": "whip", "planDir": -1},
        {"index": 6, "start": 15.0, "planMotion": "track", "planLink": "time_jump", "planDir": -1}]
shots = [{"beats": [k + 1], "start": k * 3.0, "end": k * 3.0 + 3.0, "duration": 3.0, "mediaType": "image", "motion": "zoom_in"} for k in range(6)]
R.apply_shot_plan(shots, segs)
check("quote holds still", shots[0]["motion"] == "static" and shots[3]["motion"] == "static", [x["motion"] for x in shots])
check("push_link pushes the previous shot into the detail", shots[1]["motion"] == "zoom_in")
check("track follows the camera direction, flips after BUT", shots[5]["motion"] == "pan_left" and shots[5]["_dir"] == -1)
check("realization pushes in", shots[4]["motion"] == "zoom_in")
check("transitions from the story link", [x.get("transition_in") for x in shots[1:]] == ["cut", "cut", "cut", "whip", "dissolve"], [x.get("transition_in") for x in shots])
check("J-cut: picture cut lands after the line starts", abs(shots[3]["start"] - 9.2) < 1e-6 and abs(shots[2]["end"] - 9.2) < 1e-6)
sn = [{"beats": [1], "start": 0, "end": 5.35, "duration": 5.35, "mediaType": "image"}, {"beats": [2], "start": 5.35, "end": 11, "duration": 5.65, "mediaType": "image"}]
R.apply_shot_plan(sn, [{"index": 1, "start": 0}, {"index": 2, "start": 5.66}])
check("cut snaps to the phrase's first word", abs(sn[1]["start"] - 5.66) < 1e-6 and abs(sn[0]["end"] - 5.66) < 1e-6 and R.phrase_alignment(sn)["max_offset_s"] < 1e-6)
check("phrase alignment within limit (J lead allowed)", R.phrase_alignment(shots)["pass"] and R.phrase_alignment(shots)["max_offset_s"] <= 0.21)
check("motion carries across cuts (cut on movement)", shots[1]["_carry"] and shots[2]["_carry_in"])
e = [R._ease(t / 10.0, True, True) for t in range(11)]
check("carry easing leaves the cut moving", (e[10] - e[9]) > 0.06 and (e[1] - e[0]) > 0.06, e)
e2 = [R._ease(t / 10.0) for t in range(11)]
check("plain ease rests at both ends", (e2[10] - e2[9]) < 0.03)
# similarity gate on real frames
d = tempfile.mkdtemp()
def clip(name, src):
    out = os.path.join(d, name)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, "-t", "2", "-r", "24", "-pix_fmt", "yuv420p", out], check=True); return out
a = clip("a.mp4", "testsrc2=s=640x360")
b = clip("b.mp4", "mandelbrot=s=640x360")
cat = os.path.join(d, "cat.mp4"); lst = os.path.join(d, "l.txt")
open(lst, "w").write("file '%s'\nfile '%s'\nfile '%s'\n" % (a, a, b))
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", cat], check=True)
sh = [{"start": 0, "duration": 2, "media": "m1"}, {"start": 2, "duration": 2, "media": "m2"}, {"start": 4, "duration": 2, "media": "m3"}]
g = R.similarity_gate(cat, sh)
check("near-identical consecutive shots fail the similarity gate", not g["pass"] and g["fails"] == [1], g)
sh[1]["plan_link"] = "match"
check("an intentional match cut is allowed", R.similarity_gate(cat, sh)["pass"])
sh[1]["plan_link"] = None; sh[2]["media"] = "m2"
check("same image reused in a row is a re-angle", 2 in R.similarity_gate(cat, sh)["fails"])
# one character per shot + action shots get i2v, within cap
sg = [{"index": 1, "characters": "JORDAN", "oneChar": "JORDAN"}, {"index": 2, "characters": "BOTH", "oneChar": None}]
check("one-character gate flags a two-person shot", R.one_character_gate(sg)["fails"] == [2])
check("one-character gate ignores beats outside the clip", R.one_character_gate(sg, {1})["pass"])
acts = [{"media": "a.png", "mediaType": "image", "plan_shot": "action", "one_char": "JORDAN", "line": "Jordan slides the card into the drawer"},
        {"media": "b.png", "mediaType": "image", "plan_shot": "still"},
        {"media": "c.png", "mediaType": "image", "plan_shot": "action", "one_char": "MARCUS"}, {"media": "e.png", "mediaType": "image", "plan_shot": "action"}]
pk, est = R.action_i2v_plan(acts, "hailuo", 0.30)
check("only action lines animate, capped", [x["media"] for x in pk] == ["a.png"] and est == 0.27 and acts[2].get("i2v_skipped_cost"), (pk, est))
pr = R.action_prompt(acts[0])
check("action prompt: acts the line, one character, mouth closed", "slides the card" in pr and "Only Jordan" in pr and "Mouth stays closed" in pr, pr)
got = {}
R.i2v_clip(__file__, "hailuo", "k", os.path.join(d, "o.mp4"), fetch=lambda m, p: got.update(p) or b"x", prompt=pr)
check("action with no character on screen never animates", "e.png" not in [x["media"] for x in R.action_i2v_plan(acts, "hailuo", 9)[0]])
check("i2v sends the action prompt", got.get("prompt") == pr)
check("reverse shot is a hard cut", R.PLAN_TRANS["reverse"] == ("cut", 0.0))
import numpy as np
dm = np.tile(np.linspace(0, 1, 640, dtype=np.float32), (360, 1)); img = np.full((360, 640, 3), 128, np.uint8)
st = {}
for _ in R.parallax_frames(img, dm, 320, 180, 24 * 6, "zoom_in", (0.5, 0.5), 1.0, 1, st, (True, True)): pass
check("distortion guard keeps a long push-in inside the stretch gate", st["stretch"] <= R.GATE_STRETCH_MAX, st)
# reference i2v: Jordan's sheet rides as an element, duration covers the shot, per-second cost
pl = R.i2v_payload("kling-ref", "data:x", "acts", "https://ref/jordan.png", 4.2, "Jordan")
check("kling-ref passes the reference sheet and the still as start frame", pl["elements"][0]["frontal_image_url"] == "https://ref/jordan.png" and pl["image_urls"] == ["data:x"] and "@Element1" in pl["prompt"] and "start frame" in pl["prompt"] and pl["duration"] == "5", pl)
check("kling-ref cost is per second", abs(R.i2v_cost("kling-ref", 4.2) - 0.42) < 1e-9 and abs(R.i2v_cost("kling-ref", 2.5) - 0.252) < 1e-9 and R.i2v_cost("hailuo") == 0.27)
pk2, est2 = R.action_i2v_plan([dict(acts[0], duration=3.0)], "kling-ref", 0.3)
check("action plan uses the per-clip cost against the cap", len(pk2) == 1 and abs(est2 - 0.25) < 0.01, (pk2, est2))
ok1 = R.i2v_frame_check("x.mp4", "k", "https://ref", 1, ask=lambda m: {"frames": [{"people": 1, "text": [], "quality": 9}] * 3, "same_character": 9})
bad = R.i2v_frame_check("x.mp4", "k", "https://ref", 1, ask=lambda m: {"frames": [{"people": 2, "text": []}, {"people": 1, "text": ["Write it down"], "quality": 9}, {"people": 1, "quality": 4, "defects": ["melted hand"]}], "same_character": 3})
check("i2v frame check passes a clean one-person clip", ok1["ok"], ok1)
check("i2v frame check rejects a second person, on-screen text, distortion and face drift", not bad["ok"] and len(bad["why"]) == 4, bad)
check("i2v prompt forbids text and keeps named others off-screen", "no text, captions" in pr and "off-screen" in pr, pr)
# zero on-screen text by default: no captions, overlays, title or end card burned in; text gate reads the frames
R.CAPTIONS_ON = False
ap = os.path.join(d, "c.ass")
edl0 = {"caption_style": {"preset": "bold_pop", "words_per_caption": 3, "highlight_color": "#FFD23F", "position": "bottom"},
        "shots": [{"start": 0, "end": 6, "emphasis": []}], "title_card": {"enabled": True, "text": "T", "duration": 3}, "end_card": {"enabled": True, "text": "Subscribe", "duration": 3}}
R.build_ass([["Write", 0.0, 0.4], ["it", 0.4, 0.6], ["down", 0.6, 1.0]], [{"start": 0.0, "end": 2.0, "overlay": "Write it down. Keep it safe."}], edl0, 1920, 1080, 6.0, ap)
check("no captions, overlays, title or end card by default", "Dialogue:" not in open(ap).read())
tg1 = R.text_gate("x", "k", ask=lambda m: {"items": [{"tile": 3, "text": "Write it down", "kind": "overlay"}]})
tg2 = R.text_gate("x", "k", ask=lambda m: {"items": [{"tile": 2, "text": "PAID", "kind": "scene", "spelled_ok": True}]}, allow_scene=True)
tg3 = R.text_gate("x", "k", ask=lambda m: {"items": [{"tile": 2, "text": "PIAD", "kind": "scene", "spelled_ok": False}]}, allow_scene=True)
tg4 = R.text_gate("x", "k", ask=lambda m: {"items": []})
check("text gate: overlay text fails, minimal correctly spelled scene text passes, garbled fails, clean passes", not tg1["pass"] and tg2["pass"] and not tg3["pass"] and tg4["pass"], [tg1, tg2, tg3])

# fal network errors retry with backoff; a POST retries only when it never reached fal
import requests as _rq
_n = {"k": 0}
def _flaky():
    _n["k"] += 1
    if _n["k"] < 3:
        raise _rq.exceptions.ConnectionError("HTTPSConnectionPool: Max retries exceeded (NewConnectionError)")
    return "ok"
_sl = []
check("net_retry: connection errors retry with backoff then succeed", R.net_retry(_flaky, sleep=_sl.append) == "ok" and _sl == [2.0, 4.0], _sl)
def _rt():
    raise _rq.exceptions.ReadTimeout("read timed out")
try:
    R.net_retry(_rt, post=True, sleep=lambda x: None); _ok = False
except _rq.exceptions.ReadTimeout:
    _ok = True
check("net_retry: a POST that may have reached fal is not re-sent (no double charge)", _ok)
def _bad():
    raise ValueError("bad json")
try:
    R.net_retry(_bad, sleep=lambda x: None); _ok = False
except ValueError:
    _ok = True
check("net_retry: non-network errors are not retried", _ok)

print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
