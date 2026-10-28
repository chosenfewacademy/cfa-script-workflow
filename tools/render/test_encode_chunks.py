"""Chunked encode must match the single-pass graph (mocked clips) and handle 100+ shots."""
import os, subprocess, sys, tempfile, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R

fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    fails += 0 if c else 1

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).decode())

def build(n, work):
    clips, shots, t = [], [], 0.0
    names = ["cut", "dissolve", "whip", "fadeblack"]
    prev_end = 0.0
    for i in range(n):
        d = 1.0 + (i % 3) * 0.2
        tr = "cut" if i == 0 else names[i % 4]
        td = 0.0 if tr == "cut" else 0.3
        start = 0.0 if i == 0 else prev_end - td
        start = round(start * R.FPS) / R.FPS
        p = os.path.join(work, "c%03d.mp4" % i)
        subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x%02x%02x%02x:s=160x90:r=30:d=%.3f" % ((i * 37) % 256, (i * 91) % 256, (i * 53) % 256, d),
            "-vf", "drawtext=text=%d:fontsize=40:x=10:y=10:fontcolor=white" % i if False else "null",
            "-pix_fmt", "yuv420p", p])
        clips.append(p)
        shots.append({"start": start, "transition_in": tr, "transition_duration": td})
        prev_end = start + round(d * R.FPS) / R.FPS
    return clips, shots, prev_end

with tempfile.TemporaryDirectory() as w:
    subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "120", "-c:a", "aac", os.path.join(w, "a.m4a")])
    for n, ch in [(23, 5), (41, 7), (17, 16), (2, 16)]:
        clips, shots, total = build(n, w)
        tail = "fps=30,trim=0:%.3f,setpts=PTS-STARTPTS" % total
        one, many = os.path.join(w, "one.mp4"), os.path.join(w, "many.mp4")
        R.encode_video(clips, shots, total, tail, os.path.join(w, "a.m4a"), one, w, chunk=10000)
        R.encode_video(clips, shots, total, tail, os.path.join(w, "a.m4a"), many, w, chunk=ch)
        check(abs(dur(one) - dur(many)) < 0.05, "n=%d chunk=%d duration %.3f vs %.3f" % (n, ch, dur(one), dur(many)))
        out = subprocess.run(["ffmpeg", "-v", "info", "-i", one, "-i", many, "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"], capture_output=True, text=True).stderr
        m = re.search(r"average:([\d.inf]+)", out)
        ps = float("inf") if m and m.group(1) == "inf" else float(m.group(1)) if m else 0
        check(ps > 35, "n=%d chunk=%d PSNR single vs chunked %.1f dB" % (n, ch, ps))
    check(R.chunk_groups(17, 16) == [list(range(17))], "lone trailing shot merged into previous chunk")
    check(sum(len(g) for g in R.chunk_groups(102, 16)) == 102, "102 shots all covered")
print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
