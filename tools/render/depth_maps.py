"""Depth maps for stills (Depth-Anything-V2-Small, CPU). Run with a Python that has torch+transformers.
usage: depth_maps.py <in.png> <out.png> [<in> <out> ...]   writes 8-bit depth PNGs (255 = near)."""
import sys
import numpy as np
from PIL import Image
from transformers import pipeline

pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=-1)
a = sys.argv[1:]
for src, dst in zip(a[0::2], a[1::2]):
    im = Image.open(src).convert("RGB")
    d = np.array(pipe(im)["depth"].resize(im.size), np.float32)
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    Image.fromarray((d * 255).astype(np.uint8)).save(dst)
    print("depth", dst, flush=True)
