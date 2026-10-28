#!/usr/bin/env python3
"""Offline end-to-end test for render.py ($0: synthetic assets, no Grok).

Builds a bundle the same shape the HTML exports (zip with bundle.json, media,
voiceover, SRT), renders it 16:9 and 9:16 with music ducking, and checks:
duration == voice, audio present, loudness ~ -14 LUFS, every spoken word is
covered by a caption cue at its own time, and on-screen text never says "crypto".
  python3 tools/render/test_render.py [--keep DIR]
"""
import json, os, re, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render  # noqa: E402

fails = []
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)

def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)

def make_bundle(d):
    lines = ["Jordan watched the chart jump all morning.",
             "Marcus said crypto is not a slot machine.",
             "A blockchain is a shared notebook nobody can erase.",
             "Today we open that notebook together."]
    os.makedirs(os.path.join(d, "media"))
    cols = ["0x2b4c7e", "0x7e2b4c", "0x4c7e2b"]
    for i, c in enumerate(cols):
        ff("-f", "lavfi", "-i", "testsrc2=s=1600x900:d=1,drawbox=c=%s@0.6:t=fill" % c, "-frames:v", "1",
           os.path.join(d, "media", "scene_%03d.png" % (i + 1)))
    ff("-f", "lavfi", "-i", "testsrc=s=1280x720:r=30:d=2", "-pix_fmt", "yuv420p", os.path.join(d, "media", "scene_004.mp4"))
    # fake narration: one tone burst per word, 0.32s word + 0.08s gap, 0.5s between beats
    words, t, segs, parts = [], 0.2, [], []
    for i, ln in enumerate(lines):
        st = t
        for w in ln.split():
            words.append([w, round(t, 2), round(t + 0.32, 2)])
            t += 0.40
        segs.append({"index": i + 1, "text": ln, "tag": "VIDEO" if i == 3 else "IMAGE", "characters": "",
                     "media": "media/scene_%03d.%s" % (i + 1, "mp4" if i == 3 else "png"),
                     "mediaType": "video" if i == 3 else "image", "start": round(st, 2), "end": round(t - 0.08, 2)})
        t += 0.15  # tight beat gap (~0.23s) - renderer must pad it
    total = t + 0.3
    expr = "+".join("between(t,%.2f,%.2f)" % (w[1], w[2]) for w in words)
    ff("-f", "lavfi", "-i", "sine=f=180:d=%.2f" % total, "-af", "volume='0.5*(%s)':eval=frame" % expr,
       "-c:a", "libmp3lame", "-b:a", "128k", os.path.join(d, "voiceover.mp3"))
    b = {"format": "cfa-final-edit-bundle", "version": 1, "title": "What Is a Blockchain, Really?", "episode": 3,
         "script": " ".join(lines), "voiceover": "voiceover.mp3", "srt": "beats.srt", "words": words, "segments": segs}
    z = os.path.join(d, "bundle.zip")
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("bundle.json", json.dumps(b))
        for root, _, files in os.walk(d):
            for f in files:
                if f != "bundle.zip":
                    p = os.path.join(root, f)
                    zf.write(p, os.path.relpath(p, d))
    return z, words

def verify(out, words, vertical):
    rep = json.load(open(os.path.join(out, "report.json")))
    tag = "vertical" if vertical else "16:9"
    check(abs(rep["duration"] - rep["voice_duration"]) < 0.1, "%s duration %.2f == voice %.2f" % (tag, rep["duration"], rep["voice_duration"]))
    check(rep["audio_streams"] == 1, "%s audio stream present" % tag)
    check(rep["resolution"] == ("1080x1920" if vertical else "1920x1080"), "%s resolution %s" % (tag, rep["resolution"]))
    check(rep["lufs"] is not None and abs(rep["lufs"] + 14) < 1.0, "%s loudness %s LUFS" % (tag, rep["lufs"]))
    cues = rep["caption_cues"]
    # words as shown on screen, timed with the padded timestamps the renderer used
    shown = render.screen_tokens([w[0] for w in words])
    pw = rep["padded_words"]
    miss = [w[0] for w, sh in zip(pw, shown) if not any(c["start"] - 0.01 <= (w[1] + w[2]) / 2 <= c["end"] + 0.01
                                           and render.norm(sh.split()[0]) in [render.norm(x) for x in c["text"].split()] for c in cues)]
    check(not miss, "%s every word captioned at its spoken time (missing: %s)" % (tag, miss))
    ass = open(os.path.join(out, "captions.ass")).read()
    check(not re.search(r"crypto", ass.split("[Events]")[1], re.I), "%s no 'crypto' in on-screen text" % tag)
    check(os.path.getsize(os.path.join(out, "thumbnail.jpg")) > 10000, "%s thumbnail written" % tag)

def main():
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    d = keep or tempfile.mkdtemp(prefix="cfa-render-test-")
    os.makedirs(d, exist_ok=True)
    z, words = make_bundle(os.path.join(d, "src"))
    music = os.path.join(d, "music.wav")
    ff("-f", "lavfi", "-i", "sine=f=440:d=5", music)
    for vertical in (False, True):
        out = os.path.join(d, "out_v" if vertical else "out_h")
        cmd = [sys.executable, os.path.join(HERE, "render.py"), z, "-o", out, "--no-grok", "--no-score", "--no-whisper", "--no-ambience", "--keys-env", "/dev/null", "--music", music]
        if vertical:
            cmd += ["--vertical", "--caption-style", "boxed"]
        subprocess.run(cmd, check=True)
        verify(out, words, vertical)
    # pacing: pauses, min hold, crossfades, phrase captions
    rep = json.load(open(os.path.join(d, "out_h", "report.json")))
    check(rep["pauses_added"] > 0.5 and abs(rep["duration"] - rep["voice_raw_duration"] - rep["pauses_added"]) < 0.15,
          "pauses padded into voice (+%.2fs) and video follows" % rep["pauses_added"])
    check(rep["min_shot"] >= 1.3, "minimum shot hold %.2fs >= 1.3s" % rep["min_shot"])
    check(sum(1 for s in rep["shots"] if s["part"] != "b") >= 3, "each beat keeps its own picture where it can (%d shots)" % len(rep["shots"]))
    check(all(s["motion"] != "static" for s in rep["shots"]), "motion on every shot (videos push in)")
    check(rep["arc"] and rep["arc"]["turning_point_shot"] > rep["arc"]["hook_end_shot"], "story arc: hook then turning point %r" % rep["arc"])
    check(rep["shots"][0]["transition"] == "cut" and rep["shots"][0]["role"] == "hook", "cold open on a hook shot")
    kinds = [e[0] for e in rep["sfx_events"]]
    check("riser" in kinds and "impact" in kinds and kinds.count("whoosh") <= 5, "sound design: riser + impact on the turn, sparse whooshes %r" % kinds)
    cues = rep["caption_cues"]
    wpc = sum(len(c["text"].split()) for c in cues) / len(cues)
    check(1.5 <= wpc <= 5, "punchy captions: %.1f words per cue" % wpc)
    ass = open(os.path.join(d, "out_h", "captions.ass")).read()
    check("\\fscx118" in ass, "keyword emphasis pops in captions")
    title = [l for l in ass.splitlines() if ",Title," in l][0]
    check(not title.split(",")[1].startswith("0:00:00.00"), "title card lands after the hook, not over it")
    ws = json.load(zipfile.ZipFile(z).open("bundle.json"))["words"]
    import shutil
    wk = tempfile.mkdtemp()
    sg = [dict(x) for x in json.load(zipfile.ZipFile(z).open("bundle.json"))["segments"]]
    zipfile.ZipFile(z).extract("voiceover.mp3", wk)
    _, nw, ins, add = render.add_pauses(os.path.join(wk, "voiceover.mp3"), ws, sg, wk, 0.6, 0.45)
    gaps = [sg[i + 1]["start"] - sg[i]["end"] for i in range(len(sg) - 1)]
    check(all(g >= 0.59 for g in gaps), "beat gaps after padding >= 0.6s: %s" % [round(g, 2) for g in gaps])
    check(all(nw[i][1] >= ws[i][1] for i in range(len(ws))), "word timestamps shifted forward, order kept")
    shutil.rmtree(wk, ignore_errors=True)
    # grammar-aware "crypto" swap
    for src, want in [("Crypto isn't a slot machine.", "Digital assets aren't a slot machine."),
                      ("He bought a crypto yesterday.", "He bought a digital asset yesterday."),
                      ("Open a crypto wallet today", "Open a digital asset wallet today"),
                      ("crypto is volatile", "digital assets are volatile"),
                      ("Cryptocurrencies are new.", "Digital assets are new."),
                      ("I like crypto.", "I like digital assets.")]:
        check(render.screen_text(src) == want, "swap: %r -> %r (got %r)" % (src, want, render.screen_text(src)))
    # story-aware grouping: a short Jordan still next to a concept clip keeps its own shot when possible
    g_segs = [{"index": 1, "text": "Jordan sits.", "characters": "JORDAN", "media": "a.png", "mediaType": "image"},
              {"index": 2, "text": "A chart.", "characters": "NONE", "media": "b.png", "mediaType": "image"},
              {"index": 3, "text": "Hands move.", "characters": "NONE", "media": "c.mp4", "mediaType": "video"},
              {"index": 4, "text": "Jordan writes.", "characters": "JORDAN", "media": "d.png", "mediaType": "image"}]
    g = render.group_shots(g_segs, [0, 3.0, 4.0, 8.0, 12.0], 3.75)
    check([x["beats"] for x in g] == [[1, 2], [3], [4]] and g[0]["media"] == "a.png" and g[1]["mediaType"] == "video",
          "grouping keeps character stills and clips, drops the concept still (%r)" % [(x["beats"], x["media"]) for x in g])
    check(all(x["end"] - x["start"] >= 3.75 for x in g), "grouping still honours the minimum hold")
    # validator: garbage Grok output must fall back, partial output coerced onto real timings
    b = json.load(zipfile.ZipFile(z).open("bundle.json"))
    segs = b["segments"]
    cuts = render.cut_points(segs, 12.0)
    shots = render.group_shots(segs, cuts)
    try:
        render.validate_edl({"shots": "nope"}, b, shots); check(False, "garbage EDL rejected")
    except ValueError:
        check(True, "garbage EDL rejected")
    e, _ = render.validate_edl({"shots": [{"index": i + 1, "motion": "spin", "transition_in": "explode", "transition_duration": 0.2,
                                            "intensity": 0.5, "duration": 99} for i in range(len(shots))],
                                "title_card": {"enabled": True, "text": "Crypto 101"}}, b, shots)
    check(all(s["motion"] in render.MOTIONS and s["transition_in"] in render.TRANSITIONS for s in e["shots"]), "bad motions/transitions coerced")
    check(all(s["intensity"] <= render.KB_MAX for s in e["shots"]), "Ken Burns intensity capped (subtle)")
    check(all(s["transition_in"] == "cut" or s["transition_duration"] >= 0.2 for s in e["shots"][1:]), "transition durations clamped to their type")
    # arc detection + punch-in split
    sh = [{"index": i + 1, "start": i * 5.0, "end": i * 5.0 + 5.0, "text": t, "mediaType": "image", "media": "x.png", "beats": [i + 1]}
          for i, t in enumerate(["Jordan froze.", "Dee said money.", "Banks failed.", "People worried.", "That's why Satoshi wrote it.", "He finally understood.", "Next time."])]
    arc = render.detect_arc(sh)
    check(arc["hook_end_shot"] == 1 and arc["turning_point_shot"] == 5 and arc["realization_shots"] == [6, 7], "turning point found from the line (%r)" % arc)
    fb = render.fallback_edl({"title": "T"}, sh)
    ev, _ = render.validate_edl(fb, {"title": "T"}, sh)
    roles = [x["role"] for x in ev["shots"]]
    check(roles == ["hook", "tension", "tension", "tension", "turn", "realization", "realization"], "roles %r" % roles)
    check(ev["shots"][4]["transition_in"] == "whip" and ev["shots"][5]["transition_in"] == "dissolve" and not ev["shots"][5]["punch_in"], "turn whips in, realization dissolves and holds")
    wds = [["w", 0.2 + 0.4 * k, 0.5 + 0.4 * k] for k in range(80)]
    sp = render.split_punch_ins(ev["shots"], wds)
    check(len(sp) > len(ev["shots"]) and any(x["motion"] == "punch_in" and x["transition_in"] == "cut" for x in sp), "long tension stills split into wide -> punch-in")
    check(abs(sum(x["duration"] for x in sp) - 35.0) < 0.01, "splitting keeps total timing")
    check(render.pick_emphasis("Marcus had underlined October 2008 on the printout.")[:1] == ["2008"], "emphasis picks numbers first")
    check(abs(sum(s["duration"] for s in e["shots"]) - 12.0) < 1e-6, "durations locked to voice, Grok durations ignored")
    check("crypto" not in e["title_card"]["text"].lower(), "card text rewritten to digital assets")
    # audit fixes: baked-in bars, missing opening scene, missing music file
    bd = tempfile.mkdtemp(prefix="cfa-bars-")
    pb = os.path.join(bd, "pillar.png"); fl = os.path.join(bd, "full.png")
    ff("-f", "lavfi", "-i", "testsrc2=s=848x768:d=1", "-vf", "pad=1360:768:256:0:black", "-frames:v", "1", pb)
    ff("-f", "lavfi", "-i", "testsrc2=s=1360x768:d=1", "-frames:v", "1", fl)
    bx = render.detect_bars(pb, "image")
    check(bx is not None and abs(bx[0] - 848) <= 8 and render.detect_bars(fl, "image") is None, "baked-in pillarbox detected, full frame left alone (%r)" % (bx,))
    o = os.path.join(bd, "s.mp4")
    render.render_shot(pb, "image", {"motion": "zoom_in", "intensity": 0.05}, 640, 360, o, 10)
    ff("-i", o, "-frames:v", "1", "-vf", "crop=20:200:0:80", os.path.join(bd, "edge.png"))
    ylo = subprocess.run(["ffmpeg", "-v", "info", "-i", os.path.join(bd, "edge.png"), "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"], capture_output=True, text=True).stderr
    yv = float((re.findall(r"YAVG=([\d.]+)", ylo) or ["0"])[-1])
    check(yv > 30, "pillarbox replaced by a blurred fill, not black edges (edge luma %.0f)" % yv)
    src2 = os.path.join(d, "src2"); shutil.copytree(os.path.join(d, "src"), src2)
    os.remove(os.path.join(src2, "bundle.zip"))
    bj = json.load(open(os.path.join(src2, "bundle.json"))) if os.path.exists(os.path.join(src2, "bundle.json")) else json.load(zipfile.ZipFile(z).open("bundle.json"))
    bj["segments"][0]["media"] = None; bj["segments"][0]["mediaType"] = ""
    json.dump(bj, open(os.path.join(src2, "bundle.json"), "w"))
    out3 = os.path.join(d, "out_miss")
    r3 = subprocess.run([sys.executable, os.path.join(HERE, "render.py"), src2, "-o", out3, "--no-grok", "--no-score", "--no-whisper", "--no-ambience", "--keys-env", "/dev/null", "--music", os.path.join(d, "nope.wav")], capture_output=True, text=True)
    check(r3.returncode == 0 and "without a music bed" in (r3.stdout + r3.stderr), "missing music file: warns and renders without music")
    if r3.returncode == 0:
        ff("-ss", "0.3", "-i", os.path.join(out3, "final.mp4"), "-frames:v", "1", "-vf", "scale=64:36", os.path.join(bd, "first.png"))
        so = subprocess.run(["ffmpeg", "-v", "info", "-i", os.path.join(bd, "first.png"), "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"], capture_output=True, text=True).stderr
        check(float((re.findall(r"YAVG=([\d.]+)", so) or ["0"])[-1]) > 40, "missing opening scene borrows the next visual instead of a blank frame")
    # vertical reframing follows the subject (hint path, no network)
    sys.path.insert(0, HERE); import render as R
    R.SUBJECT_KEY = None
    lp = os.path.join(d, "subj.png")
    ff("-f", "lavfi", "-i", "color=c=black:s=640x360", "-vf", "drawbox=x=40:y=120:w=100:h=120:c=white:t=fill", "-frames:v", "1", lp)
    vo = os.path.join(d, "subj.mp4")
    R.render_shot(lp, "image", {"motion": "zoom_in", "intensity": 0.03, "subject": {"cx": 0.14, "cy": 0.5}}, 180, 320, vo, 6)
    ff("-i", vo, "-frames:v", "1", "-vf", "crop=60:100:60:110,scale=8:8", os.path.join(d, "subj_c.png"))
    so = subprocess.run(["ffmpeg", "-v", "info", "-i", os.path.join(d, "subj_c.png"), "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"], capture_output=True, text=True).stderr
    check(float((re.findall(r"YAVG=([\d.]+)", so) or ["0"])[-1]) > 150, "vertical crop centres on the located subject (off-centre subject stays in frame)")
    check(R.subject_center("/nonexistent.png", "image") == (0.5, 0.45), "no key -> centre fallback")
    # narrator vs character caption style
    words = [(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate("Bill watched the market fall. Wait what happened".split())]
    segs = [{"index": 0, "speaker": "NARRATOR", "start": 0.0, "end": 2.45}, {"index": 1, "speaker": "JORDAN", "start": 2.5, "end": 4.5}]
    edl = {"caption_style": {"preset": "bold_pop", "position": "lower_third", "highlight_color": "#FFD400", "words_per_caption": 4}, "shots": [{"start": 0, "end": 5, "emphasis": [], "beats": [0, 1], "duration": 5}], "title_card": {"enabled": False}, "end_card": {"enabled": False}}
    ap = os.path.join(d, "narr.ass")
    cues = R.build_ass(words, segs, edl, 1080, 1920, 5.0, ap)
    ass = open(ap).read()
    check("Style: Narr," in ass and ",Narr,," in ass and ",Cap,," in ass, "narrator lines use the Narr caption style, characters use Cap")
    check(any(c.get("speaker") == "NARRATOR" for c in cues) and any(c.get("speaker") == "JORDAN" for c in cues), "cues carry speaker")
    # motion QA: a frozen still shot then a moving shot with a hard colour jump
    mv = os.path.join(d, "mqa.mp4")
    ff("-f", "lavfi", "-i", "color=c=black:s=160x90:d=2:r=24", "-f", "lavfi", "-i", "testsrc=s=160x90:d=2:r=24",
       "-filter_complex", "[1:v]scroll=h=0.03[m];[0:v][m]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-pix_fmt", "yuv420p", mv)
    q = R.motion_qa(mv, [{"index": 0, "start": 0.0, "duration": 2.0, "mediaType": "image"}, {"index": 1, "start": 2.0, "duration": 2.0, "mediaType": "video"}])
    check([f["shot"] for f in q["frozen"]] == [0], "motion QA flags only the frozen shot %s" % q.get("motion"))
    check(len(q["jarring_cuts"]) == 1 and q["jarring_cuts"][0]["after_shot"] == 0, "motion QA flags the black-to-colour-bars cut %s" % q["jarring_cuts"])
    check([w[0] for w in R.strip_tag_words([["Wait", 0, 1], ["[sighs]", 1, 2], ["[short", 2, 3], ["pause]", 3, 4], ["okay.", 4, 5]])] == ["Wait", "okay."], "v4 audio tags never reach captions")
    # Resilia: drift split, per-beat grades, per-beat music cues, montage
    lsh = [{"index": 1, "start": 0.0, "end": 11.0, "duration": 11.0, "mediaType": "image", "media": "x.png", "motion": "zoom_in", "intensity": 0.05, "role": "tension", "transition_in": "dissolve", "transition_duration": 0.5, "part": ""},
           {"index": 2, "start": 11.0, "end": 19.0, "duration": 8.0, "mediaType": "video", "media": "v.mp4", "motion": "push_in", "intensity": 0.04, "role": "turn", "transition_in": "whip", "transition_duration": 0.3, "part": ""},
           {"index": 3, "start": 19.0, "end": 21.0, "duration": 2.0, "mediaType": "image", "media": "y.png", "motion": "pan_left", "intensity": 0.05, "role": "resolve", "transition_in": "dissolve", "transition_duration": 0.5, "part": ""}]
    wd = [["w", 0.1 + 0.5 * k, 0.45 + 0.5 * k] for k in range(42)]
    ds = R.split_drift([dict(x) for x in lsh], wd)
    parts = [x for x in ds if x["media"] == "x.png"]
    check(len(parts) >= 3 and all(1.9 <= p["duration"] <= 3.3 for p in parts), "11 s still split into ~2-3 s parts (fix 5) %r" % [p["duration"] for p in parts])
    check(abs(sum(x["duration"] for x in ds) - 21.0) < 0.01 and [x["index"] for x in ds] == list(range(1, len(ds) + 1)), "drift split keeps total timing and reindexes")
    check(all(p["motion"] not in ("static", None) for p in parts) and any(p["motion"] == "punch_in" and p.get("focus") in ("left", "right") for p in parts), "every part drifts; punch-ins are off-centre")
    check(all(p["transition_in"] == "cut" for p in parts[1:]) and parts[0]["transition_in"] == "dissolve", "inside a split: cuts; into it: the planned transition")
    check(sum(1 for x in ds if x["media"] == "v.mp4") == 1 and sum(1 for x in ds if x["media"] == "y.png") == 1, "video and short shots are not split")
    check(R.split_drift([], wd) == [] and len(R.split_drift([dict(lsh[0])], [])) >= 3, "edge: no shots / no word gaps")
    sm = R.smooth_transitions([dict(x) for x in ds])
    check([x["transition_in"] for x in sm if x["role"] == "turn"] == ["whip"] and all(x["transition_in"] != "whip" for x in sm if x["role"] != "turn"), "whips only into the reveal")
    gr = R.assign_grades([{"role": r} for r in ("hook", "tension", "montage", "turn", "realization", "resolve", None)])
    check([g["grade"] for g in gr] == ["cool_low", "sterile", "sterile", "golden", "golden", "golden", ""], "per-beat grades: cool low -> sterile -> golden")
    check(R.grade_vf({"grade": "golden"}).startswith(",eq=") and R.grade_vf({}) == "" and R.assign_grades([{"role": "turn"}], False)[0]["grade"] == "", "grade filter / off switch")
    gd = tempfile.mkdtemp(prefix="cfa-grade-")
    gsrc = os.path.join(gd, "g.png"); ff("-f", "lavfi", "-i", "color=c=0x808080:s=320x180", "-frames:v", "1", gsrc)
    means = {}
    for g in ("cool_low", "golden"):
        o = os.path.join(gd, g + ".png"); v = os.path.join(gd, g + ".mp4")
        R.render_shot(gsrc, "image", {"motion": "zoom_in", "intensity": 0.03, "grade": g}, 160, 90, v, 4)
        ff("-i", v, "-frames:v", "1", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", o)
        means[g] = list(open(o, "rb").read()[:3])
    ok = means["golden"][0] - means["golden"][2] > means["cool_low"][0] - means["cool_low"][2] + 6
    check(bool(ok), "rendered grades differ: golden warmer than cool %r" % means)
    mp = R.music_plan(90.0, {"hook_end": 6.0, "turn": 60.0}, "cinematic")
    names = [c["text"] for c in mp]
    inst = [c["positive_styles"][1] for c in mp]
    check(names[0] == "[Cold open cue]" and "[Triumph cue]" in names and len(set(inst)) == len(inst), "per-beat music cues with distinct instruments %r" % inst)
    check(abs(sum(c["duration_ms"] for c in mp) / 1000.0 - 91.5) < 0.05, "cue durations cover the episode")
    check(all(c["duration_ms"] >= 3000 for c in R.music_plan(10.0, {"hook_end": 1.0, "turn": 8.0}, "lofi")), "short episode: no sub-3 s cues")
    segm = [{"speaker": "JORDAN", "start": 0, "text": "Gone."}, {"speaker": "NARRATOR", "start": 30, "text": "Day one, nothing."}, {"speaker": "NARRATOR", "start": 34, "text": "Day two, a reply."},
            {"speaker": "NARRATOR", "start": 38, "text": "By day three, twelve confirmations."}, {"speaker": "MARCUS", "start": 42, "text": "See?"}]
    check(len(R.detect_montage(segm, 100.0)) == 3 and R.detect_montage(segm[:2], 100.0) == [], "montage = run of counting narrator lines")
    msh = R.smooth_transitions([{"role": "tension", "transition_in": "dissolve", "transition_duration": .5, "part": ""}, {"role": "montage", "transition_in": "dissolve", "transition_duration": .5, "part": ""}])
    check(msh[1]["transition_in"] == "cut", "montage beats hard-cut")
    print("\n%d failure(s)" % len(fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
