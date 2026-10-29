"""Edge-band gate + false-bar detection (v6: dark stills were cropped as 'bars' and pillar-filled with blur)."""
import os, subprocess, tempfile, numpy as np
from PIL import Image
import render
fails = []
def check(n, c, d=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else d)
    c or fails.append(n)
d = tempfile.mkdtemp()
rng = np.random.default_rng(1)
art = (rng.random((540, 960)) * 200 + 30).astype(np.uint8)
# dark-edged art: shadowy but textured edges -> NOT bars
dark = art.copy(); dark[:, :150] = (rng.random((540, 150)) * 30).astype(np.uint8)
p1 = os.path.join(d, "dark.png"); Image.fromarray(dark).save(p1)
check("bars_are_flat: textured dark edge is not a bar", not render.bars_are_flat(p1, "image", (810, 540, 150, 0), 960, 540))
flat = art.copy(); flat[:, :150] = 2
p2 = os.path.join(d, "flat.png"); Image.fromarray(flat).save(p2)
check("bars_are_flat: flat black strip is a bar", render.bars_are_flat(p2, "image", (810, 540, 150, 0), 960, 540))
check("fill_graph has no blur fill", "boxblur" not in render.fill_graph((810, 540, 150, 0), 1920, 1080))
def clip(img, name):
    p = os.path.join(d, name + ".png"); Image.fromarray(img).convert("RGB").save(p)
    o = os.path.join(d, name + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", p, "-t", "2", "-r", "10", "-pix_fmt", "yuv420p", o], check=True)
    return o
big = np.kron(art, np.ones((2, 2), dtype=np.uint8))
check("edge gate passes full-bleed art", render.edge_gate(clip(big, "ok"))["pass"])
bl = big.copy(); bl[:, :200] = 1
check("edge gate fails a black side bar", not render.edge_gate(clip(bl, "bar"))["pass"])
bb = big.copy(); bb[:, -220:] = np.asarray(Image.fromarray(bb[:, -220:]).resize((11, 54)).resize((220, 1080), Image.BILINEAR))
check("edge gate fails a blurred side band", not render.edge_gate(clip(bb, "blur"))["pass"])
v6 = "/workspace/render-test/tc/out/test_clip_v6.mp4"
if os.path.exists(v6):
    g = render.edge_gate(v6)
    ts = sorted(set(b["t"] for b in g["bad"]))
    check("edge gate flags v6 shots 3-4 (8.0-15.9s) only", not g["pass"] and ts and min(ts) >= 8.0 and max(ts) < 16.0, ts)
import numpy as _np, cv2 as _cv2
_rng = _np.random.default_rng(3); _art = _cv2.resize(_rng.integers(40, 220, (108, 192)).astype(_np.uint8), (1920, 1080), interpolation=_cv2.INTER_NEAREST).astype(_np.float32)
_soft = _cv2.GaussianBlur(_art, (0, 0), 14); _w = _np.clip(_np.arange(1920) / 700.0, 0, 1)[None, :]
_dof = _soft * (1 - _w) + _art * _w   # gradual focus falloff toward the left edge, no seam
_st = render.edge_band_stats(_dof)
check("shallow depth-of-field falloff is not a blurred band", not _st["left"][1])
_dark = _art * 0.12; _dark[:, 400:] = _art[:, 400:]
check("textured low-key art is not a dark bar", not render.edge_band_stats(_dark)["left"][0])
print("%d failure(s)" % len(fails)); raise SystemExit(1 if fails else 0)
