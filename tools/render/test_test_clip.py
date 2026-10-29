"""Fix 6: test-clip mode — renderer trims to first beats within N s; total cap clamps music; service parses params."""
import os, sys, json, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R, service as S
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
d = tempfile.mkdtemp()
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=90", os.path.join(d, "vo.wav")], check=True)
b = {"voiceover": "vo.wav"}
segs = [{"index": i + 1, "start": i * 9.0, "end": i * 9.0 + 9.0} for i in range(10)]
words = [["w", i * 0.5, i * 0.5 + 0.4] for i in range(180)]
k, w, tot, info = R.trim_to_seconds(d, b, segs, words, 90.0, 40, d)
check("keeps beats ending <= 40s", len(k) == 4 and info["beats"] == 4, info)
check("voice trimmed ~36.35s", abs(tot - 36.35) < 0.1, tot)
check("words trimmed", max(x[2] for x in w) <= 36.4, len(w))
k, w, tot, info = R.trim_to_seconds(d, {"voiceover": "vo.wav"}, [{"index": 1, "start": 0, "end": 60}, {"index": 2, "start": 60, "end": 70}], words, 90.0, 40, d)
check("always keeps first beat", len(k) == 1, info)
check("test_s clamp", S.test_params({"test_s": ["120"], "cap": ["50"]}) == {"test_s": 30.0, "cap": 10.0})
check("test_s low clamp", S.test_params({"test_s": ["5"]}) == {"test_s": 15.0})
check("25 s kept", S.test_params({"test_s": ["25"]}) == {"test_s": 25.0})
check("no params -> full", S.test_params({}) == {})
check("garbage ignored", S.test_params({"test_s": ["x"], "cap": ["y"]}) == {})
ok, est, why = R.music_guard(40, min(1.0, 6.0 - 5.9), 0.0)
check("total cap blocks music when spend near cap", not ok, (est, why))
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
