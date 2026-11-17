"""Unique shots (Nov 16): the renderer refuses any picture used twice - same file, a near-duplicate (crop/zoom,
alt take of one framing, a still that is a frame of a clip) - and any shot without its own picture. Both styles.
$0: synthetic assets, keys stripped, no network."""
import json, os, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def unique_still(path, seed, w=2720, h=1536):
    """A distinct, textured synthetic still (random shapes on a random gradient) - no two seeds share features."""
    import numpy as np, cv2
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.dstack([(x * rng.uniform(.02, .1) + y * rng.uniform(.02, .1) + rng.uniform(0, 255)) % 255 for _ in range(3)]).astype(np.uint8)
    for _ in range(60):
        c = tuple(int(v) for v in rng.integers(0, 255, 3)); cx, cy = int(rng.integers(0, w)), int(rng.integers(0, h)); r = int(rng.integers(20, 260))
        if rng.random() < .5:
            cv2.circle(base, (cx, cy), r, c, -1)
        else:
            cv2.rectangle(base, (cx, cy), (min(w - 1, cx + r * 2), min(h - 1, cy + r)), c, -1)
    cv2.imwrite(path, base)
    return path


if __name__ == "__main__":
    import numpy as np, cv2
    os.environ.pop("CFA_CAPTIONS", None)
    import render as R
    fails = []
    def check(n, ok, x=""):
        print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
    d = tempfile.mkdtemp(); m = os.path.join(d, "media"); os.makedirs(m)
    for i in range(6):
        unique_still(os.path.join(m, "u%d.png" % i), seed=i)
    import shutil
    shutil.copy(os.path.join(m, "u0.png"), os.path.join(m, "copy_of_u0.png"))           # same bytes, new name
    im = cv2.imread(os.path.join(m, "u1.png")); hh, ww = im.shape[:2]
    cv2.imwrite(os.path.join(m, "crop_u1.png"), cv2.resize(im[int(hh * .15):int(hh * .85), int(ww * .15):int(ww * .85)], (ww, hh)))   # punch-in crop
    alt = cv2.convertScaleAbs(cv2.GaussianBlur(im, (5, 5), 0), alpha=1.08, beta=-12)
    alt = np.clip(alt.astype(np.int16) + np.random.default_rng(9).integers(-10, 10, alt.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(os.path.join(m, "alt_u1.png"), alt)                                      # alt take: same framing, re-graded + noise
    # a clip made by slowly zooming into u2 (its frames are that still)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", os.path.join(m, "u2.png"), "-t", "3", "-r", "30",
                    "-vf", "scale=1920:1080,zoompan=z='1+0.002*on':d=90:s=1920x1080:fps=30", "-pix_fmt", "yuv420p", os.path.join(m, "clip_u2.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", os.path.join(m, "u5.png"), "-t", "3", "-r", "30",
                    "-vf", "scale=1920:1080", "-pix_fmt", "yuv420p", os.path.join(m, "clip_u5.mp4")], check=True)
    sh = lambda ms: [{"index": k + 1, "media": "media/" + x, "mediaType": "video" if x.endswith(".mp4") else "image"} for k, x in enumerate(ms)]
    g = R.uniqueness_gate(sh(["u0.png", "u1.png", "u2.png", "u3.png", "u4.png", "clip_u5.mp4"]), d)
    check("all-unique stills + clip pass", g["pass"] and g["compared"] == 6, g.get("message"))
    g = R.uniqueness_gate(sh(["u0.png", "u3.png", "u0.png"]), d)
    check("same file twice fails and names shots 1 and 3", not g["pass"] and g["exact"] and g["exact"][0]["shots"] == [1, 3] and "shots 1 and 3 use the same file" in g["message"], g.get("message"))
    g = R.uniqueness_gate(sh(["u0.png", "u3.png", "copy_of_u0.png"]), d)
    check("same bytes under another name fails (sha256)", not g["pass"] and g["exact"] and g["exact"][0]["shots"] == [1, 3], g.get("message"))
    g = R.uniqueness_gate(sh(["u1.png", "u3.png", "crop_u1.png"]), d)
    check("a punch-in crop of the same still fails as a near-duplicate", not g["pass"] and g["near"] and g["near"][0]["shots"] == [1, 3] and "near-duplicates" in g["message"], g.get("message"))
    g = R.uniqueness_gate(sh(["u1.png", "alt_u1.png"]), d)
    check("an alt take of the same framing fails", not g["pass"] and g["near"] and g["near"][0]["shots"] == [1, 2], g.get("message"))
    g = R.uniqueness_gate(sh(["u2.png", "u4.png", "clip_u2.mp4"]), d)
    check("a still that is a frame of a clip fails", not g["pass"] and g["near"] and g["near"][0]["shots"] == [1, 3], g.get("message"))
    g = R.uniqueness_gate(sh(["u0.png", "u1.png"]) + [{"index": 3, "media": None, "mediaType": "image"}], d)
    check("a shot without its own picture fails (never filled from a neighbour)", not g["pass"] and g["missing"] == [3] and "no picture of its own" in g["message"], g.get("message"))
    check("thresholds: ORB >= 30 inliers, dHash <= 6, SSIM >= 0.90", (R.UNIQUE_ORB_INLIERS, R.UNIQUE_DHASH_MAX, R.UNIQUE_SSIM_MIN) == (30, 6, 0.90))
    check("similarity gate has no match-cut exemption", "plan_link" not in __import__("inspect").getsource(R.similarity_gate))

    # end-to-end, both styles: duplicate bundle refuses BEFORE rendering with the colliding shots named; unique bundle renders
    def bundle(name, media, style):
        bd = os.path.join(d, name); os.makedirs(os.path.join(bd, "media"))
        for x in set(media):
            shutil.copy(os.path.join(m, x), os.path.join(bd, "media", x))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=200:d=%d" % (2 * len(media)), "-ar", "44100", os.path.join(bd, "voiceover.mp3")], check=True)
        W = [["w%d" % k, round(k * 0.4, 2), round(k * 0.4 + 0.3, 2)] for k in range(5 * len(media))]
        segs = [{"index": k + 1, "text": " ".join(w[0] for w in W[k * 5:(k + 1) * 5]), "media": "media/" + x, "mediaType": "video" if x.endswith(".mp4") else "image",
                 "characters": "NONE", "start": k * 2.0, "end": k * 2.0 + 2.0} for k, x in enumerate(media)]
        json.dump({"format": "cfa-final-edit-bundle", "version": 1, "title": name, "voiceover": "voiceover.mp3", "words": W, "segments": segs, "cutStyle": style},
                  open(os.path.join(bd, "bundle.json"), "w"))
        return bd
    env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "FAL_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "CFA_CAPTIONS")}
    def render(bd, style):
        out = os.path.join(d, os.path.basename(bd) + "_out")
        r = subprocess.run([sys.executable, os.path.join(HERE, "render.py"), bd, "-o", out, "--no-grok", "--no-score", "--no-whisper", "--no-ambience", "--no-sfx",
                            "--keys-env", "/dev/null", "--min-hold", "1.0", "--cut-style", style], capture_output=True, text=True, env=env)
        return r, out
    for style in ("v8", "fast_cuts"):
        r, out = render(bundle("dup_" + style, ["u0.png", "u3.png", "crop_u1.png", "u1.png"], style), style)
        err = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else ""
        check("%s: near-duplicate bundle refused (exit != 0), message names shots 3 and 4" % style, r.returncode != 0 and "UNIQUE SHOTS GATE FAILED" in err and "shots 3 and 4" in err, err[-300:])
        check("%s: refused before rendering (no final.mp4), report says why" % style, not os.path.exists(os.path.join(out, "final.mp4")) and json.load(open(os.path.join(out, "report.json")))["uniqueness"]["pass"] is False)
        r, out = render(bundle("same_" + style, ["u0.png", "u3.png", "u0.png"], style), style)
        err = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else ""
        check("%s: same asset twice refused, message names shots 1 and 3" % style, r.returncode != 0 and "shots 1 and 3 use the same file" in err, err[-300:])
        r, out = render(bundle("ok_" + style, ["u0.png", "u3.png", "u4.png", "clip_u5.mp4"], style), style)
        rep = json.load(open(os.path.join(out, "report.json"))) if r.returncode == 0 else {}
        check("%s: all-unique bundle renders, uniqueness gate PASS" % style, r.returncode == 0 and rep.get("motion_gate", {}).get("uniqueness", {}).get("pass") is True and rep.get("cut_style") == style,
              (r.stdout + r.stderr)[-600:])
    print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
