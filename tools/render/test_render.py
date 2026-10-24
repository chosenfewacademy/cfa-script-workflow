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
        t += 0.5
    total = t
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
    miss = [w[0] for w in words if not any(c["start"] - 0.01 <= (w[1] + w[2]) / 2 <= c["end"] + 0.01
                                           and render.norm(render.screen_text(w[0]).split()[0]) in [render.norm(x) for x in c["text"].split()] for c in cues)]
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
    check(render.screen_text("Crypto and cryptocurrencies") == "Digital assets and digital assets", "screen_text rewrite")
    for vertical in (False, True):
        out = os.path.join(d, "out_v" if vertical else "out_h")
        cmd = [sys.executable, os.path.join(HERE, "render.py"), z, "-o", out, "--no-grok", "--music", music]
        if vertical:
            cmd += ["--vertical", "--caption-style", "boxed"]
        subprocess.run(cmd, check=True)
        verify(out, words, vertical)
    # validator: garbage Grok output must fall back, partial output must be coerced onto real timings
    b = json.load(zipfile.ZipFile(z).open("bundle.json"))
    segs = b["segments"]
    cuts = render.cut_points(segs, 12.0)
    try:
        render.validate_edl({"shots": "nope"}, b, segs, cuts); check(False, "garbage EDL rejected")
    except ValueError:
        check(True, "garbage EDL rejected")
    e, _ = render.validate_edl({"shots": [{"index": i + 1, "motion": "spin", "transition_in": "explode", "transition_duration": 9,
                                            "duration": 99} for i in range(4)],
                                "title_card": {"enabled": True, "text": "Crypto 101"}}, b, segs, cuts)
    check(all(s["motion"] in render.MOTIONS and s["transition_in"] in render.TRANSITIONS for s in e["shots"]), "bad motions/transitions coerced")
    check(abs(sum(s["duration"] for s in e["shots"]) - 12.0) < 1e-6, "durations locked to voice, Grok durations ignored")
    check("crypto" not in e["title_card"]["text"].lower(), "card text rewritten to digital assets")
    print("\n%d failure(s)" % len(fails))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
