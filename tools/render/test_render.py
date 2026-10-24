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
        cmd = [sys.executable, os.path.join(HERE, "render.py"), z, "-o", out, "--no-grok", "--music", music]
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
    print("\n%d failure(s)" % len(fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
