"""v8 locked defaults: crisp sharpen, upscaler cost + raw-clip upscale, script-fidelity verdicts. No network, no spend."""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("CFA_SHARPEN_VF", None); os.environ.pop("CFA_VIDEO_UPSCALE", None)
import render as R
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
check("crisp sharpen is the default", R.SHARPEN_VF == ",unsharp=3:3:0.9:3:3:0,cas=0.35", R.SHARPEN_VF)
check("8 Mbps floor", R.FINAL_MIN_KBPS == 8000, R.FINAL_MIN_KBPS)
check("upscaler on by default", R.VIDEO_UPSCALE)
u = R.upscale_cost(5.0)
check("upscale cost ~ $0.25 per 5s 1080p clip (v8 paid $0.237)", 0.2 <= u <= 0.3, u)
base = R.I2V_MODELS["hailuo"][1]
check("i2v cost estimate includes the upscaler", R.i2v_cost("hailuo", 5.0) >= base + 0.2, (R.i2v_cost("hailuo", 5.0), base))
d = tempfile.mkdtemp(); raw = os.path.join(d, "raw.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=1364x768:d=1", "-pix_fmt", "yuv420p", raw], check=True)
seen = {}
def fetch(model, payload):
    seen.update(model=model, scale=payload["scale"], raw=payload["video_url"].startswith("data:video/mp4")); return open(raw, "rb").read()
out = R.upscale_clip(raw, "k", os.path.join(d, "up.mp4"), 1920, fetch=fetch)
check("upscaler fed the RAW clip at the exact factor to 1080p", seen.get("model") == "fal-ai/video-upscaler" and seen.get("raw") and abs(seen["scale"] - 1920 / 1364) < 0.01 and out.endswith("up.mp4"), seen)
def boom(m, p): raise RuntimeError("down")
check("upscaler failure keeps the raw clip", R.upscale_clip(raw, "k", os.path.join(d, "up2.mp4"), 1920, fetch=boom) == raw)
big = os.path.join(d, "big.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=1920x1080:d=1", "-pix_fmt", "yuv420p", big], check=True)
check("no upscale (no spend) when the clip is already 1080p", R.upscale_clip(big, "k", os.path.join(d, "u3.mp4"), 1920, fetch=boom) == big)
f = R.script_fidelity("x.png", "She checks her phone, worried.", None, ask=lambda l: {"action": True, "object": False, "emotion": True, "why": "no phone"})
check("fidelity fails when the object is missing", f["ok"] is False and "phone" in f["why"], f)
f = R.script_fidelity("x.png", "She smiles.", None, ask=lambda l: {"action": True, "object": True, "emotion": True})
check("fidelity passes when action, object and emotion match", f["ok"] is True, f)
check("fidelity unchecked without a line", R.script_fidelity("x.png", "", "k")["ok"] is None)
html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "CFA_Script_Workflow.html")).read()
check("tool asks Kling o1 for 2K stills", "image_urls:refImages,resolution:KLING_O1_RES" in html and "const KLING_O1_RES='2K'" in html)
check("tool prompt carries the crisp-props rule", "crisp edges on props; background softly blurred" in html and "+CRISP_PROPS_RULE;" in html)
check("tool shot audit asks action/object fidelity and regenerates on a miss", '"action_match":<bool>' in html and "w.push('script fidelity')" in html and "check.fidelity_bad=!au.fidelity_ok" in html)
import shutil
if shutil.which("node"):
    import re as _re
    fn = _re.search(r"function scriptFidelityOk\(f\)\{.*?\}\n", html).group(0)
    out = subprocess.run(["node", "-e", fn + "console.log([scriptFidelityOk({action:true,object:false,emotion:true}),scriptFidelityOk({action:null,object:true,emotion:true}),scriptFidelityOk({action:true,object:true,emotion:false})].join())"], capture_output=True, text=True).stdout.strip()
    check("tool fidelity verdicts (object miss fails, unknown passes, emotion miss fails)", out == "false,true,false", out)
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
