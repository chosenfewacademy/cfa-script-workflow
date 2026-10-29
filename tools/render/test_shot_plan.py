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
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
