#!/usr/bin/env python3
"""CFA final-edit renderer.

Turns a bundle exported by CFA_Script_Workflow.html ("Export for final edit")
into a finished, edited MP4 plus a thumbnail.

  python3 tools/render/render.py BUNDLE.zip -o out/ [--vertical] [--music bed.mp3]

Pipeline: unpack -> Grok (grok-4.3, JSON) edit decision list -> validate against
the real voiceover timings (deterministic fallback) -> ffmpeg render (Ken Burns
stills, conformed clips, crossfades, burned-in word-timed captions, optional
ducked music, -14 LUFS) -> final.mp4 + thumbnail.jpg + edl.json + report.json.

Standard library only. Needs ffmpeg/ffprobe with libass (apt install ffmpeg).
XAI_API_KEY is read from the environment (or --keys-env FILE); it is never written
anywhere.
"""
import argparse, json, math, os, re, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile

FPS = 30
XAI_URL = "https://api.x.ai/v1/chat/completions"
MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"]
TRANSITIONS = {"cut": None, "dissolve": "fade", "fadeblack": "fadeblack"}  # gentle only
CAPTION_STYLES = ["bold_pop", "clean_lower", "boxed"]
FONT = "Montserrat"


def log(*a):
    print("[render]", *a, flush=True)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.stderr.write(r.stderr[-4000:])
        raise RuntimeError("command failed: " + " ".join(map(str, cmd[:6])) + " ...")
    return r


def ensure_ffmpeg():
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    log("ffmpeg missing; installing with apt")
    pre = [] if os.geteuid() == 0 else ["sudo"]
    subprocess.run(pre + ["apt-get", "update", "-qq"], check=True)
    subprocess.run(pre + ["apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    return json.loads(r.stdout)


def media_duration(path):
    try:
        return float(probe(path)["format"]["duration"])
    except Exception:
        return 0.0


# ── on-screen wording ────────────────────────────────────────────────────────
# Narration should already say "digital assets" (the script prompts enforce it).
# If a "crypto" word slips through, captions swap it *with grammar fixes*:
#   crypto is/was/has/isn't...  -> digital assets are/were/have/aren't...
#   a/an crypto(currency)       -> a digital asset
#   crypto wallet / exchange    -> digital asset wallet / exchange
#   crypto, cryptos, cryptocurrencies (noun) -> digital assets
_CRYPTO = re.compile(r"^(crypto|cryptos|cryptocurrency|cryptocurrencies)([^\w]*)$", re.I)
_VERB_FIX = {"is": "are", "was": "were", "has": "have", "isn't": "aren't", "wasn't": "weren't", "hasn't": "haven't",
             "does": "do", "doesn't": "don't", "isn’t": "aren’t", "wasn’t": "weren’t", "doesn’t": "don’t", "hasn’t": "haven’t"}
_NOUN_NEXT = set("and or but in on for to of with is are was were has have does do isn't aren't doesn't "
                 "can will could would should might may just really itself so that than as at by from".split())


def _case(src, out):
    if src.isupper() and len(src) > 1:
        return out.upper()
    return out[0].upper() + out[1:] if src[:1].isupper() else out


def screen_tokens(tokens):
    """Rewrite a list of words for on-screen use. Returns the same number of
    entries (so word timings still line up); a swapped word may expand to two."""
    out = list(tokens)
    for i, t in enumerate(tokens):
        m = _CRYPTO.match(t)
        if not m:
            continue
        word, punct = m.group(1), m.group(2)
        nxt = re.sub(r"[^\w’']", "", tokens[i + 1]).lower() if i + 1 < len(tokens) else ""
        prev = tokens[i - 1].lower() if i else ""
        plural_src = word.lower() in ("cryptos", "cryptocurrencies")
        if prev in ("a", "an"):
            rep = "digital asset"
            out[i - 1] = _case(tokens[i - 1], "a")
        elif punct or not nxt or nxt in _NOUN_NEXT or nxt in _VERB_FIX or plural_src:
            rep = "digital assets"
            if not punct and nxt in _VERB_FIX and not plural_src:
                lead = re.match(r"^\W*", tokens[i + 1]).group(0)
                tail = tokens[i + 1][len(lead) + len(nxt):]
                out[i + 1] = lead + _case(tokens[i + 1][len(lead):], _VERB_FIX[nxt]) + tail
        else:  # adjective: crypto wallet -> digital asset wallet
            rep = "digital asset"
        out[i] = _case(word, rep) + punct
    return [re.sub(r"crypto", "digital asset", o, flags=re.I) for o in out]  # any leftover fragment


def screen_text(s):
    """On-screen text says "digital assets", never "crypto", and stays grammatical."""
    return " ".join(screen_tokens(str(s).split()))


# ── bundle ───────────────────────────────────────────────────────────────────
def load_bundle(src, work):
    d = os.path.join(work, "bundle")
    if os.path.isdir(src):
        shutil.copytree(src, d)
    elif src.endswith(".json"):
        # JSON-with-base64 variant: {"bundle": {...}, "files": {"name": "base64"}}
        import base64
        j = json.load(open(src))
        os.makedirs(d)
        for name, b64 in (j.get("files") or {}).items():
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(base64.b64decode(b64))
        json.dump(j["bundle"], open(os.path.join(d, "bundle.json"), "w"))
    else:
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                if n.startswith("/") or ".." in n.split("/"):
                    raise ValueError("unsafe path in bundle: " + n)
            z.extractall(d)
    b = json.load(open(os.path.join(d, "bundle.json")))
    if b.get("format") != "cfa-final-edit-bundle":
        raise ValueError("not a CFA final-edit bundle")
    return d, b


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def fill_timings(segs, words, total):
    """Ensure every segment has start/end. Missing ones are re-aligned from the
    word list, else interpolated by word count between known neighbours."""
    n = len(segs)
    # try re-alignment for missing ones using words
    W = [(norm(w[0]), w[1], w[2]) for w in words if norm(w[0])]
    cur = 0
    for s in segs:
        toks = [norm(t) for t in s["text"].split() if norm(t)]
        if s.get("start") is not None and s.get("end") is not None:
            # advance cursor past this segment
            while cur < len(W) and W[cur][1] < s["end"] - 0.01:
                cur += 1
            continue
        if not toks or cur >= len(W):
            continue
        for k in range(cur, min(len(W), cur + 60)):
            if W[k][0] == toks[0] and (len(toks) < 2 or k + 1 >= len(W) or W[k + 1][0] == toks[1]):
                last = min(len(W) - 1, k + len(toks) - 1)
                s["start"], s["end"] = W[k][1], W[last][2]
                cur = last + 1
                break
    # interpolate the rest
    wc = [max(1, len(s["text"].split())) for s in segs]
    i = 0
    while i < n:
        if segs[i].get("start") is not None:
            i += 1
            continue
        j = i
        while j < n and segs[j].get("start") is None:
            j += 1
        a = segs[i - 1]["end"] if i > 0 else 0.0
        b = segs[j]["start"] if j < n else total
        tot = sum(wc[i:j]) or 1
        t = a
        for k in range(i, j):
            d = (b - a) * wc[k] / tot
            segs[k]["start"], segs[k]["end"], segs[k]["interpolated"] = t, t + d, True
            t += d
        i = j
    return segs


MIN_HOLD = 3.75        # seconds a picture stays up at minimum (short beats share a shot)
XFADE = 0.9            # default crossfade
KB_DEFAULT, KB_MAX = 0.045, 0.07   # Ken Burns: slow and subtle


def add_pauses(voice, words, segs, work, beat_pause=0.6, sentence_pause=0.45):
    """Insert silence so there is >= beat_pause between beats and >= sentence_pause
    after a sentence end inside a beat. Shifts words and beat timings to match.
    Returns (new_voice_path, words, inserted [(t, extra)], total_added)."""
    if not words or (beat_pause <= 0 and sentence_pause <= 0):
        return voice, words, [], 0.0
    beat_first = set()
    for s in segs:
        if s.get("start") is None:
            continue
        k = min(range(len(words)), key=lambda j: abs(words[j][1] - s["start"]))
        if k:
            beat_first.add(k)
    ins = []
    for k in range(len(words) - 1):
        gap = words[k + 1][1] - words[k][2]
        target = beat_pause if (k + 1) in beat_first else (sentence_pause if re.search(r"[.!?…][\"”’']?$", words[k][0]) else 0)
        extra = round(target - max(0.0, gap), 3)
        if target and extra > 0.02:
            ins.append((words[k][2] + max(0.0, gap) / 2, extra))
    if not ins:
        return voice, words, [], 0.0

    def shift(t):
        return t + sum(e for p, e in ins if p <= t + 1e-6)
    src = os.path.join(work, "voice_src.wav")
    run(["ffmpeg", "-y", "-v", "error", "-i", voice, "-ar", "48000", "-ac", "2", src])
    cuts = [0.0] + [p for p, _ in ins]
    fc, labs = [], []
    for i, a in enumerate(cuts):
        b = cuts[i + 1] if i + 1 < len(cuts) else None
        trim = "atrim=start=%.4f%s" % (a, (":end=%.4f" % b) if b is not None else "")
        pad = (",apad=pad_dur=%.4f" % ins[i][1]) if i < len(ins) else ""
        fc.append("[0:a]%s,asetpts=PTS-STARTPTS%s[p%d]" % (trim, pad, i))
        labs.append("[p%d]" % i)
    fc.append("%sconcat=n=%d:v=0:a=1[a]" % ("".join(labs), len(labs)))
    out = os.path.join(work, "voice_paced.wav")
    gs = os.path.join(work, "pause_graph.txt")
    open(gs, "w").write(";\n".join(fc))
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex_script", gs, "-map", "[a]", "-ar", "48000", out])
    new_words = [[w[0], round(shift(w[1]), 3), round(shift(w[2]), 3)] for w in words]
    for s in segs:
        if s.get("start") is not None:
            s["start"], s["end"] = round(shift(s["start"]), 3), round(shift(s["end"]), 3)
    return out, new_words, ins, sum(e for _, e in ins)


def cut_points(segs, total):
    """Beat boundaries: cuts sit in the middle of the pause before each beat."""
    cuts = [0.0]
    for i in range(1, len(segs)):
        prev_end, st = segs[i - 1]["end"], segs[i]["start"]
        c = st - max(0.0, st - prev_end) / 2
        cuts.append(max(cuts[-1] + 0.3, min(c, total - 0.3)))
    cuts.append(total)
    return cuts


def media_value(seg):
    """How much a beat's picture matters to the story if it is dropped by a merge."""
    if not seg.get("media"):
        return 0.0
    chars = (seg.get("characters") or "NONE") != "NONE"
    if seg.get("mediaType") == "video":
        return 3.5 if chars else 2.5
    return 3.0 if chars else 1.0


def pick_media(segs, g):
    media = [segs[i] for i in g if segs[i].get("media")]
    if not media:
        return None
    # character pictures carry the story; then motion; earliest wins ties
    return max(media, key=lambda s: (media_value(s), -g.index(segs.index(s))))


def group_shots(segs, cuts, min_hold=MIN_HOLD):
    """Partition consecutive beats into shots that each hold >= min_hold seconds.
    Among valid partitions, choose the one that drops the least story value
    (character stills and clips are expensive to lose, concept stills cheap),
    then the one with more shots. Each shot shows its most valuable picture."""
    n = len(segs)
    INF = float("inf")
    best = [(INF, 0, None)] * (n + 1)   # (dropped value, -shots, prev index)
    best[0] = (0.0, 0, None)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            if best[i][0] == INF:
                continue
            dur = cuts[j] - cuts[i]
            if dur < min_hold and not (i == 0 and j == n):
                continue
            g = list(range(i, j))
            pick = pick_media(segs, g)
            dropped = sum(media_value(segs[k]) for k in g) - (media_value(pick) if pick else 0)
            cand = (best[i][0] + dropped, best[i][1] - 1, i)
            if (cand[0], cand[1]) < (best[j][0], best[j][1]):
                best[j] = cand
    if best[n][0] == INF:          # cannot satisfy the hold anywhere: one shot
        bounds = [0, n]
    else:
        bounds, j = [n], n
        while j:
            j = best[j][2]
            bounds.append(j)
        bounds.reverse()
    shots = []
    for k in range(len(bounds) - 1):
        g = list(range(bounds[k], bounds[k + 1]))
        pick = pick_media(segs, g)
        shots.append({"index": k + 1, "beats": [segs[i]["index"] for i in g],
                      "start": cuts[g[0]], "end": cuts[g[-1] + 1],
                      "media": pick.get("media") if pick else None,
                      "mediaType": (pick.get("mediaType") or "image") if pick else "",
                      "text": " ".join(segs[i]["text"] for i in g)})
    return shots


# ── Grok edit decision list ──────────────────────────────────────────────────
EDL_SYSTEM = """You are a senior YouTube video editor for Chosen Few Academy, a calm, unhurried, beginner-friendly
education channel about digital assets (story-driven 2D illustrated explainers with characters Marcus and Jordan).
The pace must feel slow and easy to follow. You receive SHOTS (each already holds one or more voiceover beats,
at least ~3.75 s each) with LOCKED timings and the media for each shot.
Return ONLY a JSON object, no prose:
{
 "shots":[{"index":int,"motion":"zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down|static",
           "intensity":0.02-0.07,"transition_in":"cut|dissolve|fadeblack",
           "transition_duration":0.8-1.0,"emphasis":["word",...]}],
 "caption_style":{"preset":"clean_lower|boxed|bold_pop","words_per_caption":5-8,"highlight_color":"#RRGGBB","position":"bottom|center"},
 "title_card":{"enabled":bool,"text":"...","subtitle":"...","duration":2.5-4},
 "end_card":{"enabled":bool,"text":"...","duration":2.5-4},
 "thumbnail":{"shot_index":int,"text":"max 5 words"}
}
Rules: exactly one entry per shot, same index. Durations are fixed by the voice; never invent timing.
Motion is slow and subtle (intensity 0.03-0.05 typical, never above 0.07); alternate direction between consecutive stills; "static" for video clips.
Transitions are gentle: dissolve 0.8-1.0 s by default, fadeblack only at a big story turn, plain cut only for a deliberate jolt (rare). First shot transition_in is "cut".
Captions are calm phrase-level chunks (5-8 words, broken at natural phrase boundaries), not word-by-word pops; 1-2 emphasis words per shot at most.
On-screen text must say "digital assets", never the word "crypto". Keep text short and calm, no hype."""


def grok_edl(bundle, shots, key, model="grok-4.3", timeout=120):
    sh = [{"index": s["index"], "text": s["text"], "media": s.get("mediaType") or "none",
           "seconds": round(s["end"] - s["start"], 2), "beats": len(s["beats"])} for s in shots]
    user = json.dumps({"title": bundle.get("title"), "episode": bundle.get("episode"),
                       "total_seconds": round(shots[-1]["end"], 2), "shots": sh})
    body = json.dumps({"model": model, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": EDL_SYSTEM}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(XAI_URL, data=body, headers={"Authorization": "Bearer " + key,
                                                               "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.load(r)
    txt = j["choices"][0]["message"]["content"]
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
    return json.loads(txt), j.get("usage", {})


def fallback_edl(bundle, shots):
    cycle = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
    out, k = [], 0
    for i, s in enumerate(shots):
        vid = s.get("mediaType") == "video"
        out.append({"index": s["index"], "motion": "static" if vid else cycle[k % len(cycle)],
                    "intensity": KB_DEFAULT, "transition_in": "cut" if i == 0 else "dissolve",
                    "transition_duration": 0.0 if i == 0 else XFADE, "emphasis": []})
        k += 0 if vid else 1
    t = bundle.get("title") or "Chosen Few Academy"
    ep = bundle.get("episode")
    return {"shots": out,
            "caption_style": {"preset": "clean_lower", "words_per_caption": 7, "highlight_color": "#FFD23F", "position": "bottom"},
            "title_card": {"enabled": True, "text": t, "subtitle": ("Episode %d" % ep) if ep else "Chosen Few Academy", "duration": 3.5},
            "end_card": {"enabled": True, "text": "Subscribe for the next episode", "duration": 3.5},
            "thumbnail": {"shot_index": 1, "text": t}}


def clamp(v, lo, hi, d):
    try:
        v = float(v)
    except Exception:
        return d
    return d if math.isnan(v) else max(lo, min(hi, v))


def validate_edl(raw, bundle, shots_in):
    """Coerce Grok's EDL onto the real shot timings. Returns (edl, problems).
    Raises ValueError when it is unusable (caller falls back)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("shots"), list):
        raise ValueError("no shots list")
    fb = fallback_edl(bundle, shots_in)
    by_idx = {}
    for s in raw["shots"]:
        if isinstance(s, dict):
            try:
                by_idx.setdefault(int(s.get("index")), s)
            except Exception:
                pass
    problems = []
    if len(by_idx) < max(1, int(0.8 * len(shots_in))):
        raise ValueError("EDL covers %d of %d shots" % (len(by_idx), len(shots_in)))
    shots = []
    for i, base in enumerate(shots_in):
        s, f = by_idx.get(base["index"]), fb["shots"][i]
        if s is None:
            problems.append("shot %d missing; fallback used" % base["index"])
            s = f
        dur = base["end"] - base["start"]
        motion = s.get("motion") if s.get("motion") in MOTIONS else f["motion"]
        if base.get("mediaType") == "video":
            motion = "static"
        tr = s.get("transition_in") if s.get("transition_in") in TRANSITIONS else f["transition_in"]
        td = clamp(s.get("transition_duration"), 0.8, 1.0, XFADE)
        if i == 0:
            tr, td = "cut", 0.0
        # a transition may use at most 40% of either neighbouring shot
        prev_dur = shots_in[i - 1]["end"] - shots_in[i - 1]["start"] if i else 0
        td = min(td, 0.4 * dur, 0.4 * prev_dur) if i else 0.0
        if tr == "cut" or td < 0.1:
            tr, td = "cut", 0.0
        shots.append({"index": base["index"], "beats": base["beats"], "start": round(base["start"], 3),
                      "end": round(base["end"], 3), "duration": round(dur, 3),
                      "media": base["media"], "mediaType": base["mediaType"], "motion": motion,
                      "intensity": clamp(s.get("intensity"), 0.02, KB_MAX, KB_DEFAULT),
                      "transition_in": tr, "transition_duration": round(td, 3),
                      "emphasis": [str(x) for x in (s.get("emphasis") or []) if isinstance(x, (str, int))][:2]})
    cs = raw.get("caption_style") if isinstance(raw.get("caption_style"), dict) else {}
    hc = cs.get("highlight_color", "")
    cap = {"preset": cs.get("preset") if cs.get("preset") in CAPTION_STYLES else "clean_lower",
           "words_per_caption": int(clamp(cs.get("words_per_caption"), 5, 8, 7)),
           "highlight_color": hc if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(hc)) else "#FFD23F",
           "position": cs.get("position") if cs.get("position") in ("bottom", "center") else "bottom"}

    def card(c, d):
        c = c if isinstance(c, dict) else {}
        out = {"enabled": bool(c.get("enabled", d["enabled"])),
               "text": screen_text(str(c.get("text") or d["text"]))[:80],
               "duration": clamp(c.get("duration"), 2.5, 4.0, d["duration"])}
        if "subtitle" in d:
            out["subtitle"] = screen_text(str(c.get("subtitle") or d["subtitle"]))[:80]
        return out
    th = raw.get("thumbnail") if isinstance(raw.get("thumbnail"), dict) else {}
    ti = int(clamp(th.get("shot_index"), 1, len(shots_in), 1))
    if not shots_in[ti - 1].get("media"):
        ti = next((s["index"] for s in shots_in if s.get("media")), 1)
    return ({"shots": shots, "caption_style": cap,
             "title_card": card(raw.get("title_card"), fb["title_card"]),
             "end_card": card(raw.get("end_card"), fb["end_card"]),
             "thumbnail": {"shot_index": ti, "text": screen_text(str(th.get("text") or bundle.get("title") or ""))[:60]}},
            problems)


# ── rendering ────────────────────────────────────────────────────────────────
def render_shot(src, kind, shot, W, H, out, frames):
    """Render one shot to an intermediate (video only) of exactly `frames` frames."""
    dur = frames / FPS
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
    if src is None:
        vf = "color=c=0x101418:s=%dx%d:r=%d" % (W, H, FPS)
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", vf, "-frames:v", str(frames)] + enc + [out])
        return
    if kind == "video":
        cd = media_duration(src) or dur
        speed = min(1.0, cd / dur) if cd < dur else 1.0
        speed = max(speed, 0.67)  # slow at most to 1.5x length, then hold the last frame
        vf = ("setpts=PTS/%.4f,fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
              "tpad=stop_mode=clone:stop_duration=%.2f,setsar=1" % (speed, FPS, W, H, W, H, dur + 1))
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-frames:v", str(frames)] + enc + [out])
        return
    # still: Ken Burns on a 2x canvas for smooth sub-pixel motion
    m, k = shot["motion"], shot["intensity"]
    W2, H2 = W * 2, H * 2
    p = "(on/%d)" % (frames - 1)
    ease = "(0.5-0.5*cos(PI*%s))" % p
    if m == "zoom_in":
        z, x, y = "1+%.3f*%s" % (k, ease), "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif m == "zoom_out":
        z, x, y = "%.3f-%.3f*%s" % (1 + k, k, ease), "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif m in ("pan_left", "pan_right"):
        z = "%.3f" % (1 + k)
        a = ease if m == "pan_right" else "(1-%s)" % ease
        x, y = "(iw-iw/zoom)*%s" % a, "ih/2-(ih/zoom/2)"
    elif m in ("pan_up", "pan_down"):
        z = "%.3f" % (1 + k)
        a = ease if m == "pan_down" else "(1-%s)" % ease
        x, y = "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*%s" % a
    else:
        z, x, y = "1", "0", "0"
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,"
          "zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d" % (W2, H2, W2, H2, z, x, y, frames, W, H, FPS))
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", src, "-vf", vf, "-frames:v", str(frames)] + enc + [out])


def ass_color(hexrgb, alpha="00"):
    h = hexrgb.lstrip("#")
    return "&H%s%s%s%s&" % (alpha, h[4:6], h[2:4], h[0:2])


def ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def ass_esc(s):
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(words, segs, edl, W, H, total, path):
    cap = edl["caption_style"]
    vertical = H > W
    size = int(min(W, H) * (0.062 if cap["preset"] == "bold_pop" else 0.054))
    margin_v = int(H * (0.08 if cap["position"] == "bottom" else 0.42))
    if vertical and cap["position"] == "bottom":
        margin_v = int(H * 0.22)  # clear of Shorts UI
    border_style, outline, back = (3, 10, "&H80000000") if cap["preset"] == "boxed" else (1, max(3, size // 12), "&H96000000")
    hl = ass_color(cap["highlight_color"])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H00101010,{back},1,0,0,0,100,100,0,0,{border_style},{outline},2,2,{int(W*0.08)},{int(W*0.08)},{margin_v},1
Style: Title,{FONT},{int(H*0.075)},&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,1,0,0,0,100,100,0,0,1,{max(3,int(H*0.005))},3,5,{int(W*0.08)},{int(W*0.08)},0,1
Style: Sub,{FONT},{int(H*0.035)},{hl},&H00FFFFFF,&H00101010,&H96000000,1,0,0,0,100,100,2,0,1,3,2,5,{int(W*0.08)},{int(W*0.08)},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev, cues = [], []
    # phrase-level captions: break at punctuation / max words, never across a beat,
    # held until the next phrase (up to 0.8 s past the last word), min 1.2 s on screen
    W_ = [(w[0], float(w[1]), float(w[2])) for w in words]
    disp_all = screen_tokens([w[0] for w in W_])
    n = cap["words_per_caption"]
    starts = sorted(s["start"] for s in segs if s.get("start") is not None)[1:]
    groups, cur = [], []
    for k, w in enumerate(W_):
        if cur and any(W_[cur[-1]][1] < st <= w[1] + 0.02 for st in starts):
            groups.append(cur)
            cur = []
        cur.append(k)
        soft = re.search(r"[,;:—–]$", w[0]) and len(cur) >= max(3, n - 3)
        if len(cur) >= n or re.search(r"[.!?…][\"”’']?$", w[0]) or soft:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    shot_of = lambda t: next((i for i, sh in enumerate(edl["shots"]) if sh["start"] <= t < sh["end"]), len(edl["shots"]) - 1)
    emph = [{norm(x) for x in sh.get("emphasis", [])} for sh in edl["shots"]]
    for gi, g in enumerate(groups):
        g_start = W_[g[0]][1]
        g_end = W_[g[-1]][2] + 0.8
        if gi + 1 < len(groups):
            g_end = min(g_end, W_[groups[gi + 1][0]][1])
        g_end = min(max(g_end, g_start + 1.2), total)
        if gi + 1 < len(groups):
            g_end = min(g_end, W_[groups[gi + 1][0]][1])
        disp = [disp_all[k] for k in g]
        em = emph[shot_of(g_start)]
        txt = " ".join(("{\\c%s}%s{\\c&H00FFFFFF&}" % (hl, ass_esc(t))) if norm(W_[k][0]) in em else ass_esc(t)
                       for t, k in zip(disp, g))
        ev.append("Dialogue: 1,%s,%s,Cap,,0,0,0,,{\\fad(200,200)}%s" % (ass_time(g_start), ass_time(g_end), txt))
        cues.append({"start": round(g_start, 3), "end": round(g_end, 3), "text": " ".join(disp)})
    tc, ec = edl["title_card"], edl["end_card"]
    if tc["enabled"]:
        d = tc["duration"]
        ev.append("Dialogue: 2,%s,%s,Title,,0,0,0,,{\\an5\\pos(%d,%d)\\fad(300,400)}%s" % (ass_time(0), ass_time(d), W // 2, int(H * 0.40), ass_esc(tc["text"])))
        ev.append("Dialogue: 2,%s,%s,Sub,,0,0,0,,{\\an5\\pos(%d,%d)\\fad(300,400)}%s" % (ass_time(0.25), ass_time(d), W // 2, int(H * 0.40 + H * 0.085), ass_esc(tc.get("subtitle", ""))))
    if ec["enabled"]:
        d = min(ec["duration"], total / 3)
        ev.append("Dialogue: 2,%s,%s,Title,,0,0,0,,{\\an5\\pos(%d,%d)\\fad(400,300)}%s" % (ass_time(total - d), ass_time(total), W // 2, int(H * 0.38), ass_esc(ec["text"])))
    open(path, "w", encoding="utf-8").write(head + "\n".join(ev) + "\n")
    return cues


def loudnorm_json(stderr):
    i = stderr.rfind("{")
    return json.loads(stderr[i:stderr.index("}", i) + 1])


def build_audio(voice, music, total, out, work):
    """Voice (+ optional music ducked with sidechaincompress), 2-pass loudnorm to -14 LUFS / -1 dBTP."""
    mix = os.path.join(work, "mix.wav")
    if music:
        fc = ("[0:a]aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:%.3f,asplit=2[v][sc];"
              "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=-16dB,aloop=loop=-1:size=2e9,atrim=0:%.3f,"
              "afade=t=in:d=1.5,afade=t=out:st=%.3f:d=2[m];"
              "[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400:makeup=1[duck];"
              "[v][duck]amix=inputs=2:duration=first:normalize=0[a]") % (total, total, max(0, total - 2))
        run(["ffmpeg", "-y", "-v", "error", "-i", voice, "-stream_loop", "-1", "-i", music,
             "-filter_complex", fc, "-map", "[a]", "-ar", "48000", mix])
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", voice, "-af",
             "aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:%.3f" % total, "-ar", "48000", mix])
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", mix, "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = loudnorm_json(r.stderr)
    af = ("loudnorm=I=-14:TP=-1:LRA=11:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:"
          "offset=%s:linear=true" % (m["input_i"], m["input_tp"], m["input_lra"], m["input_thresh"], m["target_offset"]))
    run(["ffmpeg", "-y", "-v", "error", "-i", mix, "-af", af + ",aresample=48000", "-c:a", "aac", "-b:a", "192k", out])


def font_file(pattern):
    try:
        f = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout.strip()
        return f or None
    except Exception:
        return None


def make_thumbnail(clip, t, text, vertical, work, out):
    tw, th = (1280, 720) if not vertical else (720, 1280)
    words, lines, cur = (text or "").upper().split(), [], ""
    maxc = 18 if not vertical else 12
    for w in words:
        if cur and len(cur) + 1 + len(w) > maxc:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    lines = lines[:3]
    fs = int(th * (0.13 if not vertical else 0.075))
    vf = ["scale=%d:%d" % (tw, th)]
    if lines:
        box_h = (len(lines) * 1.15 + 0.6) * fs
        vf.append("drawbox=y=ih-%d:w=iw:h=%d:color=black@0.5:t=fill" % (box_h, box_h))
        ff = font_file("Anton") or font_file("sans:bold")
        for k, ln in enumerate(lines):
            p = os.path.join(work, "thumb_%d.txt" % k)
            open(p, "w").write(ln)
            y = th - box_h + 0.3 * fs + k * 1.15 * fs
            vf.append("drawtext=textfile='%s'%s:fontsize=%d:fontcolor=%s:borderw=5:bordercolor=black:x=(w-text_w)/2:y=%d"
                      % (p, (":fontfile='%s'" % ff) if ff else "", fs, "0xFFD23F" if k == len(lines) - 1 else "white", y))
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % t, "-i", clip, "-frames:v", "1", "-vf", ",".join(vf), "-q:v", "2", out])


def measure_lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    try:
        return float(loudnorm_json(r.stderr)["input_i"])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", help="CFA_FinalEdit_*.zip (or unpacked folder, or JSON-with-base64)")
    ap.add_argument("-o", "--out", default="render-out")
    ap.add_argument("--vertical", action="store_true", help="1080x1920 instead of 1920x1080")
    ap.add_argument("--music", help="optional background music file (ducked under the voice)")
    ap.add_argument("--no-grok", action="store_true", help="skip Grok, use the deterministic edit")
    ap.add_argument("--model", default="grok-4.3")
    ap.add_argument("--keys-env", default="/home/box/secrets/cfa_keys.env", help="optional env file for XAI_API_KEY")
    ap.add_argument("--caption-style", choices=CAPTION_STYLES, help="override Grok's caption preset")
    ap.add_argument("--min-hold", type=float, default=MIN_HOLD, help="min seconds per shot; short beats are merged (default 3.75)")
    ap.add_argument("--beat-pause", type=float, default=0.6, help="min silence between beats, padded from timestamps (0 = off)")
    ap.add_argument("--sentence-pause", type=float, default=0.45, help="min silence after a sentence inside a beat (0 = off)")
    ap.add_argument("--no-title", action="store_true")
    ap.add_argument("--no-end-card", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args()

    ensure_ffmpeg()
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cfa-render-")
    W, H = (1080, 1920) if a.vertical else (1920, 1080)
    d, b = load_bundle(a.bundle, work)
    voice = os.path.join(d, b["voiceover"])
    total = media_duration(voice)
    if total <= 0:
        raise SystemExit("voiceover missing or unreadable")
    words = [w for w in (b.get("words") or []) if isinstance(w, list) and len(w) == 3]
    segs = sorted(b["segments"], key=lambda s: s["index"])
    for s in segs:
        if s.get("media") and not os.path.exists(os.path.join(d, s["media"])):
            s["media"] = None
    fill_timings(segs, words, total)
    voice_raw = total
    voice, words, pauses, added = add_pauses(voice, words, segs, work, a.beat_pause, a.sentence_pause)
    if added:
        total = media_duration(voice)
    cuts = cut_points(segs, total)
    base_shots = group_shots(segs, cuts, a.min_hold)
    log("%s | %d beats -> %d shots | voice %.2fs (+%.2fs pauses) | %dx%d" % (
        b.get("title"), len(segs), len(base_shots), total, added, W, H))

    # EDL
    key = os.environ.get("XAI_API_KEY")
    if not key and a.keys_env and os.path.exists(a.keys_env):
        for line in open(a.keys_env):
            if line.startswith("XAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    source, problems, usage = "fallback", [], {}
    edl = None
    if key and not a.no_grok:
        for attempt in range(2):
            try:
                raw, usage = grok_edl(b, base_shots, key, a.model)
                edl, problems = validate_edl(raw, b, base_shots)
                source = "grok:" + a.model
                break
            except Exception as e:
                problems.append("grok attempt %d failed: %s" % (attempt + 1, str(e)[:200]))
    if edl is None:
        edl, _ = validate_edl(fallback_edl(b, base_shots), b, base_shots)
    if a.caption_style:
        edl["caption_style"]["preset"] = a.caption_style
    if a.no_title:
        edl["title_card"]["enabled"] = False
    if a.no_end_card:
        edl["end_card"]["enabled"] = False
    edl["source"] = source
    edl["pauses_added"] = round(added, 3)
    json.dump(edl, open(os.path.join(a.out, "edl.json"), "w"), indent=1)
    log("EDL from", source, "| problems:", problems or "none")

    # shots
    clips, last_media = [], None
    shots = edl["shots"]
    for i, shot in enumerate(shots):
        nxt = shots[i + 1]["transition_duration"] if i + 1 < len(shots) else 0.0
        src, kind = None, "image"
        if shot.get("media"):
            src, kind = os.path.join(d, shot["media"]), shot.get("mediaType") or "image"
            last_media = (src, kind)
        elif last_media:  # hold the previous visual rather than going black
            src, kind = last_media
        out = os.path.join(work, "shot_%03d.mp4" % i)
        f0 = round(shot["start"] * FPS)
        f1 = round((shot["end"] + nxt) * FPS) if i + 1 < len(shots) else round(total * FPS) + 2
        render_shot(src, kind, shot, W, H, out, max(2, f1 - f0))
        clips.append(out)
        log("shot %d/%d beats %s %s %s %.2fs" % (i + 1, len(shots), shot["beats"], kind, shot["motion"], shot["duration"]))

    # assemble: xfade chain (offset = next cut time) + captions
    ass = os.path.join(work, "captions.ass")
    cues = build_ass(words, segs, edl, W, H, total, ass)
    inputs, fc, prev = [], [], "[0:v]"
    for c in clips:
        inputs += ["-i", c]
    for i in range(1, len(clips)):
        shot = edl["shots"][i]
        tr = TRANSITIONS[shot["transition_in"]]
        lab = "[x%d]" % i
        if tr is None:
            fc.append("%s[%d:v]concat=n=2:v=1:a=0%s" % (prev, i, lab))
        else:
            fc.append("%s[%d:v]xfade=transition=%s:duration=%.3f:offset=%.3f%s" % (prev, i, tr, shot["transition_duration"], round(shot["start"] * FPS) / FPS, lab))
        prev = lab
    ass_esc_path = ass.replace("\\", "/").replace(":", "\\:")
    fc.append("%sfps=%d,trim=0:%.3f,setpts=PTS-STARTPTS,subtitles='%s'[v]" % (prev, FPS, total, ass_esc_path))
    audio = os.path.join(work, "audio.m4a")
    build_audio(voice, a.music, total, audio, work)
    final = os.path.join(a.out, "final.mp4")
    fcs = os.path.join(work, "graph.txt")
    open(fcs, "w").write(";\n".join(fc))
    run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-i", audio, "-filter_complex_script", fcs,
         "-map", "[v]", "-map", "%d:a" % len(clips), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "copy", "-t", "%.3f" % total,
         "-movflags", "+faststart", final])

    # thumbnail: chosen shot (caption-free intermediate), big title text
    th = edl["thumbnail"]
    si = th["shot_index"] - 1
    thumb = os.path.join(a.out, "thumbnail.jpg")
    make_thumbnail(clips[si], shots[si]["duration"] * 0.6, th["text"], a.vertical, work, thumb)

    pr = probe(final)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    au = [s for s in pr["streams"] if s["codec_type"] == "audio"]
    report = {"final": final, "thumbnail": thumb, "duration": float(pr["format"]["duration"]),
              "voice_duration": total, "resolution": "%sx%s" % (v["width"], v["height"]),
              "audio_streams": len(au), "lufs": measure_lufs(final), "edl_source": source,
              "edl_problems": problems, "grok_usage": usage, "beats": len(segs),
              "voice_raw_duration": voice_raw, "pauses_added": round(added, 3), "pause_count": len(pauses),
              "shots": [{"index": x["index"], "beats": x["beats"], "media": x["media"], "type": x["mediaType"],
                         "start": x["start"], "duration": x["duration"], "motion": x["motion"],
                         "transition": x["transition_in"], "xfade": x["transition_duration"]} for x in shots],
              "avg_shot": round(total / len(shots), 3), "min_shot": min(x["duration"] for x in shots),
              "interpolated_beats": [s["index"] for s in segs if s.get("interpolated")],
              "caption_cues": cues, "padded_words": words, "render_seconds": round(time.time() - t0, 1)}
    json.dump(report, open(os.path.join(a.out, "report.json"), "w"), indent=1)
    shutil.copy(ass, os.path.join(a.out, "captions.ass"))
    if not a.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    log("done: %s (%.2fs, voice %.2fs, %s LUFS) in %ss" % (final, report["duration"], total, report["lufs"], report["render_seconds"]))


if __name__ == "__main__":
    main()
