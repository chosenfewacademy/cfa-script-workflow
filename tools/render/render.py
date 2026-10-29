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
MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "punch_in", "push_in", "static"]
TRANSITIONS = {"cut": None, "whip": "smoothleft", "dissolve": "fade", "fadeblack": "fadeblack"}
TRANS_RANGE = {"whip": (0.2, 0.35), "dissolve": (0.5, 1.0), "fadeblack": (0.5, 1.0)}
FOCI = {"center": (0.5, 0.5), "left": (0.25, 0.45), "right": (0.75, 0.45), "top": (0.5, 0.25), "bottom": (0.5, 0.75)}
ROLES = ["hook", "tension", "turn", "realization", "resolve"]
CAPTION_STYLES = ["bold_pop", "clean_lower", "boxed"]
# Resilia-style per-beat grades (layered under the shared LUT): cool & low for the cold open,
# sterile for the struggle, golden from the turn on.
GRADES = {"cool_low": "eq=brightness=-0.03:saturation=0.82:gamma=0.97,colorbalance=bs=0.06:bm=0.04:rh=-0.03",
          "sterile": "eq=saturation=0.72:contrast=1.04,colorbalance=bs=0.03:gs=0.02:rm=-0.02",
          "golden": "eq=saturation=1.08:brightness=0.02,colorbalance=rs=0.05:rm=0.06:bm=-0.05:bh=-0.03"}
ROLE_GRADE = {"montage": "sterile", "hook": "cool_low", "tension": "sterile", "turn": "golden", "realization": "golden", "resolve": "golden"}
DRIFT_MAX = 3.2         # stills longer than this are split into 3-4 s parts with constant slow drift
TITLE_DEFAULT_ON = os.environ.get("CFA_TITLE", "0") == "1"   # fix (b): title card off unless asked for
PUNCH_ZOOM = 1.28      # punch-in framing (second half of a split still)
TENSE_MAX = 2.6         # tense beats (hook, turn, montage, crisis words, or the tool marks pace=tense): ~2 s cuts
TENSE_TARGET = 2.0
CALM_TARGET = 2.6       # calm beats: 3-4 s parts
TENSE_WORDS = re.compile(r"\b(gone|now|seconds?|locked|lost|deadline|frozen|failed|wrong|empty|zero|panic|too late|missing|stolen|drained|declined|ran out|run out|hurry|no time)\b", re.I)
SPLIT_OVER = 3.2       # a still held longer than this (outside the realization) is split wide -> punch-in
TP_RE = re.compile(r"\b(that'?s why|which is why|so that|the point|realiz\w*|not a price|instead|because|the answer|it meant|that was it|finally|suddenly|clicked|understood|that's the)\b", re.I)
FONT = "Montserrat"


def log(*a):
    print("[render]", *a, flush=True)


RUN_TIMEOUT = int(os.environ.get("CFA_FFMPEG_TIMEOUT", "1800"))


def run(cmd, **kw):
    kw.setdefault("timeout", RUN_TIMEOUT)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.stderr.write(r.stderr[-4000:])
        why = ""
        if r.returncode < 0:
            why = " (killed by signal %d%s)" % (-r.returncode, ", likely out of memory" if r.returncode == -9 else "")
        raise RuntimeError("command failed%s: " % why + " ".join(map(str, cmd[:6])) + " ...")
    return r



ENCODE_CHUNK = int(os.environ.get("CFA_ENCODE_CHUNK", "16"))


def _t(x):
    return round(x * FPS) / FPS


def chain_graph(n, shots, base, first_label=0):
    """xfade/concat chain over n inputs; shots[k] describes input k; offsets relative to base."""
    fc, prev = ["[0:v]settb=1/%d[b0]" % FPS], "[b0]"
    for i in range(1, n):
        shot = shots[i]
        tr = TRANSITIONS[shot["transition_in"]]
        lab = "[x%d]" % i
        if tr is None:
            fc.append("%s[%d:v]concat=n=2:v=1:a=0,settb=1/%d%s" % (prev, i, FPS, lab))
        else:
            fc.append("[%d:v]settb=1/%d[in%d]" % (i, FPS, i))
            fc.append("%s[in%d]xfade=transition=%s:duration=%.3f:offset=%.3f%s" % (
                prev, i, tr, shot["transition_duration"], _t(shot["start"]) - base, lab))
        prev = lab
    return fc, prev


def chunk_groups(n, size):
    size = max(2, size)
    groups = [list(range(k, min(n, k + size))) for k in range(0, n, size)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        last = groups.pop()
        groups[-1] = groups[-1] + last
    return groups


def encode_video(clips, shots, total, tail_filter, audio, final, work, chunk=None):
    """Encode the shot chain. Long edits are pre-joined in chunks so ffmpeg never holds
    more than `chunk` decoders at once (a single 100+ input graph got OOM-killed)."""
    chunk = chunk or ENCODE_CHUNK
    srcs, sshots = list(clips), list(shots)
    if len(clips) > chunk:
        groups = chunk_groups(len(clips), chunk)
        log("encoding %d shots in %d chunks of <=%d" % (len(clips), len(groups), chunk))
        srcs, sshots = [], []
        for gi, g in enumerate(groups):
            base = _t(shots[g[0]]["start"])
            fc, prev = chain_graph(len(g), [shots[k] for k in g], base)
            fc.append("%snull[v]" % prev)
            gfile = os.path.join(work, "graph_chunk_%02d.txt" % gi)
            open(gfile, "w").write(";\n".join(fc))
            out = os.path.join(work, "chunk_%02d.mp4" % gi)
            ins = []
            for k in g:
                ins += ["-i", clips[k]]
            run(["ffmpeg", "-y", "-v", "error"] + ins + ["-filter_complex_script", gfile, "-map", "[v]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p", "-r", str(FPS), out])
            srcs.append(out)
            sshots.append(shots[g[0]])
    fc, prev = chain_graph(len(srcs), sshots, 0.0)
    fc.append("%s%s[v]" % (prev, tail_filter))
    fcs = os.path.join(work, "graph.txt")
    open(fcs, "w").write(";\n".join(fc))
    inputs = []
    for c in srcs:
        inputs += ["-i", c]
    run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-i", audio, "-filter_complex_script", fcs,
         "-map", "[v]", "-map", "%d:a" % len(srcs), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "copy", "-t", "%.3f" % total,
         "-movflags", "+faststart", final])

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


def probe_wh(path):
    for st in probe(path).get("streams", []):
        if st.get("codec_type") == "video":
            return int(st.get("width") or 0), int(st.get("height") or 0)
    return 0, 0


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


MIN_HOLD = 1.6         # seconds a picture stays up at minimum (only very short beats share a shot)
XFADE = 0.8            # default dissolve (realization / resolve only)
KB_DEFAULT, KB_MAX = 0.06, 0.12    # motion on every shot


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
    lips = [(s["start"], s["end"]) for s in segs if s.get("mediaType") == "lipsync" and s.get("start") is not None]
    in_lip = lambda t: any(a - 1e-3 <= t <= b + 1e-3 for a, b in lips)
    ins = []
    for k in range(len(words) - 1):
        gap = words[k + 1][1] - words[k][2]
        target = beat_pause if (k + 1) in beat_first else (0 if in_lip(words[k][2]) else (sentence_pause if re.search(r"[.!?…][\"”’']?$", words[k][0]) else 0))
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
        if segs[i].get("mediaType") == "lipsync":
            c = st - min(0.12, max(0.0, st - prev_end))          # picture lands just before the speaker talks
        elif segs[i - 1].get("mediaType") == "lipsync":
            c = min(st + 0.25, segs[i]["end"] - 0.3) if segs[i]["end"] - st > 0.8 else c  # J/L: the line leads, picture follows
        cuts.append(max(cuts[-1] + 0.3, min(c, total - 0.3)))
    cuts.append(total)
    return cuts


def media_value(seg):
    """How much a beat's picture matters to the story if it is dropped by a merge."""
    if not seg.get("media"):
        return 0.0
    chars = (seg.get("characters") or "NONE") != "NONE"
    if seg.get("mediaType") == "lipsync":
        return 50.0
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
            g = list(range(i, j))
            has_lip = any(segs[k].get("mediaType") == "lipsync" for k in g)
            if has_lip and len(g) > 1:
                continue  # a talking shot carries exactly its own line
            if dur < min_hold and not (i == 0 and j == n) and not has_lip:
                continue
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
EDL_SYSTEM = """You are a senior short-form story editor for Chosen Few Academy, a calm, trust-first education channel about
digital assets (story-driven 2D cartoon explainers with Marcus and Jordan). Calm does NOT mean flat: the edit must hold attention.
You receive SHOTS (one or more voiceover beats each) with LOCKED timings and media type. Plan the edit around the story arc:
- HOOK (first ~3 s): cold open on the tension, no title card on top of it; the first cut lands fast.
- TENSION (hook -> turning point): short-short-long rhythm, hard cuts, punch-ins on long stills, motion every shot, something changes every 2-4 s.
- TURN: the one shot where the story turns (the reveal / the answer starts). Mark it; it gets a whip/hard cut with a riser + impact.
- REALIZATION (1-2 shots after the turn): slow down — longer holds, slow push, a dissolve, no punch-in. This is the longest hold.
- RESOLVE: steady, gentle dissolves or cuts to the end.
Return ONLY a JSON object, no prose:
{
 "arc":{"hook_end_shot":int,"turning_point_shot":int,"realization_shots":[int,...]},
 "shots":[{"index":int,"role":"hook|tension|turn|realization|resolve",
           "motion":"zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down|push_in","intensity":0.03-0.12,
           "transition_in":"cut|whip|dissolve|fadeblack","transition_duration":0.2-1.0,
           "punch_in":bool,"focus":"center|left|right|top|bottom","emphasis":["word",...]}],
 "caption_style":{"preset":"bold_pop|clean_lower|boxed","words_per_caption":2-5,"highlight_color":"#RRGGBB","position":"bottom|center"},
 "title_card":{"enabled":bool,"text":"...","subtitle":"...","duration":2-3.5},
 "end_card":{"enabled":bool,"text":"...","duration":2.5-4},
 "thumbnail":{"shot_index":int,"text":"max 5 words"}
}
Rules: exactly one entry per shot, same index. Durations are fixed by the voice; never invent timing.
Motion on every shot (videos get "push_in"); alternate direction between consecutive stills; intensity 0.07-0.12 in tension, 0.04-0.06 in realization.
punch_in=true splits a long still into wide then a tighter punch-in on "focus" (the face or the key object) — use it on long tension/hook stills, never in realization.
Transitions: "cut" for tension, "whip" (0.2-0.35 s) only for a big scene change and the turn (it gets a whoosh, so use at most 4), "dissolve" 0.6-1.0 s for realization/resolve, "fadeblack" at most once. First shot is "cut".
NARRATOR shots (wides, establishing, B-roll) get gentler motion and are good dissolve points; character lines cut on the speaker change (shot / reverse shot). Narrator captions are rendered in a separate quieter style automatically.
Captions are punchy 2-4 word chunks; 1-2 emphasis words per shot (numbers, names, the key noun/verb of the line).
The title card appears right after the hook, not over it. On-screen text must say "digital assets", never "crypto". No hype words."""


def grok_edl(bundle, shots, key, model="grok-4.3", timeout=120, notes=""):
    sh = [{"index": s["index"], "text": s["text"], "media": s.get("mediaType") or "none",
           "seconds": round(s["end"] - s["start"], 2), "beats": len(s["beats"])} for s in shots]
    user = json.dumps({"title": bundle.get("title"), "episode": bundle.get("episode"),
                       "total_seconds": round(shots[-1]["end"], 2), "shots": sh})
    if notes:
        user += "\n\nEDITOR NOTES from the creator for this re-edit (follow them within the rules): " + notes[:2000]
    body = json.dumps({"model": model, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": EDL_SYSTEM}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(XAI_URL, data=body, headers={"Authorization": "Bearer " + key,
                                                               "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.load(r)
    txt = j["choices"][0]["message"]["content"]
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
    return json.loads(txt), j.get("usage", {})


STOP = set("the a an and or but of to in on at for with is was were it its he she they his her their that this then than had has have be been as by from not no so just".split())


def pick_emphasis(text, k=2):
    """Numbers first, then mid-sentence names, then the longest content words."""
    toks = re.findall(r"[A-Za-z0-9'$%.,-]+", text or "")
    out = []
    for i, t in enumerate(toks):
        w = t.strip(".,")
        if re.search(r"\d", w) and w not in out:
            out.append(w)
    for i, t in enumerate(toks):
        w = t.strip(".,")
        if i and w[:1].isupper() and not toks[i - 1].endswith(".") and w.lower() not in STOP and w not in out:
            out.append(w)
    rest = sorted({t.strip(".,") for t in toks if len(t.strip(".,")) >= 6 and t.lower().strip(".,") not in STOP}, key=lambda w: -len(w))
    out += [w for w in rest if w not in out]
    return out[:k]


def detect_arc(shots):
    """Hook = shots starting in the first 3 s; turn = best turning-point cue in 40-85% of the runtime
    (else the shot at ~62%); realization = the 1-2 shots after it."""
    n = len(shots)
    total = shots[-1]["end"] if shots else 1.0
    hook_end = max([s["index"] for s in shots if s["start"] < 3.0] or [shots[0]["index"]]) if shots else 1
    best, bscore = None, -1e9
    for s in shots:
        pos = s["start"] / total
        if s["index"] <= hook_end or not (0.35 <= pos <= 0.88):
            continue
        sc = 2.0 * min(1, len(TP_RE.findall(s.get("text", "")))) - abs(pos - 0.62) * 3
        if sc > bscore:
            best, bscore = s["index"], sc
    tp = best or min(n, max(hook_end + 1, round(n * 0.62)))
    real = [i for i in (tp + 1, tp + 2) if i <= n][:2]
    return {"hook_end_shot": hook_end, "turning_point_shot": tp, "realization_shots": real}


def role_of(idx, arc):
    if idx <= arc["hook_end_shot"]:
        return "hook"
    if idx < arc["turning_point_shot"]:
        return "tension"
    if idx == arc["turning_point_shot"]:
        return "turn"
    if idx in arc["realization_shots"]:
        return "realization"
    return "resolve"


def fallback_edl(bundle, shots):
    cycle = ["zoom_in", "pan_right", "zoom_out", "pan_left", "pan_up", "pan_down"]
    arc = detect_arc(shots)
    out, k = [], 0
    for i, s in enumerate(shots):
        vid = s.get("mediaType") in ("video", "lipsync")
        role = role_of(s["index"], arc)
        dur = s["end"] - s["start"]
        tr, td = "cut", 0.0
        if i and role == "turn":
            tr, td = "whip", 0.3
        elif i and role == "realization":
            tr, td = "dissolve", 0.9
        elif i and role == "resolve":
            tr, td = ("dissolve", 0.6) if k % 2 == 0 else ("cut", 0.0)
        out.append({"index": s["index"], "role": role, "motion": "push_in" if vid else cycle[k % len(cycle)],
                    "intensity": 0.05 if role == "realization" else 0.09, "transition_in": tr, "transition_duration": td,
                    "punch_in": (not vid) and dur > SPLIT_OVER and role in ("hook", "tension", "resolve"),
                    "focus": "center", "emphasis": pick_emphasis(s.get("text", ""))})
        k += 0 if vid else 1
    t = bundle.get("title") or "Chosen Few Academy"
    ep = bundle.get("episode")
    return {"arc": arc, "shots": out,
            "caption_style": {"preset": "bold_pop", "words_per_caption": 3, "highlight_color": "#FFD23F", "position": "bottom"},
            "title_card": {"enabled": True, "text": t, "subtitle": ("Episode %d" % ep) if ep else "Chosen Few Academy", "duration": 2.5},
            "end_card": {"enabled": True, "text": "Subscribe for the next episode", "duration": 3.5},
            "thumbnail": {"shot_index": 1, "text": t}}


def clamp(v, lo, hi, d):
    try:
        v = float(v)
    except Exception:
        return d
    return d if math.isnan(v) else max(lo, min(hi, v))


LUT_PATH = None    # shared colour grade (.cube), applied under the captions
GROK_TITLE = False  # True = let the edit model write title/thumbnail text (old behaviour)


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
    n = len(shots_in)
    ra = raw.get("arc") if isinstance(raw.get("arc"), dict) else {}
    arc = dict(fb["arc"])
    try:
        he, tp = int(ra.get("hook_end_shot")), int(ra.get("turning_point_shot"))
        if 1 <= he < tp <= n:
            arc["hook_end_shot"], arc["turning_point_shot"] = he, tp
            rs = [int(x) for x in (ra.get("realization_shots") or []) if tp < int(x) <= n][:2]
            arc["realization_shots"] = rs or [i for i in (tp + 1, tp + 2) if i <= n][:2]
        else:
            problems.append("arc out of range; detected arc used")
    except Exception:
        if ra:
            problems.append("arc unreadable; detected arc used")
    if len(by_idx) < max(1, int(0.8 * len(shots_in))):
        raise ValueError("EDL covers %d of %d shots" % (len(by_idx), len(shots_in)))
    shots = []
    for i, base in enumerate(shots_in):
        s, f = by_idx.get(base["index"]), fb["shots"][i]
        if s is None:
            problems.append("shot %d missing; fallback used" % base["index"])
            s = f
        dur = base["end"] - base["start"]
        role = role_of(base["index"], arc)
        vid = base.get("mediaType") in ("video", "lipsync")
        motion = s.get("motion") if s.get("motion") in MOTIONS and s.get("motion") not in ("static", "punch_in") else f["motion"]
        if vid:
            motion = "push_in"
        elif motion == "push_in":
            motion = "zoom_in"
        tr = s.get("transition_in") if s.get("transition_in") in TRANSITIONS else f["transition_in"]
        if role == "realization" and tr == "whip":
            tr = "dissolve"
        lo, hi = TRANS_RANGE.get(tr, (0, 0))
        td = clamp(s.get("transition_duration"), lo, hi, (lo + hi) / 2)
        if i == 0:
            tr, td = "cut", 0.0
        # a transition may use at most 40% of either neighbouring shot
        prev_dur = shots_in[i - 1]["end"] - shots_in[i - 1]["start"] if i else 0
        td = min(td, 0.4 * dur, 0.4 * prev_dur) if i else 0.0
        if tr == "cut" or td < 0.1:
            tr, td = "cut", 0.0
        punch = bool(s.get("punch_in", f["punch_in"])) and not vid and role != "realization" and dur > 3.2
        if not vid and dur > SPLIT_OVER and role in ("hook", "tension"):
            punch = True     # long tension stills always get a punch-in
        focus = s.get("focus") if s.get("focus") in FOCI else "center"
        emph = [str(x) for x in (s.get("emphasis") or []) if isinstance(x, (str, int))][:2] or f["emphasis"]
        shots.append({"index": base["index"], "beats": base["beats"], "start": round(base["start"], 3),
                      "end": round(base["end"], 3), "duration": round(dur, 3),
                      "media": base["media"], "mediaType": base["mediaType"], "motion": motion,
                      "intensity": clamp(s.get("intensity"), 0.03, KB_MAX, KB_DEFAULT) if role != "realization" else clamp(s.get("intensity"), 0.03, 0.06, 0.05),
                      "transition_in": tr, "transition_duration": round(td, 3), "role": role,
                      "punch_in": punch, "focus": focus, "emphasis": emph})
    cs = raw.get("caption_style") if isinstance(raw.get("caption_style"), dict) else {}
    hc = cs.get("highlight_color", "")
    cap = {"preset": cs.get("preset") if cs.get("preset") in CAPTION_STYLES else "bold_pop",
           "words_per_caption": int(clamp(cs.get("words_per_caption"), 2, 5, 3)),
           "highlight_color": hc if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(hc)) else "#FFD23F",
           "position": cs.get("position") if cs.get("position") in ("bottom", "center") else "bottom"}

    def card(c, d):
        c = c if isinstance(c, dict) else {}
        out = {"enabled": bool(c.get("enabled", d["enabled"])),
               "text": screen_text(str(c.get("text") or d["text"]))[:80],
               "duration": clamp(c.get("duration"), 2.0, 4.0, d["duration"])}
        if "subtitle" in d:
            out["subtitle"] = screen_text(str(c.get("subtitle") or d["subtitle"]))[:80]
        return out
    th = raw.get("thumbnail") if isinstance(raw.get("thumbnail"), dict) else {}
    ti = int(clamp(th.get("shot_index"), 1, len(shots_in), 1))
    if not shots_in[ti - 1].get("media"):
        ti = next((s["index"] for s in shots_in if s.get("media")), 1)
    tcard = card(raw.get("title_card"), fb["title_card"])
    if not GROK_TITLE:
        # overlay-only rule: on-screen words come from the bundle, never invented by the edit model
        tcard["text"], tcard["subtitle"] = fb["title_card"]["text"][:80], fb["title_card"].get("subtitle", "")[:80]
        th = {}
    return ({"arc": arc, "shots": shots, "caption_style": cap,
             "title_card": tcard,
             "end_card": card(raw.get("end_card"), fb["end_card"]),
             "thumbnail": {"shot_index": ti, "text": screen_text(str(th.get("text") or bundle.get("title") or ""))[:60]}},
            problems)


def split_punch_ins(shots, words):
    """Split each punch_in still at the word gap nearest its middle: wide (planned motion) -> hard cut -> punch-in."""
    out = []
    for sh in shots:
        dur = sh["end"] - sh["start"]
        if not sh.get("punch_in") or sh.get("mediaType") in ("video", "lipsync") or dur <= 3.2:
            out.append(dict(sh, part=""))
            continue
        mid = sh["start"] + dur / 2
        gaps = [float(w[1]) for w in words if sh["start"] + 1.4 <= float(w[1]) <= sh["end"] - 1.4]
        cut = min(gaps, key=lambda t: abs(t - mid)) - 0.05 if gaps else mid
        a = dict(sh, end=round(cut, 3), duration=round(cut - sh["start"], 3), part="a")
        b = dict(sh, start=round(cut, 3), duration=round(sh["end"] - cut, 3), part="b", motion="punch_in",
                 transition_in="cut", transition_duration=0.0, intensity=0.04)
        out += [a, b]
    for k, sh in enumerate(out):
        sh["index"] = k + 1
    return out


def is_tense(sh, segs=None):
    """Tense beat: hook/turn role, crisis words in the line, or a beat the tool's director marked pace=tense."""
    if sh.get("role") in ("hook", "turn", "montage"):
        return True
    if TENSE_WORDS.search(str(sh.get("text", ""))):
        return True
    for sg in segs or []:
        if sg.get("pace") == "tense" and sg.get("start") is not None and sh["start"] - 0.3 <= sg["start"] < sh["end"]:
            return True
    return False


def split_drift(shots, words, max_len=DRIFT_MAX, segs=None):
    """Resilia pacing: split long stills at word gaps into ~2 s parts on tense beats and ~3-4 s parts on calm
    beats; each part keeps a constant slow drift and alternates framing (wide drift -> off-centre punch-in
    left/right). Video/lip-sync untouched."""
    out = []
    drifts = ["pan_right", "zoom_in", "pan_left", "zoom_out"]
    for sh in shots:
        dur = sh["end"] - sh["start"]
        tense = is_tense(sh, segs)
        lim, target = (TENSE_MAX, TENSE_TARGET) if tense else (max_len, CALM_TARGET)
        if sh.get("mediaType") in ("video", "lipsync") or dur <= lim:
            out.append(dict(sh, pace="tense" if tense else "calm"))
            continue
        n = max(2, int(math.ceil(dur / target)))
        gaps = [float(w[1]) for w in words if sh["start"] + 1.2 <= float(w[1]) <= sh["end"] - 1.2]
        cuts = []
        for k in range(1, n):
            t = sh["start"] + dur * k / n
            c = min(gaps, key=lambda g: abs(g - t)) - 0.05 if gaps else t
            if (not cuts or c - cuts[-1] >= 1.2) and c - sh["start"] >= 1.2 and sh["end"] - c >= 1.2:
                cuts.append(round(c, 3))
        edges = [sh["start"]] + cuts + [sh["end"]]
        base_part = sh.get("part", "")
        for k in range(len(edges) - 1):
            p = dict(sh, start=round(edges[k], 3), end=round(edges[k + 1], 3), duration=round(edges[k + 1] - edges[k], 3),
                     pace="tense" if tense else "calm")
            if k:
                p.update(part="b", transition_in="cut", transition_duration=0.0, intensity=0.035)
                if k % 2:
                    p.update(motion="punch_in", focus="left" if (k // 2) % 2 == 0 else "right")
                else:
                    p.update(motion=drifts[k % len(drifts)])
            else:
                p["part"] = base_part
                if p.get("motion") in (None, "static"):
                    p["motion"] = "zoom_in"
            out.append(p)
    for k, sh in enumerate(out):
        sh["index"] = k + 1
    return out


MONTAGE_RE = re.compile(r"\b(day|days|week|weeks|hour|hours|night|morning|attempt|try|tries|again|then|by|first|second|third|one|two|three|four|five|\d+)\b", re.I)


def detect_montage(segs, total):
    """Milestone montage beats: explicit role, else a run of 2-4 consecutive short NARRATOR lines that count
    progress (days, attempts, numbers) in the middle of the episode."""
    exp = [sg for sg in segs if sg.get("role") == "montage" and sg.get("start") is not None]
    if exp:
        return exp
    run_, best = [], []
    for sg in segs + [{}]:
        ok = (sg.get("speaker") == "NARRATOR" and sg.get("start") is not None and total
              and 0.2 <= sg["start"] / total <= 0.85 and len(str(sg.get("text", "")).split()) <= 14
              and MONTAGE_RE.search(str(sg.get("text", ""))))
        if ok:
            run_.append(sg)
        else:
            if 2 <= len(run_) and len(run_) > len(best):
                best = run_[:4]
            run_ = []
    return best


def assign_grades(shots, on=True):
    for sh in shots:
        sh["grade"] = ROLE_GRADE.get(sh.get("role"), "") if on else ""
    return shots


def grade_vf(shot):
    g = GRADES.get(shot.get("grade") or "")
    return ("," + g) if g else ""


# ── sound design ─────────────────────────────────────────────────────────────
def make_sfx(work):
    """Synthesised, license-free whoosh / riser / impact (one family)."""
    p = {k: os.path.join(work, k + ".wav") for k in ("whoosh", "riser", "impact")}
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=0.6:a=0.6:r=48000",
         "-af", "bandpass=f=1400:width_type=o:w=2.5,afade=t=in:d=0.32:curve=exp,afade=t=out:st=0.32:d=0.28,volume=1.6", "-ac", "2", p["whoosh"]])
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=color=white:d=2.4:a=0.25:r=48000",
         "-f", "lavfi", "-i", "aevalsrc=0.22*sin(2*PI*(140*t+70*t*t)):d=2.4:s=48000",
         "-filter_complex", "[0]highpass=f=900[n];[n][1]amix=inputs=2:normalize=0,afade=t=in:d=2.3:curve=exp", "-ac", "2", p["riser"]])
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "aevalsrc=0.9*sin(2*PI*52*t)*exp(-4.5*t)+0.25*sin(2*PI*104*t)*exp(-7*t):d=1.0:s=48000",
         "-ac", "2", p["impact"]])
    return p


def sfx_events(shots, arc_times):
    ev = []
    tp = arc_times.get("turn")
    for sh in shots[1:]:
        if sh["transition_in"] == "whip":
            ev.append(("whoosh", max(0, sh["start"] - 0.3), 0.55))
    if tp:
        ev.append(("riser", max(0, tp - 2.4), 0.5))
        ev.append(("impact", tp, 0.8))
        if not any(abs(t + 0.3 - tp) < 0.2 for k, t, _ in ev if k == "whoosh"):
            ev.append(("whoosh", max(0, tp - 0.3), 0.55))
    # whooshes stay sparse: at most 5
    wh = [e for e in ev if e[0] == "whoosh"][:5]
    return sorted(wh + [e for e in ev if e[0] != "whoosh"], key=lambda e: e[1])


# ── rendering ────────────────────────────────────────────────────────────────
_BARS = {}
_SUBJ = {}
_LUMA = {}
DARK_LIFT_BELOW, DARK_TARGET = 80.0, 95.0


def mean_luma(src, kind):
    """Average luma (0-255) of the still / an early clip frame; None if it cannot be measured."""
    if src in _LUMA:
        return _LUMA[src]
    y = None
    try:
        err = subprocess.run(["ffmpeg", "-v", "info", "-hide_banner"] + (["-ss", "0.3"] if kind in ("video", "lipsync") else []) +
                             ["-i", src, "-frames:v", "1", "-vf", "scale=96:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=60).stderr
        v = re.findall(r"YAVG=([\d.]+)", err)
        y = float(v[-1]) if v else None
    except Exception:
        y = None
    _LUMA[src] = y
    return y


def lift_filter(y):
    """Gamma lift that brings a too-dark frame's mean luma to ~DARK_TARGET (keeps blacks black, opens midtones)."""
    if y is None or y >= DARK_LIFT_BELOW or y <= 1:
        return ""
    g = max(1.05, min(1.9, math.log(y / 255.0) / math.log(DARK_TARGET / 255.0)))
    return ",eq=gamma=%.2f:contrast=1.12:saturation=1.1" % g
SUBJECT_KEY = None  # xAI key for subject location (vertical reframing); None -> centre


def subject_center(src, kind, seg_hint=None):
    """Normalised (cx, cy) of the main subject (character's face/upper body, else the key prop).
    Order: a box the tool sent in bundle.json -> one Grok vision call per source (cached) -> centre."""
    if seg_hint and isinstance(seg_hint, dict) and "cx" in seg_hint:
        return (clamp(seg_hint.get("cx"), 0, 1, 0.5), clamp(seg_hint.get("cy", 0.45), 0, 1, 0.45))
    if src in _SUBJ:
        return _SUBJ[src]
    c = (0.5, 0.45)
    if SUBJECT_KEY:
        try:
            jpg = src + ".subj.jpg"
            run(["ffmpeg", "-y", "-v", "error"] + (["-ss", "0.3"] if kind in ("video", "lipsync") else []) + ["-i", src, "-frames:v", "1", "-vf", "scale=640:-2", jpg])
            import base64
            url = "data:image/jpeg;base64," + base64.b64encode(open(jpg, "rb").read()).decode()
            body = json.dumps({"model": "grok-4.3", "response_format": {"type": "json_object"}, "max_tokens": 200, "messages": [
                {"role": "system", "content": "You locate the main subject of a cartoon frame for reframing to a vertical 9:16 crop. The subject is the main character's face and upper body; if no person, the key prop the shot is about. Return JSON only: {\"cx\":0-1,\"cy\":0-1,\"w\":0-1,\"h\":0-1,\"what\":\"short\"} — box centre and size as fractions of image width/height."},
                {"role": "user", "content": [{"type": "text", "text": "Locate the subject."}, {"type": "image_url", "image_url": {"url": url}}]}]}).encode()
            req = urllib.request.Request(XAI_URL, data=body, headers={"Authorization": "Bearer " + SUBJECT_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = json.load(r)["choices"][0]["message"]["content"]
            o = json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip())
            c = (clamp(o.get("cx"), 0, 1, 0.5), clamp(o.get("cy"), 0, 1, 0.45))
            log("subject", os.path.basename(src), "->", "%.2f,%.2f" % c, str(o.get("what", ""))[:40])
        except Exception as e:
            log("subject locate failed (centre crop):", str(e)[:80])
    _SUBJ[src] = c
    return c


def subject_crop(W, H, c):
    """scale-to-cover then crop W x H with the subject centred (clamped to the frame)."""
    cx, cy = c
    return ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d:'min(max(0,iw*%.3f-%d),iw-%d)':'min(max(0,ih*%.3f-%d),ih-%d)'"
            % (W, H, W, H, cx, W // 2, W, cy, H // 2, H))


def detect_bars(src, kind):
    """Content box (w,h,x,y) when the media has baked-in black bars (some image models pad to 16:9), else None."""
    if src in _BARS:
        return _BARS[src]
    box = None
    try:
        args = ["ffmpeg", "-v", "info", "-hide_banner"] + (["-ss", "0.5"] if kind in ("video", "lipsync") else ["-loop", "1"]) + \
               ["-i", src, "-vf", "cropdetect=limit=0.09:round=2:reset=0", "-frames:v", "6", "-f", "null", "-"]
        err = subprocess.run(args, capture_output=True, text=True, timeout=60).stderr
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
        dims = re.search(r"Stream.*Video.* (\d{2,5})x(\d{2,5})", err)
        if m and dims:
            w, h, x, y = map(int, m[-1]); iw, ih = int(dims.group(1)), int(dims.group(2))
            if w >= iw * 0.3 and h >= ih * 0.3 and (w < iw * 0.93 or h < ih * 0.93):
                box = (w, h, x, y)
    except Exception:
        box = None
    _BARS[src] = box
    return box


def fill_graph(box, W, H):
    """-vf prefix: crop away baked-in bars and place the art over a blurred fill of itself at the canvas size."""
    w, h, x, y = box
    return ("crop=%d:%d:%d:%d,split[a][b];[a]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=20:2,eq=brightness=-0.08[bg];"
            "[b]scale=%d:%d:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1" % (w, h, x, y, W, H, W, H, W, H))


# ── 2.5D depth parallax for stills (replaces the Ken Burns fallback; Oct 28 motion audit) ──
STILL_MOTION = os.environ.get("CFA_STILL_MOTION", "parallax")   # "parallax" | "kenburns"
DEPTH_PY = os.environ.get("CFA_DEPTH_PY") or next((p for p in ("/workspace/.venv_depth/bin/python",) if os.path.exists(p)), None)
PARALLAX_PX_S = 9.0       # foreground lateral travel at 1280 px wide (px/s), eased; background ~0 (fix a: was 48)
PARALLAX_ZOOM_S = 0.012  # depth-scaled dolly per second (was 0.05)
PARALLAX_DEPTH_SCALE = 0.35  # depth range used for warping (1 = full model depth)
GATE_STRETCH_MAX = 1.08  # distortion gate: max local stretch of any still warp
PARALLAX_OVERSCAN = 1.12


def depth_maps(pairs, work):
    """[(src_png, dst_png)] -> {src: depth_png or None}. One model load for all stills; falls back to None ($0)."""
    out = {s: None for s, _ in pairs}
    todo = [(s, d) for s, d in pairs if not os.path.exists(d)]
    if todo and DEPTH_PY:
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "depth_maps.py")
        try:
            subprocess.run([DEPTH_PY, helper] + [x for p in todo for x in p], check=True, timeout=1800,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log("depth maps unavailable (%s); parallax uses a synthetic depth" % str(e)[:80])
    for s, d in pairs:
        out[s] = d if os.path.exists(d) else None
    return out


def synthetic_depth(h, w):
    """No depth model: lower frame and centre read as nearer (works for most character shots)."""
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    v = yy / max(1, h - 1)
    r = 1 - np.clip((((xx - w / 2) / (w / 2)) ** 2 + ((yy - h * 0.55) / (h / 2)) ** 2) ** 0.5, 0, 1)
    return np.clip(0.55 * v + 0.45 * r, 0, 1)


def _ease(t, carry_in=False, carry_out=False):
    """Cosine ease-in-out: starts and ends at rest. With carry, the move keeps some velocity through the cut
    (cut on movement) so the next shot picks the direction up instead of starting from a dead stop."""
    import math
    e = 0.5 - 0.5 * math.cos(math.pi * t)
    if carry_in and carry_out:
        return 0.35 * e + 0.65 * t
    if carry_out:
        return 0.35 * e + 0.65 * (1 - math.cos(math.pi * t / 2))   # ease in, leave moving
    if carry_in:
        return 0.35 * e + 0.65 * math.sin(math.pi * t / 2)        # arrive moving, ease out
    return e


def smooth_depth(depth, w, h):
    """Depth for warping: heavy blur, discontinuities clamped (max local gradient), range compressed by PARALLAX_DEPTH_SCALE."""
    import numpy as np, cv2
    d = cv2.resize(depth.astype(np.float32), (w, h))
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    d = cv2.medianBlur((d * 255).astype(np.uint8), 5).astype(np.float32) / 255.0
    k = max(3, int(round(min(w, h) * 0.04)) | 1)
    for _ in range(3):   # clamp steps at object edges: a dilate/erode band blended with a wide blur
        d = 0.5 * d + 0.5 * cv2.GaussianBlur(d, (k, k), 0)
    d = cv2.GaussianBlur(d, (0, 0), max(4.0, min(w, h) * 0.02))
    return 0.5 + (d - 0.5) * PARALLAX_DEPTH_SCALE


def parallax_maps(d, W, H, w, h, frames, motion, focus, punch, direction, carry=(False, False), amp=1.0, probe=False):
    """Per-frame remap fields (output pixel -> overscanned source). Small eased dolly + truck, never sampling outside the source."""
    import numpy as np
    dur = frames / float(FPS)
    sc = W / 1280.0
    side = direction if direction in (-1, 1) else (1 if focus[0] <= 0.5 else -1)
    lat = PARALLAX_PX_S * dur * sc * {"pan_left": -1.0, "pan_right": 1.0}.get(motion, 0.6 * side)
    zr = PARALLAX_ZOOM_S * dur * (-1.0 if motion == "zoom_out" else 1.0)
    if motion == "static":          # hold on a quote: barely breathing, no travel
        lat, zr = 0.4 * lat, 0.4 * zr
    elif motion == "zoom_in":       # motivated push-in: the dolly leads, little truck
        lat, zr = 0.3 * lat, 1.25 * zr
    elif motion in ("pan_left", "pan_right"):
        zr = 0.4 * zr
    lat, zr = lat * amp, zr * amp
    vert = 0.25 * abs(lat) * (-1.0 if motion == "pan_up" else 1.0 if motion == "pan_down" else 0.0)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = w * focus[0], h * focus[1]
    ox, oy = min(max(cx - W / 2 / punch, 0), w - W / punch), min(max(cy - H / 2 / punch, 0), h - H / punch)
    gx, gy = ox + xx / punch, oy + yy / punch
    import cv2
    dd = cv2.remap(d, gx, gy, cv2.INTER_LINEAR)
    pcx, pcy = ox + W / 2 / punch, oy + H / 2 / punch
    zdep = (0.85 + 0.3 * dd) if motion == "zoom_in" else (0.6 + 0.8 * dd)   # push-in: dolly feel with less depth warp
    for i in ([0, frames // 2, frames - 1] if probe else range(frames)):
        t = _ease(i / max(1, frames - 1), *carry)
        z = 1.0 + (zr * t if zr > 0 else -zr * (1 - t)) * zdep
        mx = (gx - pcx) / z + pcx - (t - 0.5) * lat * dd
        my = (gy - pcy) / z + pcy - (t - 0.5) * vert * dd
        yield np.clip(mx, 0, w - 1.001), np.clip(my, 0, h - 1.001)


def map_stretch(mx, my):
    """Max local anisotropic stretch of a remap field (1.0 = rigid/uniform scale). Edge-clamped regions count as stretch."""
    import numpy as np
    ax, ay = np.gradient(mx, axis=1), np.gradient(my, axis=0)
    bx, by = np.gradient(mx, axis=0), np.gradient(my, axis=1)
    s = np.sqrt(ax * ax + by * by + bx * bx + ay * ay) / np.sqrt(2.0)
    s = s / (np.median(s) + 1e-9)
    ratio = np.maximum(np.abs(ax), 1e-6) / np.maximum(np.abs(ay), 1e-6)
    return float(max(np.percentile(s, 99.5), np.percentile(np.maximum(ratio, 1 / ratio), 99.5)))


def parallax_frames(img, depth, W, H, frames, motion="zoom_in", focus=(0.5, 0.5), punch=1.0, direction=0, stats=None, carry=(False, False)):
    """Yield W x H BGR frames; stats (dict) gets the worst map stretch for the distortion gate."""
    import cv2
    h, w = img.shape[:2]
    d = smooth_depth(depth, w, h)
    worst = 1.0
    amp = 1.0
    for _ in range(6):   # distortion guard: shrink the move until the warp stays inside the gate
        if max(map_stretch(mx, my) for mx, my in parallax_maps(d, W, H, w, h, frames, motion, focus, punch, direction, carry, amp, True)) <= GATE_STRETCH_MAX * 0.98:
            break
        amp *= 0.8
    if stats is not None:
        stats["amp"] = round(amp, 3)
    for i, (mx, my) in enumerate(parallax_maps(d, W, H, w, h, frames, motion, focus, punch, direction, carry, amp)):
        if stats is not None and i in (0, frames // 2, frames - 1):
            worst = max(worst, map_stretch(mx, my))
        yield cv2.remap(img, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if stats is not None:
        stats["stretch"] = round(worst, 4)


def render_still_parallax(src, shot, W, H, out, frames, fit_vf, depth_png=None):
    """Still -> overscanned graded base (ffmpeg, same crop/reframe/lift/grade as Ken Burns) -> parallax frames -> h264."""
    import numpy as np, cv2
    Wo, Ho = int(W * PARALLAX_OVERSCAN) // 2 * 2, int(H * PARALLAX_OVERSCAN) // 2 * 2
    base = out + ".base.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", fit_vf(Wo, Ho) + grade_vf(shot), "-frames:v", "1", base])
    img = cv2.imread(base)
    dm = None
    if depth_png and os.path.exists(depth_png):   # same crop/reframe as the picture
        dbase = out + ".depth.png"
        run(["ffmpeg", "-y", "-v", "error", "-i", depth_png, "-vf", fit_vf(Wo, Ho), "-frames:v", "1", dbase])
        dm = cv2.imread(dbase, cv2.IMREAD_GRAYSCALE)
        os.remove(dbase)
    depth = dm.astype(np.float32) / 255.0 if dm is not None else synthetic_depth(Ho, Wo)
    m = shot.get("motion") or "zoom_in"
    punch = PUNCH_ZOOM if m == "punch_in" else 1.0
    focus = FOCI.get(shot.get("focus"), (0.5, 0.5)) if m == "punch_in" else (0.5, 0.5)
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (W, H), "-r", str(FPS),
                          "-i", "-", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                          "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", out], stdin=subprocess.PIPE)
    try:
        st = {}
        for fr in parallax_frames(img, depth, W, H, frames, m, focus, punch, shot.get("_dir", 0), st, (bool(shot.get("_carry_in")), bool(shot.get("_carry")))):
            p.stdin.write(np.ascontiguousarray(fr).tobytes())
    finally:
        p.stdin.close()
        p.wait()
    os.remove(base)
    if p.returncode:
        raise RuntimeError("parallax encode failed")
    shot["_stretch"] = st.get("stretch")
    return st.get("stretch")


# ── Phrase shot plan (tool sends shotPlan="phrase"): one new image per phrase, motivated motion, story-led transitions ──
PLAN_MOTION = {"push_in": "zoom_in", "track": "pan", "hold": "static", "reveal": "pan"}
PLAN_TRANS = {"cut": ("cut", 0.0), "match": ("cut", 0.0), "jcut": ("cut", 0.0), "push_link": ("cut", 0.0), "reverse": ("cut", 0.0),
              "whip": ("whip", 0.18), "time_jump": ("dissolve", 0.30)}
MUSIC_RESERVE_USD = 0.35   # held back from the total cap for music when sizing action i2v


def music_reserve(b, a):
    """Music money to hold back: none when the bundle carries music, scoring is off, or the episode score is cached."""
    b = b or {}
    style = (b.get("musicStyle") or getattr(a, "music_style", None) or "cinematic").lower()
    if b.get("music") or style == "none" or getattr(a, "no_score", False):
        return 0.0
    try:
        if music_cache_get(music_cache_key(b, style)):
            return 0.0
    except Exception:
        pass
    return MUSIC_RESERVE_USD


class ActionShotDegraded(RuntimeError):
    """A character-motion (action) shot would silently become a still. Fail loudly instead."""
J_LEAD = 0.20          # J-cut: the next line's audio leads the picture cut by this much
SIM_DHASH_MIN = 10     # similarity gate: consecutive shots closer than this (of 64 bits) ...
SIM_SSIM_MAX = 0.72    # ... or more structurally similar than this read as a re-angle of the same frame
PHRASE_ALIGN_MAX = 0.30  # motion must start within this many seconds of its phrase's first word


def apply_shot_plan(shots, segs):
    """Map each shot to its phrase segment: motivated motion, transition from the story link, carry direction, J-cut timing."""
    by = {s["index"]: s for s in segs}
    d = 1
    for i, x in enumerate(shots):
        sg = by.get((x.get("beats") or [None])[0]) or {}
        pm = sg.get("planMotion") or "track"
        vid = x.get("mediaType") in ("video", "lipsync")
        if sg.get("planDir") in (-1, 1):
            d = sg["planDir"]
        m = PLAN_MOTION.get(pm, "pan")
        if m == "pan":
            m = "pan_right" if d > 0 else "pan_left"
        if not vid:
            x["motion"] = m
        x["_dir"] = d
        x["plan_motion"], x["plan_link"] = pm, sg.get("planLink") or "cut"
        x["phrase_start"] = sg.get("start")
        x["plan_shot"], x["one_char"], x["line"] = sg.get("planShot") or "still", sg.get("oneChar"), sg.get("text") or ""
        if i:
            tr, td = PLAN_TRANS.get(x["plan_link"], ("cut", 0.0))
            x["transition_in"], x["transition_duration"] = tr, td
            if x["plan_link"] == "push_link" and shots[i - 1].get("mediaType") not in ("video", "lipsync"):
                shots[i - 1]["motion"] = "zoom_in"       # push into the detail that becomes this shot
            if x.get("phrase_start") is not None:
                # picture cut + motion start snap to the phrase's first word; a J-cut lands J_LEAD after it (audio leads)
                want = x["phrase_start"] + (J_LEAD if x["plan_link"] == "jcut" else 0.0)
                delta = want - x["start"]
                if abs(delta) > 1e-6 and x["duration"] - delta > 1.0 and shots[i - 1]["duration"] + delta > 1.0:
                    x["start"] = want; x["duration"] -= delta
                    shots[i - 1]["end"] = want; shots[i - 1]["duration"] += delta
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        x["_carry"] = bool(nxt is not None)                          # cut on movement: keep velocity into the cut
        x["_carry_in"] = i > 0 and shots[i - 1].get("_dir") == d
    return shots


def one_character_gate(segs, limit_beats=None):
    """Every planned shot shows one character at most (two-person beats are shot/reverse-shot)."""
    bad = [sg["index"] for sg in segs if (limit_beats is None or sg["index"] in limit_beats)
           and (str(sg.get("characters") or "").startswith("BOTH") or (sg.get("oneChar") and sg.get("characters") != sg.get("oneChar")))]
    return {"pass": not bad, "fails": bad}


# One motion model per episode (every character): mixing Kling-ref clips with stills changed the render look (Oct 29).
# Hailuo matched the baseline test_clip_vision look. Override per bundle (i2vModel) or env CFA_MOTION_MODEL.
EPISODE_MOTION_MODEL = os.environ.get("CFA_MOTION_MODEL", "hailuo")


def line_key(x):
    m = re.match(r"\s*(\d+)\.", str((x or {}).get("line") or ""))
    return m.group(1) if m else None


def same_line_media(shots, i):
    """Nearest other shot of the same script line that has media (used to fill a gap instead of holding the neighbour)."""
    k = line_key(shots[i])
    if k is None:
        return None
    c = [x for j, x in sorted(enumerate(shots), key=lambda t: abs(t[0] - i)) if j != i and x.get("media") and line_key(x) == k]
    return c[0] if c else None


def episode_motion_model(b, a):
    m = (b or {}).get("i2vModel") or (a.i2v if getattr(a, "i2v", "off") != "off" else EPISODE_MOTION_MODEL)
    return m if m in I2V_MODELS else EPISODE_MOTION_MODEL


def action_i2v_plan(shots, mode, cap):
    """Phrase plan: only shots whose line is physical action get image-to-video, never over `cap`."""
    if mode not in I2V_MODELS:
        return [], 0.0
    pick, est, seen = [], 0.0, set()
    for x in shots:
        m = x.get("media")
        if x.get("plan_shot") != "action" or not x.get("one_char") or not m or (x.get("mediaType") or "image") != "image" or m in seen:
            continue
        unit = i2v_cost(mode, x.get("duration"))
        if est + unit > (cap or 0) + 1e-9:
            x["i2v_skipped_cost"] = unit; continue
        seen.add(m); pick.append(x); est += unit
    return pick, round(est, 2)


def action_prompt(x):
    who = (x.get("one_char") or "the character").title()
    return ("%s acts out this moment with clear, natural body movement and an expression that fits it: %s. Only %s in frame, no second person "
            "(anyone else named stays off-screen). Mouth stays closed, no talking, same 3D Pixar style, same character as the image, smooth steady camera, "
            "crisp clean frames, no text, captions, signs or writing anywhere." % (who, (x.get("line") or "")[:220], who))


def _dhash(g):
    import cv2, numpy as np
    s = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    return (s[:, 1:] > s[:, :-1]).flatten()


def _ssim(a, b):
    import numpy as np, cv2
    a, b = a.astype(np.float64), b.astype(np.float64)
    C1, C2 = 6.5025, 58.5225
    mu1, mu2 = cv2.GaussianBlur(a, (7, 7), 1.5), cv2.GaussianBlur(b, (7, 7), 1.5)
    s1 = cv2.GaussianBlur(a * a, (7, 7), 1.5) - mu1 ** 2
    s2 = cv2.GaussianBlur(b * b, (7, 7), 1.5) - mu2 ** 2
    s12 = cv2.GaussianBlur(a * b, (7, 7), 1.5) - mu1 * mu2
    return float((((2 * mu1 * mu2 + C1) * (2 * s12 + C2)) / ((mu1 ** 2 + mu2 ** 2 + C1) * (s1 + s2 + C2))).mean())


def similarity_gate(path, shots):
    """Consecutive shots must show new visual information: fail pairs that read as the same frame re-angled,
    unless the plan marks an intentional match cut."""
    import cv2
    cap = cv2.VideoCapture(path)
    def grab(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
        ok, f = cap.read()
        if not ok:
            return None
        h = f.shape[0]
        return cv2.cvtColor(cv2.resize(f[int(h * .1):int(h * .72)], (160, 74)), cv2.COLOR_BGR2GRAY)  # captions excluded
    pairs, fails = [], []
    for i in range(1, len(shots)):
        a, b = shots[i - 1], shots[i]
        fa, fb = grab(a["start"] + a["duration"] * 0.5), grab(b["start"] + b["duration"] * 0.5)
        if fa is None or fb is None:
            continue
        dh = int((_dhash(fa) != _dhash(fb)).sum())
        ss = round(_ssim(fa, fb), 3)
        same = a.get("media") and a.get("media") == b.get("media")
        sim = same or dh < SIM_DHASH_MIN or ss > SIM_SSIM_MAX
        ok = (not sim) or b.get("plan_link") == "match"
        pairs.append({"i": i, "dhash": dh, "ssim": ss, "same_media": bool(same), "ok": ok})
        if not ok:
            fails.append(i)
    return {"pass": not fails, "fails": fails, "pairs": pairs, "dhash_min": SIM_DHASH_MIN, "ssim_max": SIM_SSIM_MAX}


def phrase_alignment(shots):
    """Motion starts with its phrase: shot start vs the phrase's first word (J-cut lead allowed)."""
    errs = [abs(x["start"] - x["phrase_start"]) for x in shots if x.get("phrase_start") is not None]
    worst = round(max(errs), 3) if errs else None
    return {"shots": len(errs), "max_offset_s": worst, "pass": worst is None or worst <= PHRASE_ALIGN_MAX}



def assign_directions(shots):
    """One lateral drift direction for adjacent stills so the camera progresses; flips only at the turn/realization."""
    d, prev = 1, None
    for x in shots:
        r = x.get("role")
        if r in ("turn", "realization") and prev not in ("turn", "realization"):
            d = -d
        x["_dir"] = d
        prev = r
    return shots


def render_shot(src, kind, shot, W, H, out, frames):
    """Render one shot to an intermediate (video only) of exactly `frames` frames."""
    dur = frames / FPS
    box = detect_bars(src, kind) if src else None
    reframe = None
    if src is not None and H > W:
        try:
            iw, ih = probe_wh(src)
            if iw and ih and iw / ih > (W / H) * 1.15:  # landscape art on a vertical canvas: follow the subject
                reframe = subject_center(src, kind, shot.get("subject"))
        except Exception:
            reframe = None
    lift = lift_filter(mean_luma(src, kind)) if src is not None else ""
    if lift:
        log("brighten", os.path.basename(src), "mean luma %.0f ->" % mean_luma(src, kind), lift[1:])
    def cover(w, h):
        pre = ("crop=%d:%d:%d:%d," % box) if box else ""
        if reframe:
            return pre + subject_crop(w, h, reframe) + ",setsar=1" + lift
        return (fill_graph(box, w, h) if box else "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1" % (w, h, w, h)) + lift
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
    if src is None:
        vf = "color=c=0x101418:s=%dx%d:r=%d" % (W, H, FPS)
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", vf, "-frames:v", str(frames)] + enc + [out])
        return
    if kind == "lipsync":
        off = max(0.0, float(shot.get("lip_offset") or 0.0))
        fit = cover(W, H)
        vf = ("fps=%d,%s,tpad=start_mode=clone:start_duration=%.3f:stop_mode=clone:stop_duration=%.2f,setsar=1"
              % (FPS, fit, off, dur + 1)) + grade_vf(shot)
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-frames:v", str(frames)] + enc + [out])
        return
    if kind in ("video", "lipsync"):
        cd = media_duration(src) or dur
        speed = min(1.0, cd / dur) if cd < dur else 1.0
        speed = max(speed, 0.67)  # slow at most to 1.5x length, then hold the last frame
        k = shot.get("intensity", 0.04) if shot.get("motion") == "push_in" else 0.0
        push = (",zoompan=z='1+%.3f*on/%d':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=%dx%d:fps=%d"
                % (min(k, 0.06), max(1, frames - 1), W, H, FPS)) if k else ""
        fit = cover(W, H)
        vf = ("setpts=PTS/%.4f,fps=%d,%s,"
              "tpad=stop_mode=clone:stop_duration=%.2f,setsar=1%s" % (speed, FPS, fit, dur + 1, push)) + grade_vf(shot)
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-frames:v", str(frames)] + enc + [out])
        return
    if STILL_MOTION == "parallax":
        try:
            render_still_parallax(src, shot, W, H, out, frames, cover, shot.get("_depth"))
            return
        except Exception as e:
            log("parallax failed (%s); Ken Burns fallback" % str(e)[:80])
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
    elif m == "punch_in":
        fx, fy = FOCI.get(shot.get("focus"), (0.5, 0.5))
        z = "%.3f+%.3f*%s" % (PUNCH_ZOOM, k, ease)
        x, y = "(iw-iw/zoom)*%.2f" % fx, "(ih-ih/zoom)*%.2f" % fy
    else:
        z, x, y = "1", "0", "0"
    if reframe and m in ("pan_left", "pan_right"):  # a sideways pan on a reframed vertical would slide off the subject
        z, x, y = "1+%.3f*%s" % (k, ease), "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    fit = cover(W2, H2)
    vf = (fit + ","
          "zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d" % (z, x, y, frames, W, H, FPS)) + grade_vf(shot)
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


CAPTIONS_ON = os.environ.get("CFA_CAPTIONS", "off") == "on"   # default: zero burned-in text


TEXT_GATE_SYS = ("You read a contact sheet of video frames from a 3D animated clip. List every piece of readable or pseudo writing you can see "
                 "(captions, subtitles, titles, overlays, signs, labels, screens, paper), per tile number (tiles numbered left-to-right, top-to-bottom from 1). "
                 'Mark each as "overlay" (burned-in caption/title over the picture) or "scene" (part of the drawn world) and whether it is correctly spelled real words. '
                 'JSON only: {"items":[{"tile":<int>,"text":"...","kind":"overlay|scene","spelled_ok":<bool>}]}')


def text_gate(mp4, key, every=1.0, ask=None, allow_scene=False):
    """Zero on-screen text: samples a frame every `every` s into tiled sheets and asks the vision model for any writing.
    Fails on any overlay text, and on scene writing unless allowed (then it must be correctly spelled)."""
    import base64, tempfile
    items = []
    if ask:
        items = ask(None).get("items") or []
    else:
        d = tempfile.mkdtemp()
        dur = media_duration(mp4)
        n = max(1, int(dur / every))
        for k0 in range(0, n, 12):
            sheet = os.path.join(d, "t%d.jpg" % k0)
            run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % (k0 * every), "-i", mp4, "-vf",
                 "fps=1/%.2f,scale=480:-2,tile=4x3" % every, "-frames:v", "1", sheet])
            url = "data:image/jpeg;base64," + base64.b64encode(open(sheet, "rb").read()).decode()
            body = json.dumps({"model": "grok-4.3", "response_format": {"type": "json_object"}, "max_tokens": 400, "messages": [
                {"role": "system", "content": TEXT_GATE_SYS}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}]}).encode()
            req = urllib.request.Request(XAI_URL, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = json.load(r)["choices"][0]["message"]["content"]
            o = json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip())
            for it in o.get("items") or []:
                it["t"] = round((k0 + int(it.get("tile") or 1) - 1) * every, 2)
                items.append(it)
    bad = [it for it in items if str(it.get("text", "")).strip() and (it.get("kind") != "scene" or not allow_scene or it.get("spelled_ok") is False)]
    return {"pass": not bad, "items": items, "fails": bad[:10]}


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
Style: Narr,{FONT},{int(size*0.86)},&H00C8E8F5,&H00C8E8F5,&H00101010,&H96000000,0,1,0,0,100,100,0,0,1,{max(2, size // 16)},1,2,{int(W*0.1)},{int(W*0.1)},{margin_v},1
Style: Title,{FONT},{int(H*0.075)},&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,1,0,0,0,100,100,0,0,1,{max(3,int(H*0.005))},3,5,{int(W*0.08)},{int(W*0.08)},0,1
Style: Ovl,{FONT},{int(H*0.045)},&H00FFFFFF,&H00FFFFFF,&H00101010,&H8C1A1A1A,1,0,0,0,100,100,1,0,3,{max(8,int(H*0.012))},0,8,{int(W*0.1)},{int(W*0.1)},{int(H*0.07)},1
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
    seg_spk = lambda t: next((str(sg.get("speaker") or "") for sg in segs if sg.get("start") is not None and float(sg["start"]) - 0.02 <= t < float(sg.get("end") or 1e9)), "")
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
        txt = " ".join(("{\\c%s\\t(0,120,\\fscx118\\fscy118)\\t(120,260,\\fscx100\\fscy100)}%s{\\c&H00FFFFFF&}" % (hl, ass_esc(t))) if norm(W_[k][0]) in em else ass_esc(t)
                       for t, k in zip(disp, g))
        pop = "{\\fad(80,120)\\fscx92\\fscy92\\t(0,110,\\fscx100\\fscy100)}" if cap["preset"] == "bold_pop" else "{\\fad(150,150)}"
        spk = seg_spk(g_start).upper()
        if spk == "NARRATOR":
            # narrator: quieter italic warm-white captions, no pop or highlight, so viewers can tell Bill from the characters
            ev.append("Dialogue: 1,%s,%s,Narr,,0,0,0,,{\\fad(200,200)}%s" % (ass_time(g_start), ass_time(g_end), " ".join(ass_esc(t) for t in disp)))
        else:
            ev.append("Dialogue: 1,%s,%s,Cap,,0,0,0,,%s%s" % (ass_time(g_start), ass_time(g_end), pop, txt))
        cues.append({"start": round(g_start, 3), "end": round(g_end, 3), "text": " ".join(disp), "speaker": spk or None})
    # overlay words planned per beat (the image itself carries no text)
    for sg in segs:
        ov = screen_text(str(sg.get("overlay") or "")).strip()
        if not ov or sg.get("start") is None or sg.get("end") is None:
            continue
        ov = " ".join(ov.split()[:6])
        a0, a1 = float(sg["start"]) + 0.15, max(float(sg["end"]), float(sg["start"]) + 1.5)
        ev.append("Dialogue: 3,%s,%s,Ovl,,0,0,0,,{\\fad(200,200)}%s" % (ass_time(a0), ass_time(min(a1, total)), ass_esc(ov)))
    tc, ec = edl["title_card"], edl["end_card"]
    if tc["enabled"]:
        # cold open: the title lands right after the hook, never over it
        t0 = min(edl.get("arc_times", {}).get("hook_end", 0.0), max(0.0, total - tc["duration"] - 1))
        d = t0 + tc["duration"]
        ev.append("Dialogue: 2,%s,%s,Title,,0,0,0,,{\\an5\\pos(%d,%d)\\fad(250,350)}%s" % (ass_time(t0), ass_time(d), W // 2, int(H * 0.30), ass_esc(tc["text"])))
        ev.append("Dialogue: 2,%s,%s,Sub,,0,0,0,,{\\an5\\pos(%d,%d)\\fad(250,350)}%s" % (ass_time(t0 + 0.2), ass_time(d), W // 2, int(H * 0.30 + H * 0.085), ass_esc(tc.get("subtitle", ""))))
    if ec["enabled"]:
        d = min(ec["duration"], total / 3)
        ev.append("Dialogue: 2,%s,%s,Title,,0,0,0,,{\\an5\\pos(%d,%d)\\fad(400,300)}%s" % (ass_time(total - d), ass_time(total), W // 2, int(H * 0.38), ass_esc(ec["text"])))
    if not CAPTIONS_ON:   # no on-screen text at all: no captions, overlays, title or end card burned in
        ev = []
    open(path, "w", encoding="utf-8").write(head + "\n".join(ev) + "\n")
    return cues


def loudnorm_json(stderr):
    i = stderr.rfind("{")
    return json.loads(stderr[i:stderr.index("}", i) + 1])


AMBIENCE_GAIN = 0.14   # per-scene ElevenLabs ambience, well under the voice (~-17 dB before the mix bus)


def scene_ambience(shots, segs, key, work, cache=None):
    """ElevenLabs sound effects per scene from the director's sfx text (room tone, street, shop bell...).
    One sound per distinct description (cached), trimmed to the shot with short fades. Returns
    ([(path, start, gain, dur)], info). Any failure just skips that scene - ambience is never required."""
    import urllib.request
    by_idx = {sg["index"]: sg for sg in segs}
    cache = {} if cache is None else cache
    out, info = [], {"scenes": 0, "generated": 0, "errors": []}
    for sh in shots:
        txt = next((str(by_idx[i].get("sfx") or "").strip() for i in sh["beats"] if i in by_idx and str(by_idx[i].get("sfx") or "").strip()), "")
        if not txt or not key:
            continue
        txt = re.sub(r"\b(music|song|singing|voices?|speech|talking)\b", "", txt, flags=re.I)
        txt = re.sub(r"^(?:\W|and|with|or|no)+|(?:\W|and|with|or|no)+$", "", re.sub(r"\s+", " ", txt), flags=re.I)[:200]
        if len(re.sub(r"[^a-z]", "", txt.lower())) < 3:
            continue
        info["scenes"] += 1
        dur = round(min(22.0, max(1.0, sh["duration"] + 0.4)), 2)
        ck = (txt.lower(), dur if dur < 22 else 22)
        if ck not in cache:
            path = os.path.join(work, "amb_%02d.mp3" % len(cache))
            body = json.dumps({"text": txt + ", ambient background, no music, no voices", "duration_seconds": dur, "prompt_influence": 0.35}).encode()
            req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=body, method="POST",
                                         headers={"xi-api-key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = r.read()
                if len(data) < 500:
                    raise ValueError("empty audio")
                open(path, "wb").write(data)
                cache[ck] = path
                info["generated"] += 1
            except Exception as e:
                cache[ck] = None
                info["errors"].append("%s: %s" % (txt[:40], str(e)[:120]))
        if cache[ck]:
            out.append((cache[ck], sh["start"], AMBIENCE_GAIN, sh["duration"]))
    return out, info


FOLEY_KINDS = [  # (kind, keyword regex on the SPOKEN line only, ElevenLabs prompt). No phone buzz: it read as random buzzing (Oct 28 audit).
    ("typing", r"\b(typ(e|ed|ing)|keyboard)\b", "short burst of laptop keyboard typing, close"),
    ("writing", r"\b(wr(ite|ote|iting)|pen|pencil|scribbl\w*)\b", "pencil scribbling on paper notebook, close"),
    ("paper", r"\b(paper|invoice|envelope|receipt)\b", "paper sheet rustle and slide on a desk"),
    ("door", r"\b(door|bell|walked in|came in)\b", "small shop door bell jingle as a door opens"),
    ("tool", r"\b(wrench|bolt|spoke)\b", "metal wrench set down on a wooden workbench, single clink"),
]
FOLEY_GAIN, FOLEY_GAP, FOLEY_MAX = 0.2, 20.0, 40
FOLEY_DEFAULT_ON = False   # off unless --foley (the user reviews it first)


def foley_plan(shots, segs):
    """At most one foley hit per FOLEY_GAP s, only when the SPOKEN line names the sound (never the image prompt / sfx text)."""
    by_idx = {sg["index"]: sg for sg in segs}
    plan, last = [], -99.0
    for sh in shots:
        txt = " ".join(str(by_idx[i].get("text") or "") for i in sh.get("beats", []) if i in by_idx).lower()
        kind = next((k for k, rx, _ in FOLEY_KINDS if re.search(rx, txt)), None)
        t = sh["start"] + min(0.4, sh["duration"] / 4)
        if kind and t - last >= FOLEY_GAP and len(plan) < FOLEY_MAX:
            plan.append((kind, round(t, 3)))
            last = t
    return plan


def scene_foley(shots, segs, key, work, fetch=None):
    """Generate (cached, one per kind) and place foley hits. Returns ([(path, t, gain, dur)], info)."""
    import urllib.request
    plan = foley_plan(shots, segs)
    info = {"planned": len(plan), "generated": 0, "errors": []}
    if not plan or not key:
        return [], info
    def _fetch(prompt):
        body = json.dumps({"text": prompt + ", sound effect only, no music, no voices", "duration_seconds": 1.5, "prompt_influence": 0.6}).encode()
        req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=body, method="POST",
                                     headers={"xi-api-key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    fetch = fetch or _fetch
    prompts = {k: pr for k, _, pr in FOLEY_KINDS}
    paths, out = {}, []
    for kind, t in plan:
        if kind not in paths:
            paths[kind] = None
            try:
                data = fetch(prompts[kind])
                if len(data) < 500:
                    raise ValueError("empty audio")
                pth = os.path.join(work, "foley_%s.mp3" % kind)
                open(pth, "wb").write(data)
                paths[kind] = pth
                info["generated"] += 1
            except Exception as e:
                info["errors"].append("%s: %s" % (kind, str(e)[:100]))
        if paths[kind]:
            out.append((paths[kind], t, FOLEY_GAIN, 1.5))
    info["placed"] = len(out)
    return out, info


def build_sfx_track(events, total, work, ambience=None):
    ambience = ambience or []
    if not events and not ambience:
        return None
    p = make_sfx(work) if events else {}
    ins, fc = [], []
    for k, (kind, t, gain) in enumerate(events):
        ins += ["-i", p[kind]]
        ms = int(round(t * 1000))
        fc.append("[%d:a]adelay=%d|%d,volume=%.2f[s%d]" % (k, ms, ms, gain, k))
    for j, (path, t, gain, dur) in enumerate(ambience):
        k = len(events) + j
        ins += ["-i", path]
        ms = int(round(t * 1000))
        fd = min(0.3, dur / 4)
        fc.append("[%d:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:%.3f,afade=t=in:d=%.3f,afade=t=out:st=%.3f:d=%.3f,adelay=%d|%d,volume=%.2f[s%d]"
                  % (k, dur, fd, max(0, dur - fd), fd, ms, ms, gain, k))
    events = list(events) + list(ambience)
    fc.append("%samix=inputs=%d:normalize=0:duration=longest,apad=whole_dur=%.3f,atrim=0:%.3f[o]" % ("".join("[s%d]" % k for k in range(len(events))), len(events), total, total))
    out = os.path.join(work, "sfx.wav")
    run(["ffmpeg", "-y", "-v", "error"] + ins + ["-filter_complex", ";".join(fc), "-map", "[o]", "-ar", "48000", "-ac", "2", out])
    return out



def env_key(name, path):
    k = os.environ.get(name)
    if not k and path and os.path.exists(path):
        for line in open(path):
            if line.startswith(name + "="):
                k = line.split("=", 1)[1].strip().strip('"')
    return k


MUSIC_STYLES = {
    "cinematic": "warm cinematic score, soft piano, felt strings, light pulse",
    "lofi": "warm lo-fi hip hop, dusty keys, soft vinyl, mellow drums",
    "orchestral": "small chamber orchestra, strings and french horn, hopeful",
    "acoustic": "warm acoustic guitar and soft piano, intimate, hopeful",
    "electronic": "soft modern electronic, warm pads, gentle synth arpeggio",
}


def music_plan(total, arc, style):
    """Composition plan from the story arc: tense cold open, calm under dialogue, build, swell at the turn, resolve."""
    base = MUSIC_STYLES.get(style, MUSIC_STYLES["cinematic"])
    hook = min(max(arc.get("hook_end") or 0.0, 3.0), total - 6) if total > 12 else total / 3
    turn = arc.get("turn") or total * 0.68
    turn = min(max(turn, hook + 3), total - 3)
    # per-beat cues (Resilia): each section changes instrumentation, not just intensity
    cut = [(0.0, hook, "Cold open cue", ["solo low piano", "tense", "suspended", "sparse"]),
           (hook, max(hook + 3, turn - 4), "Struggle cue", ["muted percussion pulse", "sterile", "understated", "steady"]),
           (max(hook + 3, turn - 4), turn, "Build cue", ["rising synth pad", "building", "anticipation"]),
           (turn, min(total, turn + 6), "Triumph cue", ["warm orchestra swell", "golden", "uplifting", "full strings"]),
           (min(total, turn + 6), total + 1.5, "Resolve cue", ["gentle piano and strings", "warm", "hopeful ending"])]
    chunks, carry = [], 0.0
    for a, b, name, mood in cut:
        d = b - a + carry
        if d < 3.0:
            carry = d
            continue
        carry = 0.0
        chunks.append({"text": "[%s]" % name, "duration_ms": int(round(d * 1000)),
                       "positive_styles": [base] + mood, "negative_styles": ["vocals", "singing", "lyrics", "harsh", "aggressive drums"]})
    if carry and chunks:
        chunks[-1]["duration_ms"] += int(carry * 1000)
    return clamp_music_chunks(chunks)


MUSIC_CHUNK_MS = (3000, 120000)  # ElevenLabs composition_plan limits per chunk (422 above 120 s)


def clamp_music_chunks(chunks, lo=MUSIC_CHUNK_MS[0], hi=MUSIC_CHUNK_MS[1]):
    """Split any section longer than the API limit into equal parts (<= hi) and keep every part >= lo."""
    out = []
    for c in chunks:
        d = int(c["duration_ms"])
        n = max(1, -(-d // hi))
        for k in range(n):
            part = dict(c, positive_styles=list(c.get("positive_styles", [])), negative_styles=list(c.get("negative_styles", [])))
            part["duration_ms"] = d // n + (d % n if k == n - 1 else 0)
            if n > 1:
                part["text"] = c["text"].rstrip("]") + (" (continues)]" if k else "]")
            out.append(part)
    for c in out:
        c["duration_ms"] = max(lo, min(hi, int(c["duration_ms"])))
    return out


MUSIC_USD_PER_MIN = 0.65      # billed: fal elevenlabs/music/v2 ~$4.2 for 6.7 min (Oct 28), rounded up; EL direct similar
MUSIC_CAP_DEFAULT = 1.00      # USD per job unless --music-cap; full episodes fall back to cache/library above this
ALLOW_STILL_ACTION = os.environ.get("CFA_ALLOW_STILL_ACTION", "") == "1"
MUSIC_CACHE = os.environ.get("CFA_MUSIC_CACHE") or os.path.expanduser("~/cfa-render-data/music_cache")


def music_cost(total):
    """Billed-cost estimate (USD) of composing a `total`-second score (plan adds ~1.5 s)."""
    return round((total + 2.0) / 60.0 * MUSIC_USD_PER_MIN, 3)


def music_cache_key(b, style):
    """One score per episode + style: reruns, re-edits and test clips reuse it (the bed loops / trims to length)."""
    ep = str(b.get("videoId") or b.get("episode") or b.get("title") or "untitled")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", "%s__%s" % (ep, style))[:120]


def music_cache_get(key, cache=None):
    p = os.path.join(cache or MUSIC_CACHE, key + ".mp3")
    return p if os.path.exists(p) and os.path.getsize(p) > 10000 else None


def music_cache_put(key, path, cache=None):
    c = cache or MUSIC_CACHE
    os.makedirs(c, exist_ok=True)
    dst = os.path.join(c, key + ".mp3")
    shutil.copy(path, dst)
    return dst


def music_guard(total, cap, spent=0.0):
    """(allowed, est_usd, reason). Paid composing only if est + already-spent <= cap."""
    est = music_cost(total)
    if cap is None or cap <= 0:
        return False, est, "music cap is $0 (cache/library only)"
    if spent + est > cap + 1e-9:
        return False, est, "est $%.2f + spent $%.2f > cap $%.2f" % (est, spent, cap)
    return True, est, "ok"


def compose_music(total, arc, style, key, work):
    """ElevenLabs Music (music_v2_5) score for this episode. Returns (path, plan) or (None, error)."""
    import requests
    plan = music_plan(total, arc, style)
    body = {"model_id": "music_v2_5", "composition_plan": {"positive_global_styles": ["instrumental", "underscore for spoken dialogue"],
            "negative_global_styles": ["vocals", "lyrics"], "chunks": plan}}
    for attempt in range(2):
        try:
            r = requests.post("https://api.elevenlabs.io/v1/music?output_format=mp3_44100_128", json=body,
                              headers={"xi-api-key": key}, timeout=240)
            if r.status_code == 200 and len(r.content) > 10000:
                out = os.path.join(work, "score.mp3")
                open(out, "wb").write(r.content)
                return out, plan
            err = "HTTP %s %s" % (r.status_code, r.text[:200])
        except Exception as e:
            err = str(e)[:200]
    return None, err


def compose_music_fal(total, arc, style, key, work):
    """Same composition plan via fal (elevenlabs/music/v2) when the ElevenLabs key lacks music permission."""
    import requests, time as _t
    plan = music_plan(total, arc, style)
    h = {"Authorization": "Key " + key}
    try:
        r = requests.post("https://queue.fal.run/elevenlabs/music/v2", headers=h, timeout=60,
                          json={"composition_plan": {"positive_global_styles": ["instrumental", "underscore for spoken dialogue"],
                                                     "negative_global_styles": ["vocals", "lyrics"], "chunks": plan}})
        r.raise_for_status()
        j = r.json()
        t0 = _t.time()
        while _t.time() - t0 < 300:
            st = requests.get(j["status_url"], headers=h, timeout=30).json()
            if st.get("status") == "COMPLETED":
                break
            if st.get("status") in ("FAILED", "ERROR"):
                return None, "fal music failed: %s" % str(st)[:160]
            _t.sleep(3)
        res = requests.get(j["response_url"], headers=h, timeout=60).json()
        url = (res.get("audio") or {}).get("url") or (res.get("audio_file") or {}).get("url")
        if not url:
            return None, "fal music: no audio in %s" % str(res)[:160]
        out = os.path.join(work, "score.mp3")
        open(out, "wb").write(requests.get(url, timeout=120).content)
        return out, plan
    except Exception as e:
        return None, "fal music: " + str(e)[:200]


def lip_offsets(shots, d, voice, work):
    """Exact lip-sync timing: cross-correlate each talking clip's own audio with the voice track where it plays."""
    import numpy as np
    def pcm(args):
        raw = subprocess.run(["ffmpeg", "-v", "error"] + args + ["-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    out = []
    for x in shots:
        if x.get("mediaType") != "lipsync" or not x.get("media"):
            continue
        t = x["start"] + x.get("lip_offset", 0.0)
        c = pcm(["-i", os.path.join(d, x["media"])])
        if len(c) < 4000:
            out.append({"media": x["media"], "offset_ms": None, "note": "clip has no audio track"})
            continue
        v = pcm(["-ss", "%.3f" % max(0, t - 0.5), "-t", "%.3f" % (len(c) / 8000 + 1.0), "-i", voice])
        n = 1 << int(np.ceil(np.log2(len(v) + len(c))))
        cc = np.fft.irfft(np.fft.rfft(v, n) * np.conj(np.fft.rfft(c, n)), n)[:len(v)]
        lag = int(np.argmax(cc)) / 8000 - min(0.5, t)
        out.append({"media": x["media"], "plays_at": round(t, 3), "offset_ms": int(round(lag * 1000)), "pass": abs(lag) <= 0.045})
    return out


TRANSITION_POLICY = True
HARD_CUTS = os.environ.get("CFA_HARD_CUTS", "1") != "0"
MUSIC_UNDER_DB = (15.0, 19.0, 17.0)  # music (ducked) sits this many dB under the voice: min, max, target (was 18-22: too quiet to notice)


def smooth_transitions(shots):
    """Soft by default: dissolves between scenes, straight cuts inside a dialogue exchange (the J/L timing
    does the smoothing), a whip only into the turn/reveal."""
    for i, sh in enumerate(shots):
        if i == 0:
            continue
        prev = shots[i - 1]
        if sh.get("part") == "b":
            continue
        if sh.get("role") == "montage":  # milestone montage: quick hard cuts
            sh["transition_in"], sh["transition_duration"] = "cut", 0.0
            continue
        dlg = sh.get("mediaType") == "lipsync" and prev.get("mediaType") == "lipsync"
        if dlg:
            sh["transition_in"], sh["transition_duration"] = "cut", 0.0
        elif sh.get("role") == "turn" and sh.get("transition_in") == "whip":
            pass
        elif HARD_CUTS and sh.get("role") not in ("realization", "resolve"):
            sh["transition_in"], sh["transition_duration"] = "cut", 0.0   # hard cuts (Oct 28 motion audit: dissolves hid the cuts)
        elif sh.get("transition_in") in ("whip", "cut", "fadeblack") and not (sh.get("role") == "turn"):
            sh["transition_in"], sh["transition_duration"] = "dissolve", 0.45
    return shots


AUDIO_TAG_RE = re.compile(r"\[[^\]\n]{1,30}\]")


def strip_tag_words(words):
    """Drop ElevenLabs v4 audio tags ([sighs], [short pause]) from word lists so they never reach captions or alignment."""
    out, inside = [], False
    for w in words:
        t = str(w[0])
        if inside:
            inside = "]" not in t
            continue
        if t.startswith("["):
            inside = "]" not in t
            continue
        out.append(w)
    return out


MOTION_MIN = 0.6        # mean |frame difference| (0-255, 64-px gray) below this = near-frozen shot
CUT_COLOR_MAX = 70.0    # mean |RGB| jump across a cut (0-255) above this = jarring colour jump
CUT_POS_MAX = 0.30      # brightness-centroid shift across a cut (fraction of the frame) above this = jarring position jump


def _thumb(path, t, n=16):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % max(0.0, t), "-i", path, "-frames:v", "1", "-vf", "scale=%d:%d" % (n, n),
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    b = r.stdout
    return [(b[i], b[i + 1], b[i + 2]) for i in range(0, len(b) - 2, 3)] if len(b) >= n * n * 3 else None


def _centroid(px, n=16):
    lum = [(0.299 * r + 0.587 * g + 0.114 * b) for r, g, b in px]
    tot = sum(lum) or 1.0
    return (sum(v * (k % n) for k, v in enumerate(lum)) / tot / n, sum(v * (k // n) for k, v in enumerate(lum)) / tot / n)


def shot_motion(path, start, dur):
    """Mean absolute frame-to-frame difference inside one shot (0-255 on a 64-px grey proxy)."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", "%.3f" % start, "-t", "%.3f" % max(0.2, dur), "-i", path,
                        "-vf", "scale=64:-2,format=gray,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-f", "null", "-"], capture_output=True, text=True)
    vals = [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stderr)][1:]
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def motion_qa(path, shots):
    """Flag near-frozen shots and jarring cuts (colour or position jump) in the final video."""
    out = {"frozen": [], "jarring_cuts": [], "motion": []}
    for i, sh in enumerate(shots):
        a = float(sh["start"]) + float(sh.get("transition_duration") or 0) + 0.05
        b = float(sh["start"]) + float(sh["duration"]) - 0.05
        m = shot_motion(path, a, max(0.3, b - a))
        out["motion"].append(m)
        if m < MOTION_MIN:
            out["frozen"].append({"shot": sh.get("index", i), "motion": m, "type": sh.get("mediaType"),
                                  "fix": "animate this beat (image-to-video) or give the still parallax/idle motion"})
        if i + 1 < len(shots):
            nx = shots[i + 1]
            x0 = _thumb(path, float(nx["start"]) - 0.08)
            x1 = _thumb(path, float(nx["start"]) + float(nx.get("transition_duration") or 0) + 0.08)
            if x0 and x1 and len(x0) == len(x1):
                col = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) for p, q in zip(x0, x1)) / (3.0 * len(x0))
                c0, c1 = _centroid(x0), _centroid(x1)
                pos = ((c0[0] - c1[0]) ** 2 + (c0[1] - c1[1]) ** 2) ** 0.5
                if col > CUT_COLOR_MAX or pos > CUT_POS_MAX:
                    out["jarring_cuts"].append({"after_shot": sh.get("index", i), "colour_jump": round(col, 1), "position_jump": round(pos, 3)})
    return out


def _tok(t):
    t = t.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9'%$]+", "", t)
    if t.isdigit() and len(t) <= 3:
        t = _num_words(int(t))
    if re.fullmatch(r"[a-z]+hundred[a-z]+", t or ""):
        t = t.replace("hundred", "")       # "450" heard for "four-fifty" -> "fourfifty"
    return HOMOPHONES.get(t, t)


HOMOPHONES = {"d": "dee", "dea": "dee", "tier": "tear", "oclock": "o'clock"}   # Whisper spellings of the same sound


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _num_words(n):
    """Spoken form joined without spaces so '12' == 'twelve', '21' == 'twentyone' (script tokens get the same join)."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else _ONES[n % 10])
    return _ONES[n // 100] + "hundred" + ("" if n % 100 == 0 else _num_words(n % 100))


def whisper_words(path, key, work, tag):
    """OpenAI whisper-1 word timestamps for an audio file (mono 16k mp3 upload)."""
    import requests
    small = os.path.join(work, "whisper_%s.mp3" % tag)
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-b:a", "48k", small])
    with open(small, "rb") as f:
        r = requests.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": "Bearer " + key},
                          files={"file": ("a.mp3", f, "audio/mpeg")},
                          data={"model": "whisper-1", "response_format": "verbose_json", "timestamp_granularities[]": "word"}, timeout=180)
    r.raise_for_status()
    j = r.json()
    return [(w["word"], float(w["start"]), float(w["end"])) for w in j.get("words", [])], j.get("text", "")


def whisper_check(segs, words, wwords):
    """Match the script against what Whisper heard. Per line: matched ratio, missing/extra words, timing drift."""
    import difflib
    script = []
    for si, s in enumerate(segs):
        for t in AUDIO_TAG_RE.sub(" ", s["text"]).split():
            if _tok(t):
                script.append((_tok(t), si))
    heard = [(_tok(w[0]), w[1], w[2]) for w in wwords if _tok(w[0])]
    sm = difflib.SequenceMatcher(a=[x[0] for x in script], b=[x[0] for x in heard], autojunk=False)
    hit = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            hit[blk.a + k] = blk.b + k
    # script word -> EL timing (words list is in script order)
    elw = [(_tok(w[0]), w[1], w[2]) for w in words if _tok(w[0])]
    sm2 = difflib.SequenceMatcher(a=[x[0] for x in script], b=[x[0] for x in elw], autojunk=False)
    el_of = {}
    for blk in sm2.get_matching_blocks():
        for k in range(blk.size):
            el_of[blk.a + k] = blk.b + k
    lines, drifts = [], []
    for si, s in enumerate(segs):
        idx = [k for k, x in enumerate(script) if x[1] == si]
        if not idx:
            continue
        got = [k for k in idx if k in hit]
        missing = [script[k][0] for k in idx if k not in hit]
        d = [abs(heard[hit[k]][1] - elw[el_of[k]][1]) for k in got if k in el_of]
        drifts += d
        ratio = len(got) / len(idx)
        lines.append({"index": s["index"], "speaker": s.get("speaker"), "words": len(idx), "matched": round(ratio, 3),
                      "missing": missing[:8], "drift_ms": int(1000 * (sum(d) / len(d))) if d else None,
                      "first_word_heard": round(heard[hit[idx[0]]][1], 3) if idx[0] in hit else None,
                      "flag": ratio < 0.85})
    mm = sorted(drifts)
    return {"lines": lines, "flagged": [l["index"] for l in lines if l["flag"]],
            "match_overall": round(len(hit) / max(1, len(script)), 3),
            "median_drift_ms": int(1000 * mm[len(mm) // 2]) if mm else None,
            "p95_drift_ms": int(1000 * mm[int(len(mm) * 0.95)]) if mm else None}, hit, heard, script


def realign_words(words, segs, wwords, limit=0.25):
    """Snap caption word times to Whisper where EL alignment drifted > limit (matched words only)."""
    rep, hit, heard, script = whisper_check(segs, words, wwords)
    import difflib
    elt = [k for k, w in enumerate(words) if _tok(w[0])]
    sm = difflib.SequenceMatcher(a=[x[0] for x in script], b=[_tok(words[k][0]) for k in elt], autojunk=False)
    moved = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            si, wi = blk.a + k, elt[blk.b + k]
            if si in hit:
                h = heard[hit[si]]
                if abs(h[1] - words[wi][1]) > limit:
                    words[wi] = [words[wi][0], round(h[1], 3), round(max(h[2], h[1] + 0.05), 3)]
                    moved += 1
    return words, moved


def music_vs_voice(voice, music_stem, work):
    """dB the (ducked) music sits below the voice, measured while the voice is speaking."""
    try:
        def lufs(p):
            o = subprocess.run(["ffmpeg", "-hide_banner", "-i", p, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
            m = re.findall(r"I:\s+(-?[\d.]+) LUFS", o)
            return float(m[-1]) if m else None
        lv, lm = lufs(voice), lufs(music_stem)
        return round(lv - lm, 1) if lv is not None and lm is not None else None
    except Exception:
        return None


def music_gain_expr(total, tp):
    """Music bed builds toward the turning point, peaks just after it, then settles (dB -> linear)."""
    if not tp:
        return "pow(10,-18/20)"
    return ("pow(10,(if(lt(t,%.3f),-25+9*t/%.3f,if(lt(t,%.3f),-15,-20)))/20)" % (tp, max(tp, 0.1), tp + 6))


def build_audio(voice, music, total, out, work, sfx=None, turn=None):
    """Voice + music bed (builds to the turn, ducked under the voice) + sparse SFX; 2-pass loudnorm to -14 LUFS / -1 dBTP."""
    mix = os.path.join(work, "mix.wav")
    ins = ["-i", voice]
    fc = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur=%.3f,atrim=0:%.3f,asplit=2[v][sc]" % (total, total)]
    parts = ["[v]"]
    if music:
        ins += ["-stream_loop", "-1", "-i", music]
        fc.append("[1:a]aformat=sample_rates=48000:channel_layouts=stereo,aloop=loop=-1:size=2e9,atrim=0:%.3f,"
                  "volume='%s':eval=frame,afade=t=in:d=0.15,afade=t=out:st=%.3f:d=2[m]" % (total, music_gain_expr(total, turn), max(0, total - 2)))
        fc.append("[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400:makeup=1[duck]")
        parts.append("[duck]")
    else:
        fc[0] = fc[0].replace(",asplit=2[v][sc]", "[v]")
    if sfx:
        ins += ["-i", sfx]
        fc.append("[%d:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.45[fx]" % (2 if music else 1))
        parts.append("[fx]")
    if len(parts) > 1:
        fc.append("%samix=inputs=%d:duration=first:normalize=0[a]" % ("".join(parts), len(parts)))
    else:
        fc.append("[v]anull[a]")
    run(["ffmpeg", "-y", "-v", "error"] + ins + ["-filter_complex", ";".join(fc), "-map", "[a]", "-ar", "48000", mix])
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", mix, "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = loudnorm_json(r.stderr)
    af = ("loudnorm=I=-14:TP=-1:LRA=11:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:"
          "offset=%s:linear=true" % (m["input_i"], m["input_tp"], m["input_lra"], m["input_thresh"], m["target_offset"]))
    run(["ffmpeg", "-y", "-v", "error", "-i", mix, "-af", af + ",aresample=48000", "-c:a", "aac", "-b:a", "192k", out])


def sharpness_check(clips, lut, work):
    """Edge energy (mean |Laplacian|) of mid-shot frames before vs after the LUT. The grade must not soften:
    ratio >= 0.97 passes. Returns {"ratio", "pass", "samples"} or None when there is no LUT."""
    if not lut or not clips:
        return None
    import numpy as np
    def edge(clip, vf):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.2f" % max(0.0, media_duration(clip) / 2), "-i", clip,
                            "-frames:v", "1", "-vf", (vf + "," if vf else "") + "scale=960:540,format=gray",
                            "-f", "rawvideo", "-"], capture_output=True)
        a = np.frombuffer(r.stdout, np.uint8)
        if a.size != 960 * 540:
            return None
        a = a.reshape(540, 960).astype(np.float32)
        lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
        return float(np.abs(lap).mean())
    picks = [clips[int(k * (len(clips) - 1) / 2)] for k in range(3)] if len(clips) >= 3 else clips
    out = []
    for c in dict.fromkeys(picks):
        b0, b1 = edge(c, ""), edge(c, "lut3d=file='%s':interp=tetrahedral" % lut.replace("'", r"\'"))
        if b0 and b1:
            out.append(round(b1 / b0, 4))
    if not out:
        return None
    ratio = min(out)
    return {"ratio": ratio, "pass": ratio >= 0.97, "samples": out}


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


def trim_to_seconds(d, b, segs, words, total, max_s, work, from_s=0.0):
    """Test-clip mode: keep the beats from `from_s` whose end <= from_s + max_s (always >= 1), cut voice/words to match
    and shift the kept window to start at 0."""
    keep = []
    from_s = max(0.0, from_s or 0.0)
    for sg in segs:
        if from_s and sg.get("start") is not None and sg["start"] < from_s - 0.05:
            continue
        e = sg.get("end")
        if keep and (e is None or e > from_s + max_s):
            break
        keep.append(sg)
    end = min(total, max(x.get("end") or 0 for x in keep) + 0.35)
    out = os.path.join(d, "voiceover_test.wav")
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % from_s, "-i", os.path.join(d, b["voiceover"]), "-t", "%.3f" % (end - from_s), out])
    b["voiceover"] = os.path.basename(out)
    words = [[w[0], round(w[1] - from_s, 3), round(w[2] - from_s, 3)] + list(w[3:]) for w in words if w[1] >= from_s - 0.02 and w[2] <= end + 0.05]
    if from_s:
        for sg in keep:
            for k in ("start", "end"):
                if sg.get(k) is not None:
                    sg[k] = round(max(0.0, sg[k] - from_s), 3)
    info = {"max_seconds": max_s, "from_seconds": from_s, "beats": len(keep), "of_beats": len(segs), "seconds": round(end - from_s, 2),
            "first_beat": keep[0].get("index")}
    log("test clip: %d of %d beats from %.1fs, %.1fs" % (len(keep), len(segs), from_s, end - from_s))
    return keep, words, media_duration(out), info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", help="CFA_FinalEdit_*.zip (or unpacked folder, or JSON-with-base64)")
    ap.add_argument("-o", "--out", default="render-out")
    ap.add_argument("--vertical", action="store_true", help="1080x1920 instead of 1920x1080")
    ap.add_argument("--music-style", default=None, help="score style: " + ", ".join(MUSIC_STYLES) + ", none")
    ap.add_argument("--no-score", action="store_true", help="do not compose an ElevenLabs score (use --music file if given)")
    ap.add_argument("--no-beat-grades", action="store_true", help="one grade for the whole episode (no per-beat cool/sterile/golden)")
    ap.add_argument("--no-drift-split", action="store_true", help="keep long stills as one shot (no 3-4 s drift parts)")
    ap.add_argument("--no-whisper", action="store_true", help="skip the Whisper caption alignment / line check")
    ap.add_argument("--raw-transitions", action="store_true", help="use the EDL transitions as-is (no smoothing policy)")
    ap.add_argument("--music", help="optional background music file (ducked under the voice)")
    ap.add_argument("--no-grok", action="store_true", help="skip Grok, use the deterministic edit")
    ap.add_argument("--model", default="grok-4.3")
    ap.add_argument("--keys-env", default="/home/box/secrets/cfa_keys.env", help="optional env file for XAI_API_KEY")
    ap.add_argument("--caption-style", choices=CAPTION_STYLES, help="override Grok's caption preset")
    ap.add_argument("--min-hold", type=float, default=MIN_HOLD, help="min seconds per shot; short beats are merged (default 3.75)")
    ap.add_argument("--beat-pause", type=float, default=0.6, help="min silence between beats, padded from timestamps (0 = off)")
    ap.add_argument("--sentence-pause", type=float, default=0.45, help="min silence after a sentence inside a beat (0 = off)")
    ap.add_argument("--no-title", action="store_true", help="(default) no title card")
    ap.add_argument("--title", action="store_true", default=TITLE_DEFAULT_ON, help="opt back in to the opening title card")
    ap.add_argument("--lut", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "luts", "cfa_warm.cube"), help="shared .cube grade")
    ap.add_argument("--no-lut", action="store_true")
    ap.add_argument("--grok-title", action="store_true", help="let Grok write the title/thumbnail text (default: bundle title only)")
    ap.add_argument("--notes", default="", help="re-edit notes passed to Grok's edit plan")
    ap.add_argument("--no-sfx", action="store_true", help="skip whooshes / riser / impact")
    ap.add_argument("--music-cap", type=float, default=float(os.environ.get("CFA_MUSIC_CAP", MUSIC_CAP_DEFAULT)),
                    help="max billed USD for composing a score (0 = cache/library only); cached per episode+style")
    ap.add_argument("--i2v", choices=["off"] + sorted(I2V_MODELS), default=os.environ.get("CFA_I2V", "off"),
                    help="idle micro-motion image-to-video on stills via fal (paid; default off)")
    ap.add_argument("--i2v-cap", type=float, default=float(os.environ.get("CFA_I2V_CAP", "0")), help="max est. USD for i2v clips")
    ap.add_argument("--max-seconds", type=float, default=float(os.environ.get("CFA_MAX_SECONDS", "0")),
                    help="test-clip mode: render only the beats that end within this many seconds (0 = whole episode)")
    ap.add_argument("--from-seconds", type=float, default=float(os.environ.get("CFA_FROM_SECONDS", "0")),
                    help="test-clip mode: window starts at this voice time (beats before it are dropped)")
    ap.add_argument("--total-cap", type=float, default=float(os.environ.get("CFA_TOTAL_CAP", "0")),
                    help="hard cap (USD) on everything this render bills (music + i2v); 0 = per-item caps only")
    ap.add_argument("--foley", action="store_true", default=FOLEY_DEFAULT_ON, help="add sparse foley hits (typing, pencil, paper, door, tool) from the spoken lines; off by default")
    ap.add_argument("--no-ambience", action="store_true", help="skip per-scene ElevenLabs ambience from the director's sfx text")
    ap.add_argument("--no-end-card", action="store_true")
    ap.add_argument("--captions", action="store_true", help="burn in captions/overlays/end card (off: zero on-screen text)")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args()

    ensure_ffmpeg()
    global CAPTIONS_ON
    CAPTIONS_ON = CAPTIONS_ON or a.captions
    global GROK_TITLE
    GROK_TITLE = bool(a.grok_title)
    global LUT_PATH
    LUT_PATH = None if a.no_lut or not os.path.exists(a.lut) else os.path.abspath(a.lut)
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cfa-render-")
    W, H = (1080, 1920) if a.vertical else (1920, 1080)
    d, b = load_bundle(a.bundle, work)
    voice = os.path.join(d, b["voiceover"])
    total = media_duration(voice)
    if total <= 0:
        raise SystemExit("voiceover missing or unreadable")
    words = strip_tag_words([w for w in (b.get("words") or []) if isinstance(w, list) and len(w) == 3])
    segs = sorted(b["segments"], key=lambda s: s["index"])
    for s in segs:
        if s.get("media") and not os.path.exists(os.path.join(d, s["media"])):
            s["media"] = None
    fill_timings(segs, words, total)
    test_clip = None
    if a.max_seconds and a.max_seconds > 0:
        segs, words, total, test_clip = trim_to_seconds(d, b, segs, words, total, a.max_seconds, work, a.from_seconds)
        voice = os.path.join(d, b["voiceover"])
    if a.total_cap and a.total_cap > 0:
        a.music_cap = min(a.music_cap, a.total_cap)
        a.i2v_cap = min(a.i2v_cap, a.total_cap)
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
    global SUBJECT_KEY
    SUBJECT_KEY = key if (key and not a.no_grok) else None
    source, problems, usage = "fallback", [], {}
    edl = None
    if key and not a.no_grok:
        for attempt in range(2):
            try:
                raw, usage = grok_edl(b, base_shots, key, a.model, notes=a.notes or "")
                edl, problems = validate_edl(raw, b, base_shots)
                source = "grok:" + a.model
                break
            except Exception as e:
                problems.append("grok attempt %d failed: %s" % (attempt + 1, str(e)[:200]))
    if edl is None:
        edl, _ = validate_edl(fallback_edl(b, base_shots), b, base_shots)
    if a.caption_style:
        edl["caption_style"]["preset"] = a.caption_style
    if a.no_title or not a.title:   # fix (b): no title slide by default; the audience gets the topic from what they hear and see
        edl["title_card"]["enabled"] = False
    if a.no_end_card or not CAPTIONS_ON:   # no text: the end card (text only) goes too
        edl["end_card"]["enabled"] = False
    PHRASE = b.get("shotPlan") == "phrase"   # tool planned one new image per phrase: no re-angled splits of a still
    if not PHRASE:
        edl["shots"] = split_punch_ins(edl["shots"], words)
    if not a.no_drift_split and not PHRASE:
        edl["shots"] = split_drift(edl["shots"], words, segs=segs)
    by_media = {s.get("media"): s for s in segs if s.get("mediaType") == "lipsync" and s.get("media")}
    for x in edl["shots"]:
        if x.get("mediaType") == "lipsync" and x.get("media") in by_media:
            x["lip_offset"] = round(max(0.0, by_media[x["media"]]["start"] - x["start"]), 3)
    if not a.raw_transitions:
        edl["shots"] = smooth_transitions(edl["shots"])
    tp_shot = next((x for x in edl["shots"] if x.get("role") == "turn"), None)
    hook_last = [x for x in edl["shots"] if x.get("role") == "hook"]
    edl["arc_times"] = {"hook_end": round(hook_last[-1]["end"], 3) if hook_last else 0.0,
                        "turn": round(tp_shot["start"], 3) if tp_shot else None}
    bt = next((sg for sg in segs if sg.get("role") == "turn" and sg.get("start") is not None), None)
    if bt:  # the script marks its own reveal: music swell and the turn role follow the writer, not the EDL guess
        edl["arc_times"]["turn"] = round(bt["start"], 3)
        for x in edl["shots"]:
            if x.get("role") == "turn" and not (x["start"] - 0.3 <= bt["start"] < x["end"]):
                x["role"] = "tension"
            elif x["start"] - 0.3 <= bt["start"] < x["end"] and x.get("part") != "b":
                x["role"] = "turn"
        edl["shots"] = smooth_transitions(edl["shots"]) if not a.raw_transitions else edl["shots"]
    mont = detect_montage(segs, total)
    for x in edl["shots"]:
        if x.get("role") in ("tension", "resolve") and any(x["start"] - 0.3 <= sg["start"] < x["end"] for sg in mont):
            x["role"] = "montage"
    if mont and not a.raw_transitions:
        edl["shots"] = smooth_transitions(edl["shots"])
    if PHRASE:
        apply_shot_plan(edl["shots"], segs)
    assign_grades(edl["shots"], not a.no_beat_grades)
    edl["source"] = source
    edl["pauses_added"] = round(added, 3)
    json.dump(edl, open(os.path.join(a.out, "edl.json"), "w"), indent=1)
    log("EDL from", source, "| problems:", problems or "none")

    # shots
    clips, last_media = [], None
    shots = edl["shots"]
    i2v_info = {"mode": a.i2v, "clips": 0, "est_usd": 0.0}
    if PHRASE:
        mode = episode_motion_model(b, a)
        reserve = music_reserve(b, a)
        cap = max(0.0, (a.total_cap - getattr(a, "spent_usd", 0.0) - reserve) if a.total_cap else a.i2v_cap)
        acts, est = action_i2v_plan(shots, mode, cap)
        fk = env_key("FAL_KEY", a.keys_env)
        i2v_info.update(mode=mode, planned=len(acts), est_usd=est, cap_usd=round(cap, 2),
                        skipped=[x.get("beats") for x in shots if x.get("i2v_skipped_cost")], music_reserve_usd=reserve)
        need = [x for x in shots if x.get("i2v_skipped_cost")]
        if need and not ALLOW_STILL_ACTION:
            raise ActionShotDegraded("action shot(s) %s need $%.2f of motion but only $%.2f is left under the cap (music reserve $%.2f); "
                                     "raise the cap or pass --allow-still-action. Nothing was billed for motion."
                                     % ([x.get("beats") for x in need], sum(x["i2v_skipped_cost"] for x in need), cap, reserve))
        n = 0
        refs = b.get("charRefs") if isinstance(b.get("charRefs"), dict) else {}
        xk = os.environ.get("XAI_API_KEY") or env_key("XAI_API_KEY", a.keys_env)
        checks = []
        if acts and not fk:
            i2v_info["degraded"] = [x.get("beats") or x.get("media") for x in acts]
            log("ACTION SHOT DEGRADED TO A STILL: no FAL key for", i2v_info["degraded"])
        for x in acts if fk else []:
            who = (x.get("one_char") or "the character").title()
            ref = refs.get(x.get("one_char") or "") or refs.get(who)
            src_img = os.path.join(d, x["media"])
            unit = i2v_cost(mode, x.get("duration"))
            for t in range(I2V_RETRY_CAP + 1):
                if t and a.total_cap and getattr(a, "spent_usd", 0.0) + unit + reserve > a.total_cap + 1e-9:
                    checks.append({"media": x["media"], "try": t, "stopped": "cap"}); break
                try:
                    out_mp4 = os.path.join(work, "act_%d_%d.mp4" % (n, t))
                    i2v_clip(src_img, mode, fk, out_mp4, prompt=action_prompt(x) + (" STRICT, previous try failed: %s." % "; ".join(checks[-1]["why"]) if t and checks and checks[-1].get("why") else ""),
                             ref_url=ref, shot_s=x.get("duration"), who=who)
                    a.spent_usd = getattr(a, "spent_usd", 0.0) + unit
                except Exception as e:
                    i2v_info.setdefault("errors", []).append(str(e)[:120]); break
                ck = {"ok": True, "why": []}
                if xk:
                    try:
                        ck = i2v_frame_check(out_mp4, xk, ref, 1, line=x.get("line") or "", prior=src_img)
                    except Exception as e:
                        ck = {"ok": True, "why": [], "error": str(e)[:80]}
                checks.append(dict(ck, media=x["media"], try_=t))
                log("i2v check", x["media"], "try", t, "ok" if ck["ok"] else ck["why"])
                if ck["ok"]:
                    x["media"] = out_mp4; x["mediaType"] = "video"; n += 1; break
            if x.get("mediaType") != "video":
                x["i2v_rejected"] = True   # every try failed the frame check, errored or hit the cap
                i2v_info.setdefault("degraded", []).append(x.get("beats") or x.get("media"))
                log("ACTION SHOT DEGRADED TO A STILL:", x.get("beats"), (x.get("line") or "")[:60])
        i2v_info["checks"] = checks
        i2v_info["ref"] = bool(refs)
        i2v_info["clips"] = n
    elif a.i2v != "off":
        pick, est = i2v_plan(shots, a.i2v, a.i2v_cap)
        fk = env_key("FAL_KEY", a.keys_env)
        i2v_info.update(planned=len(pick), est_usd=est)
        made = {}
        for m in pick if fk else []:
            try:
                made[m] = i2v_clip(os.path.join(d, m), a.i2v, fk, os.path.join(work, "i2v_%s.mp4" % re.sub(r"\W", "_", m)))
                a.spent_usd = getattr(a, "spent_usd", 0.0) + I2V_MODELS[a.i2v][1]
            except Exception as e:
                i2v_info.setdefault("errors", []).append(str(e)[:120])
        for x in shots:
            if x.get("media") in made:
                x["media"], x["mediaType"] = made[x["media"]], "video"
        i2v_info["clips"] = len(made)
    if STILL_MOTION == "parallax":
        import hashlib
        dc = os.path.expanduser(os.environ.get("CFA_DEPTH_CACHE", "~/cfa-render-data/depth_cache"))
        os.makedirs(dc, exist_ok=True)
        srcs = sorted({os.path.join(d, x["media"]) for x in shots if x.get("media") and (x.get("mediaType") or "image") == "image"})
        pairs = [(sp, os.path.join(dc, hashlib.sha1(open(sp, "rb").read()).hexdigest()[:16] + ".png")) for sp in srcs if os.path.exists(sp)]
        log("stage: depth maps for %d stills (%s)" % (len(pairs), "model" if DEPTH_PY else "synthetic"))
        dmap = depth_maps(pairs, work)
        for x in shots:
            if x.get("media"):
                x["_depth"] = dmap.get(os.path.join(d, x["media"]))
    if not PHRASE:
        assign_directions(shots)
    for i, shot in enumerate(shots):
        nxt = shots[i + 1]["transition_duration"] if i + 1 < len(shots) else 0.0
        src, kind = None, "image"
        if shot.get("media"):
            src, kind = os.path.join(d, shot["media"]), shot.get("mediaType") or "image"
            last_media = (src, kind)
        elif same_line_media(shots, i):  # a gap is filled from ITS OWN line (tighter crop), never by holding the neighbour's shot
            sm = same_line_media(shots, i)
            src, kind = os.path.join(d, sm["media"]), sm.get("mediaType") or "image"
            shot["motion"] = "zoom_in"; shot["fallback_same_line"] = True
            log("gap shot", i, "filled from its own line:", sm["media"])
        elif last_media:  # last resort: hold the previous visual rather than going black (reported as a hole)
            src, kind = last_media
            shot["held_neighbour"] = True
            log("HOLE: shot", i, "holds the neighbouring shot (no image on its line)")
        else:  # nothing before it (missing opening scene): borrow the next available visual
            nx = next((x for x in shots[i + 1:] if x.get("media")), None)
            if nx:
                src, kind = os.path.join(d, nx["media"]), nx.get("mediaType") or "image"
        if kind == "lipsync" and shot.get("mediaType") != "lipsync":
            kind = "video"  # a borrowed talking clip is just footage here
        out = os.path.join(work, "shot_%03d.mp4" % i)
        f0 = round(shot["start"] * FPS)
        f1 = round((shot["end"] + nxt) * FPS) if i + 1 < len(shots) else round(total * FPS) + 2
        render_shot(src, kind, shot, W, H, out, max(2, f1 - f0))
        clips.append(out)
        log("shot %d/%d beats %s %s %s %.2fs" % (i + 1, len(shots), shot["beats"], kind, shot["motion"], shot["duration"]))

    # assemble: xfade chain (offset = next cut time) + captions
    ass = os.path.join(work, "captions.ass")
    log("stage: captions")
    oa_key = None if a.no_whisper else env_key("OPENAI_API_KEY", a.keys_env)
    whisper = {"enabled": bool(oa_key)}
    if oa_key:
        try:
            ww, _ = whisper_words(voice, oa_key, work, "voice")
            words, moved = realign_words(words, segs, ww)
            whisper["voice_pass"] = {"words_heard": len(ww), "caption_words_realigned": moved}
            log("whisper voice pass: %d words, %d caption times snapped" % (len(ww), moved))
        except Exception as e:
            whisper["voice_pass_error"] = str(e)[:200]
    cues = build_ass(words, segs, edl, W, H, total, ass)
    ass_esc_path = ass.replace("\\", "/").replace(":", "\\:")
    grade = ("lut3d=file='%s':interp=tetrahedral," % LUT_PATH.replace("'", r"\'")) if LUT_PATH else ""
    tail_filter = "fps=%d,trim=0:%.3f,setpts=PTS-STARTPTS,%ssubtitles='%s'" % (FPS, total, grade, ass_esc_path)
    audio = os.path.join(work, "audio.m4a")
    log("stage: mixing")
    events = [] if a.no_sfx else sfx_events(edl["shots"], edl["arc_times"])
    amb, amb_info = [], {"scenes": 0, "generated": 0, "errors": [], "skipped": "off" if a.no_ambience else ""}
    if not a.no_ambience:
        try:
            amb, inf = scene_ambience(shots, segs, env_key("ELEVENLABS_API_KEY", a.keys_env), work)
            amb_info.update(inf)
        except Exception as e:
            amb_info["errors"].append(str(e)[:160])
    foley_info = {"skipped": "off (default; pass --foley)"}
    if a.foley and not a.no_sfx:
        try:
            fol, foley_info = scene_foley(shots, segs, env_key("ELEVENLABS_API_KEY", a.keys_env), work)
            amb = list(amb) + fol
        except Exception as e:
            foley_info = {"errors": [str(e)[:160]]}
    sfx = build_sfx_track(events, total, work, amb)
    music_info = {"source": None}
    bmus = b.get("music")
    style = (b.get("musicStyle") or a.music_style or "cinematic").lower()
    if bmus and os.path.exists(os.path.join(d, bmus)):
        a.music, music_info = os.path.join(d, bmus), {"source": "bundle", "file": bmus}
    elif style != "none" and not a.no_score:
        ckey = music_cache_key(b, style)
        cached = music_cache_get(ckey)
        if a.total_cap and a.total_cap > 0:
            a.music_cap = max(0.0, min(a.music_cap, a.total_cap - getattr(a, "spent_usd", 0.0)))
        ok, est, why = music_guard(total, a.music_cap, getattr(a, "spent_usd", 0.0))
        if cached:
            a.music = cached
            shutil.copy(cached, os.path.join(a.out, "score.mp3"))
            music_info = {"source": "cache", "cache_key": ckey, "style": style, "billed_usd": 0.0}
        elif not ok:
            log("music guard: not composing (%s); using %s" % (why, "library track" if a.music else "no music bed"))
            music_info = {"source": "library" if a.music else None, "guard": why, "est_usd": est, "billed_usd": 0.0}
        else:
            el = env_key("ELEVENLABS_API_KEY", a.keys_env)
            fk = env_key("FAL_KEY", a.keys_env)
            pth, plan, src, err1 = None, None, None, "no ELEVENLABS_API_KEY"
            if el:
                log("stage: composing score (%s, est $%.2f, cap $%.2f)" % (style, est, a.music_cap))
                pth, plan = compose_music(total, edl["arc_times"], style, el, work)
                src = "elevenlabs music_v2_5"
                if not pth:
                    err1, pth = plan, None
            if not pth and fk:
                pth, plan = compose_music_fal(total, edl["arc_times"], style, fk, work)
                src = "fal elevenlabs/music/v2"
            if pth:
                a.music = pth
                shutil.copy(pth, os.path.join(a.out, "score.mp3"))
                music_cache_put(ckey, pth)
                a.spent_usd = getattr(a, "spent_usd", 0.0) + est
                music_info = {"source": src, "style": style, "cache_key": ckey, "billed_usd": est, "cap_usd": a.music_cap,
                              "plan": [(c["text"], c["duration_ms"]) for c in plan]}
                if src.startswith("fal") and el:
                    music_info["elevenlabs_direct_error"] = str(err1)[:120]
            else:
                music_info = {"source": "library" if a.music else None, "score_error": [str(err1)[:160], str(plan)[:160] if plan else "no FAL_KEY"],
                              "billed_usd": 0.0}
    elif style == "none":
        a.music = None
    if a.music and not os.path.exists(a.music):
        log("warning: music file not found (%s); rendering without a music bed" % a.music)
        a.music = None
    if a.music:
        try:
            def _stem(src, tag):
                stem = os.path.join(work, "music_stem_%s.wav" % tag)
                run(["ffmpeg", "-y", "-v", "error", "-i", src, "-i", voice, "-filter_complex",
                     "[0:a]aloop=loop=-1:size=2e9,atrim=0:%.3f,volume='%s':eval=frame[m];[1:a]aformat=channel_layouts=stereo[sc];"
                     "[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400:makeup=1[d]" % (total, music_gain_expr(total, edl["arc_times"].get("turn"))),
                     "-map", "[d]", stem])
                return music_vs_voice(voice, stem, work)
            gap = _stem(a.music, "raw")
            music_info["below_voice_db_raw"] = gap
            if gap is not None and not (MUSIC_UNDER_DB[0] <= gap <= MUSIC_UNDER_DB[1]):
                adj = os.path.join(work, "music_adj.wav")
                run(["ffmpeg", "-y", "-v", "error", "-i", a.music, "-af", "volume=%.1fdB" % (gap - MUSIC_UNDER_DB[2]), adj])
                a.music = adj
                gap = _stem(adj, "adj")
            music_info["below_voice_db"] = gap
        except Exception as e:
            music_info["measure_error"] = str(e)[:120]
    build_audio(voice, a.music, total, audio, work, sfx, edl["arc_times"].get("turn"))
    final = os.path.join(a.out, "final.mp4")
    log("stage: encoding")
    encode_video(clips, edl["shots"], total, tail_filter, audio, final, work)

    # thumbnail: chosen shot (caption-free intermediate), big title text
    th = edl["thumbnail"]
    si = th["shot_index"] - 1
    thumb = os.path.join(a.out, "thumbnail.jpg")
    make_thumbnail(clips[si], shots[si]["duration"] * 0.6, th["text"], a.vertical, work, thumb)

    pr = probe(final)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    au = [s for s in pr["streams"] if s["codec_type"] == "audio"]
    try:
        sharp = sharpness_check(clips, LUT_PATH, work)
    except Exception as e:
        sharp = {"error": str(e)[:200]}
    if sharp and sharp.get("pass") is False:
        log("WARNING: LUT grade lowered edge energy to %.3f of the source" % sharp["ratio"])
    if oa_key:
        try:
            ww, txt = whisper_words(final, oa_key, work, "final")
            chk, _, _, _ = whisper_check(segs, words, ww)
            lip = []
            for x in shots:
                if x.get("mediaType") == "lipsync":
                    sg = by_media.get(x["media"])
                    ln = next((l for l in chk["lines"] if sg and l["index"] == sg["index"]), None)
                    if ln and ln["first_word_heard"] is not None:
                        lip.append({"media": x["media"], "clip_audio_start": round(x["start"] + x.get("lip_offset", 0), 3),
                                    "speech_heard": ln["first_word_heard"],
                                    "offset_ms": int(1000 * (ln["first_word_heard"] - x["start"] - x.get("lip_offset", 0)))})
            chk["lipsync_timing"] = lip
            whisper["final_pass"] = chk
            log("whisper final pass: match %.3f, flagged lines %s" % (chk["match_overall"], chk["flagged"]))
        except Exception as e:
            whisper["final_pass_error"] = str(e)[:200]
    try:
        lipsync_check = lip_offsets(shots, d, voice, work)
    except Exception as e:
        lipsync_check = [{"error": str(e)[:160]}]
    try:
        mqa = motion_qa(final, shots)
        if mqa["frozen"] or mqa["jarring_cuts"]:
            log("motion QA: %d near-frozen shot(s), %d jarring cut(s)" % (len(mqa["frozen"]), len(mqa["jarring_cuts"])))
    except Exception as e:
        mqa = {"error": str(e)[:160]}
    gate = motion_gate(final, median_max=GATE_MEDIAN_PHRASE_MAX if PHRASE else None)
    st = [x.get("_stretch") for x in shots if x.get("_stretch")]
    gate["distortion"] = {"max_stretch": round(max(st), 4) if st else None, "shots": len(st),
                          "over": sum(1 for v in st if v > GATE_STRETCH_MAX), "limit": GATE_STRETCH_MAX}
    if st and max(st) > GATE_STRETCH_MAX:
        gate["fails"].append("still warp stretch %.3f > %.2f" % (max(st), GATE_STRETCH_MAX))
        gate["pass"] = False
    if PHRASE:
        gate["similarity"] = similarity_gate(final, shots)
        gate["phrase_align"] = phrase_alignment(shots)
        gate["one_character"] = one_character_gate(segs, {bb for x in shots for bb in (x.get("beats") or [])})
        if not gate["one_character"]["pass"]:
            gate["fails"].append("more than one character in beats %s" % gate["one_character"]["fails"]); gate["pass"] = False
        if not gate["similarity"]["pass"]:
            gate["fails"].append("re-angled shots %s" % gate["similarity"]["fails"]); gate["pass"] = False
        if not gate["phrase_align"]["pass"]:
            gate["fails"].append("motion off its phrase by %.2fs" % gate["phrase_align"]["max_offset_s"]); gate["pass"] = False
        log("similarity gate:", "PASS" if gate["similarity"]["pass"] else "FAIL", gate["similarity"]["fails"], "| phrase align:", gate["phrase_align"])
    log("distortion gate:", "PASS" if not gate["distortion"]["over"] else "FAIL", gate["distortion"])
    if not CAPTIONS_ON and key and not os.environ.get("CFA_NO_TEXT_GATE"):
        try:
            tg = text_gate(final, key, allow_scene=True)
        except Exception as e:
            tg = {"pass": True, "error": str(e)[:120], "items": []}
        gate["text"] = tg
        if not tg["pass"]:
            gate["fails"].append("on-screen text %s" % [x.get("text") for x in tg["fails"]][:5]); gate["pass"] = False
        log("text gate:", "PASS" if tg["pass"] else "FAIL", tg.get("items"))
    if i2v_info.get("degraded"):
        gate["fails"].append("action shot(s) %s became stills (no character motion)" % i2v_info["degraded"]); gate["pass"] = False
    log("motion gate:", "PASS" if gate["pass"] else "FAIL " + "; ".join(gate["fails"]))
    report = {"test_clip": test_clip, "billed_usd_total": round(getattr(a, "spent_usd", 0.0), 3), "total_cap_usd": a.total_cap or None, "motion_gate": gate, "i2v": i2v_info, "final": final, "whisper": whisper, "motion_qa": mqa, "lipsync_sync": lipsync_check, "music": music_info, "thumbnail": thumb, "duration": float(pr["format"]["duration"]),
              "voice_duration": total, "resolution": "%sx%s" % (v["width"], v["height"]),
              "audio_streams": len(au), "lufs": measure_lufs(final), "edl_source": source,
              "edl_problems": problems, "grok_usage": usage, "beats": len(segs),
              "voice_raw_duration": voice_raw, "pauses_added": round(added, 3), "pause_count": len(pauses),
              "shots": [{"index": x["index"], "beats": x["beats"], "media": x["media"], "type": x["mediaType"],
                         "start": x["start"], "duration": x["duration"], "motion": x["motion"], "role": x.get("role"),
                         "part": x.get("part", ""), "transition": x["transition_in"], "xfade": x["transition_duration"], "plan_motion": x.get("plan_motion"), "plan_link": x.get("plan_link"), "plan_shot": x.get("plan_shot"), "one_char": x.get("one_char")} for x in shots],
              "arc": edl.get("arc"), "arc_times": edl.get("arc_times"), "sfx_events": [list(e) for e in events], "ambience": dict(amb_info, placed=len(amb)), "foley": foley_info,
              "punch_ins": sum(1 for x in shots if x.get("part") == "b"),
              "shot_lengths": sorted(round(x["duration"], 2) for x in shots),
              "avg_shot": round(total / len(shots), 3), "min_shot": min(x["duration"] for x in shots),
              "interpolated_beats": [s["index"] for s in segs if s.get("interpolated")],
              "caption_cues": cues, "padded_words": words, "render_seconds": round(time.time() - t0, 1),
              "lut": os.path.basename(LUT_PATH) if LUT_PATH else None, "sharpness": sharp}
    json.dump(report, open(os.path.join(a.out, "report.json"), "w"), indent=1)
    shutil.copy(ass, os.path.join(a.out, "captions.ass"))
    if not a.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    log("done: %s (%.2fs, voice %.2fs, %s LUFS) in %ss" % (final, report["duration"], total, report["lufs"], report["render_seconds"]))




GATE_MEDIAN_SHOT_MAX = 4.0     # s: fail if the median visible shot is longer
GATE_MEDIAN_PHRASE_MAX = 6.0   # s: phrase plan (one shot per new-content phrase, motivated move inside it)
GATE_CUT_DIFF = 18.0           # mean grey-level jump that reads as a cut (same-palette stills)
GATE_MOTION_MIN = 3.5          # px/s median in-frame motion, full 1280-px-wide frame (optical flow, cut samples excluded)


def motion_gate(path, maxsec=240, median_max=None):
    """Measure the final cut like a viewer: histogram cuts (Bhattacharyya > 0.35) and optical-flow motion between cuts."""
    import cv2, numpy as np
    cap = cv2.VideoCapture(path)
    fps = cap.get(5) or FPS
    step = max(1, round(fps / 6))
    prev = ph = None
    i, cuts, flow = 0, [0.0], []
    while True:
        ok, f = cap.read()
        if not ok or i / fps > maxsec:
            break
        if i % step == 0:
            g = cv2.cvtColor(cv2.resize(f, (320, 180)), cv2.COLOR_BGR2GRAY)
            h = cv2.calcHist([g], [0], None, [32], [0, 256]); cv2.normalize(h, h)
            if prev is not None:
                if cv2.compareHist(ph, h, cv2.HISTCMP_BHATTACHARYYA) > 0.35 or float(cv2.absdiff(prev, g).mean()) > GATE_CUT_DIFF:
                    cuts.append(i / fps)
                else:
                    fl = cv2.calcOpticalFlowFarneback(prev, g, None, .5, 3, 15, 3, 5, 1.2, 0)
                    flow.append(float(np.linalg.norm(fl, axis=2).mean()) * fps / step * 4.0)
            prev, ph = g, h
        i += 1
    cap.release()
    cuts.append(i / fps)
    d = [b - a for a, b in zip(cuts, cuts[1:]) if b - a > 0.3]
    med = float(np.median(d)) if d else 0.0
    mot = float(np.median(flow)) if flow else 0.0
    fails = []
    mm = median_max or GATE_MEDIAN_SHOT_MAX
    if med > mm:
        fails.append("median shot %.1fs > %.1fs" % (med, mm))
    if mot < GATE_MOTION_MIN:
        fails.append("in-frame motion %.1f px/s < %.1f" % (mot, GATE_MOTION_MIN))
    return {"pass": not fails, "fails": fails, "median_shot_s": round(med, 2), "shots": len(d),
            "motion_px_s": round(mot, 2), "static_pct": round(100.0 * sum(1 for x in flow if x < 1.2) / max(1, len(flow)), 1)}


# ── Idle micro-motion image-to-video (optional, default OFF until the user's test; paid via the fal queue) ──
I2V_MODELS = {   # est. USD per clip (~5-6 s); estimates, check fal pricing before raising caps
    "wan": ("fal-ai/wan/v2.2-a14b/image-to-video", 0.40),
    "hailuo": ("fal-ai/minimax/hailuo-02/standard/image-to-video", 0.27),
    # reference-conditioned: the character's sheet rides along as an element, so the face stays his (per-second price)
    "kling-ref": ("fal-ai/kling-video/o1/standard/reference-to-video", 0.42),
}
I2V_PER_S = {"kling-ref": 0.084}
I2V_RETRY_CAP = 2          # regenerations per action clip when the frame check fails (counted against the cap)


def i2v_duration(mode, shot_s):
    """Clip seconds requested: per-second models get the shortest length covering the shot (3-10 s)."""
    if mode in I2V_PER_S:
        import math
        return int(min(10, max(3, math.ceil((shot_s or 4) - 0.05))))
    return 6


def i2v_cost(mode, shot_s=None):
    if mode in I2V_PER_S:
        return round(I2V_PER_S[mode] * i2v_duration(mode, shot_s), 3)
    return I2V_MODELS[mode][1]


I2V_CHECK_SYS = ("You audit frames from one animated clip. For EACH frame count distinct people (face, head or torso, even partly at the edge; "
                 "hands alone do not count), transcribe any readable writing exactly (signs, labels, screens, paper), and score image quality 0-10 "
                 "(10 crisp and clean; lower for warped or melted faces, broken hands or extra fingers, deformed bodies, melted objects, blur, smears, artifacts). "
                 "Also say whether the person looks like the same character as the reference sheet (first image), score 0-10. "
                 "Judge strictly against the sheet: hair_match (same cut, colour, volume), face_match (same face shape, eyes, nose, skin tone), "
                 "mouth_open (true if in ANY frame the mouth is open or teeth show; the series keeps mouths closed), render_match (same rendering look as the sheet "
                 "AND as the source still if given: shading, materials, detail, proportions; false if the clip turns more realistic, flatter or a different style). "
                 "Props: phones (max phones visible in any frame), max_hands_per_person, duplicate_objects (an object shown twice), illogical (floating or impossible props). "
                 'JSON only: {"frames":[{"people":<int>,"text":["..."],"quality":<0-10>,"defects":["..."]}],"same_character":<0-10>,"hair_match":bool,"face_match":bool,'
                 '"mouth_open":bool,"render_match":bool,"phones":<int>,"max_hands_per_person":<int>,"duplicate_objects":["..."],"illogical":["..."]}')


def i2v_frame_check(mp4, key, sheet_url=None, expected=1, ask=None, line="", prior=None):
    """People count / stray text / distortion / identity on 3 frames of an i2v clip. Returns {ok, why[], ...}.
    `ask(messages)` can be injected for tests; otherwise one xAI vision call."""
    import base64, tempfile
    d = tempfile.mkdtemp()
    dur = media_duration(mp4) if not ask else 3.0
    imgs = []
    for k, t in enumerate((0.15, dur * 0.5, max(0.2, dur - 0.25))):
        p = os.path.join(d, "f%d.jpg" % k)
        if not ask:
            run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % t, "-i", mp4, "-frames:v", "1", "-vf", "scale=768:-2", p])
            imgs.append("data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode())
        else:
            imgs.append("frame%d" % k)
    content = [{"type": "text", "text": "Reference sheet first, then 3 frames of the clip. The clip shows: " + (line or "")[:200]}]
    if sheet_url:
        content.append({"type": "image_url", "image_url": {"url": sheet_url}})
    if prior:   # the source still: the clip must keep its exact look
        pu = prior if (ask or str(prior).startswith(("http", "data:"))) else "data:image/%s;base64,%s" % ("png" if prior.lower().endswith("png") else "jpeg", base64.b64encode(open(prior, "rb").read()).decode())
        content += [{"type": "text", "text": "Source still the clip was made from:"}, {"type": "image_url", "image_url": {"url": pu}}, {"type": "text", "text": "Clip frames:"}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in imgs]
    msgs = [{"role": "system", "content": I2V_CHECK_SYS}, {"role": "user", "content": content}]
    if ask:
        o = ask(msgs)
    else:
        body = json.dumps({"model": "grok-4.3", "response_format": {"type": "json_object"}, "max_tokens": 500, "messages": msgs}).encode()
        req = urllib.request.Request(XAI_URL, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.load(r)["choices"][0]["message"]["content"]
        o = json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip())
    fr = o.get("frames") or []
    why = []
    ppl = [int(f.get("people") or 0) for f in fr]
    if any(p != expected for p in ppl):
        why.append("people %s (want %d)" % (ppl, expected))
    txt = [t for f in fr for t in (f.get("text") or []) if str(t).strip()]
    if txt:
        why.append("on-screen text %s" % txt[:3])
    q = [float(f.get("quality") or 0) for f in fr]
    if q and min(q) < 7:
        why.append("distorted (quality %s: %s)" % (q, "; ".join(str(x) for f in fr for x in (f.get("defects") or []))[:120]))
    same = o.get("same_character")
    if sheet_url and same is not None and float(same) < 7:
        why.append("face drift (same_character %s)" % same)
    for k, bad, msg in (("hair_match", False, "hair differs from the sheet"), ("face_match", False, "face differs from the sheet"),
                        ("mouth_open", True, "mouth opens / teeth show"), ("render_match", False, "render look changed from the stills")):
        if o.get(k) is bad:
            why.append(msg)
    props = [str(v) for v in (o.get("duplicate_objects") or []) + (o.get("illogical") or []) if str(v).strip()]
    if int(o.get("phones") or 0) > max(1, expected):
        props.append("%s phones" % o.get("phones"))
    if int(o.get("max_hands_per_person") or 0) > 2:
        props.append("%s hands on one person" % o.get("max_hands_per_person"))
    if props:
        why.append("props: " + "; ".join(props[:3]))
    return {"ok": not why, "why": why, "people": ppl, "text": txt, "quality": q, "same_character": same}

I2V_PROMPT = ("Subtle idle motion only: slow breathing, a blink, slight head and hand movement, gentle camera drift. "
              "Mouth stays closed, no talking, same 3D Pixar style, same character, no text.")


def i2v_plan(shots, mode, cap):
    """Which stills get an idle i2v clip and the estimated cost; never over `cap` (USD)."""
    if mode in (None, "off") or mode not in I2V_MODELS:
        return [], 0.0
    _, unit = I2V_MODELS[mode]
    pick, est = [], 0.0
    seen = set()
    for x in shots:
        m = x.get("media")
        if not m or (x.get("mediaType") or "image") != "image" or m in seen:
            continue
        if est + unit > (cap or 0) + 1e-9:
            break
        seen.add(m); pick.append(m); est += unit
    return pick, round(est, 2)


def i2v_payload(mode, uri, prompt, ref_url=None, shot_s=None, who="the character"):
    if mode == "kling-ref":
        p = {"prompt": "Take @Image1 as the start frame. %s is @Element1: keep his face, hair, skin tone and outfit exactly as @Element1. %s"
                       % (who, prompt or I2V_PROMPT),
             "image_urls": [uri], "duration": str(i2v_duration(mode, shot_s)), "aspect_ratio": "16:9"}
        if ref_url:
            p["elements"] = [{"frontal_image_url": ref_url, "reference_image_urls": [uri]}]
        return p
    p = {"image_url": uri, "prompt": prompt or I2V_PROMPT}
    return p


def net_retry(fn, tries=4, base=2.0, sleep=None, post=False):
    """Retry a network call on connection/timeout errors with exponential backoff (2s, 4s, 8s).
    Only transport errors retry; a submitted job is never re-posted after a reply, so nothing is paid twice."""
    import time as _t
    sleep = sleep or _t.sleep
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            name = type(e).__name__
            transient = any(x in name for x in ("ConnectionError", "Timeout", "ChunkedEncoding", "SSLError", "ProtocolError"))
            if post:  # a POST retries only if the request never reached fal (no job, no charge)
                msg = str(e)
                transient = "ConnectTimeout" in name or "NewConnectionError" in msg or "NameResolution" in msg or "Failed to establish" in msg
            if not transient or k == tries - 1:
                raise
            log("fal network error (%s), retry %d/%d in %.0fs" % (name, k + 1, tries - 1, base * 2 ** k))
            sleep(base * 2 ** k)


def i2v_clip(img_path, mode, key, out, fetch=None, prompt=None, ref_url=None, shot_s=None, who="the character"):
    """One fal queue i2v job -> mp4 at `out`. `fetch(model, payload)` can be injected for tests."""
    import base64
    model, _ = I2V_MODELS[mode]
    uri = "data:image/png;base64," + base64.b64encode(open(img_path, "rb").read()).decode()
    payload = i2v_payload(mode, uri, prompt, ref_url, shot_s, who)
    if fetch:
        data = fetch(model, payload)
    else:
        import requests, time as _t
        h = {"Authorization": "Key " + key}
        j = net_retry(lambda: requests.post("https://queue.fal.run/" + model, headers=h, json=payload, timeout=60).json(), post=True)
        t0 = _t.time()
        while _t.time() - t0 < 600:
            st = net_retry(lambda: requests.get(j["status_url"], headers=h, timeout=30).json())
            if st.get("status") == "COMPLETED":
                break
            if st.get("status") in ("FAILED", "ERROR"):
                raise RuntimeError("i2v failed")
            _t.sleep(4)
        res = net_retry(lambda: requests.get(j["response_url"], headers=h, timeout=60).json())
        data = net_retry(lambda: requests.get((res.get("video") or {})["url"], timeout=180).content)
    open(out, "wb").write(data)
    return out


if __name__ == "__main__":
    main()
