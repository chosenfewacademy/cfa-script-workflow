"""Motion groundwork (mocked, $0): hard cuts, ~2.5 s pacing, depth parallax (model or synthetic fallback), motion gate, i2v off by default."""
import os, sys, tempfile, subprocess, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m); fails += 0 if c else 1
check(R.CALM_TARGET <= 2.8 and R.TENSE_TARGET <= 2.2 and R.SPLIT_OVER <= 3.4 and R.DRIFT_MAX <= 3.4, "pacing targets ~2-2.6 s")
sh = [{"index": i, "role": r, "transition_in": "cut", "transition_duration": 0.0, "mediaType": "image"} for i, r in enumerate(["hook", "tension", "tension", "realization", "turn"])]
R.smooth_transitions(sh)
check([x["transition_in"] for x in sh[1:3]] == ["cut", "cut"], "scene changes are hard cuts (no 0.45 s dissolves)")
check(R.STILL_MOTION == "parallax", "stills default to depth parallax")
I = R.I2V_MODELS
check(R.i2v_plan([{"media": "a.png"}], "off", 5) == ([], 0.0), "i2v off -> nothing planned")
shots = [{"media": "s%d.png" % (k % 7)} for k in range(40)]
p, e = R.i2v_plan(shots, "hailuo", 1.0)
check(e <= 1.0 and len(p) == 3 and len(set(p)) == 3, "i2v plan respects cap and dedups stills: %d clips $%.2f" % (len(p), e))
src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
with tempfile.TemporaryDirectory() as d:
    img = os.path.join(d, "s.png")
    subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1600x900:d=1", "-frames:v", "1", img])
    outs = {}
    for mot in ("zoom_in", "pan_left", "punch_in", "zoom_out"):
        o = os.path.join(d, mot + ".mp4")
        R.render_still_parallax(img, {"motion": mot, "focus": "left", "intensity": 0.05}, 1280, 720, o, 60,
                                lambda w, h: "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1" % (w, h, w, h), None)
        outs[mot] = o
    frames = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", outs["pan_left"]], capture_output=True, text=True).stdout.strip())
    check(frames == 60, "parallax writes exactly the requested frames (%d)" % frames)
    mv = {k: R.motion_gate(v)["motion_px_s"] for k, v in outs.items()}
    check(all(x >= R.GATE_MOTION_MIN for x in mv.values()), "synthetic-depth parallax moves >= %.0f px/s on every motion: %s" % (R.GATE_MOTION_MIN, mv))
    st = os.path.join(d, "static.mp4")
    subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", img, "-t", "8", "-r", "24", "-pix_fmt", "yuv420p", st])
    g = R.motion_gate(st)
    check(not g["pass"] and any("median shot" in f for f in g["fails"]) and any("motion" in f for f in g["fails"]), "gate fails a static 8 s single shot: %s" % g["fails"])
    if R.DEPTH_PY:
        dp = os.path.join(d, "dep.png")
        m = R.depth_maps([(img, dp)], d)
        check(m[img] == dp and os.path.exists(dp), "depth model runs from the service python via %s" % R.DEPTH_PY)
    old = R.DEPTH_PY; R.DEPTH_PY = None
    check(R.depth_maps([(img, os.path.join(d, "none.png"))], d)[img] is None, "no depth python -> synthetic fallback (no crash)")
    R.DEPTH_PY = "/nonexistent/python"
    check(R.depth_maps([(img, os.path.join(d, "none2.png"))], d)[img] is None, "broken depth python -> synthetic fallback")
    R.DEPTH_PY = old
    calls = []
    R.i2v_clip(img, "wan", "k", os.path.join(d, "c.mp4"), fetch=lambda m, pl: calls.append((m, "closed" in pl["prompt"])) or b"x" * 2000)
    check(calls == [("fal-ai/wan/v2.2-a14b/image-to-video", True)], "i2v uses the fal queue model with the mouth-closed idle prompt (mocked)")
print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
