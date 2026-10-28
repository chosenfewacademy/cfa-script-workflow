"""Whisper QA treats same-sound spellings as heard (Dee/D, four-fifty/450, tear/tier); real misses still flag. Mocked, $0."""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m); fails += 0 if c else 1
segs = [{"index": 1, "speaker": "NARRATOR", "text": "Dee needed Four-fifty by five o'clock."},
        {"index": 2, "speaker": "NARRATOR", "text": "Tear that page out of the notebook now."},
        {"index": 3, "speaker": "NARRATOR", "text": "The seed phrase stays on paper, offline."}]
def words(seq, t0=0.0):
    return [(w, t0 + 0.3 * i, t0 + 0.3 * i + 0.25) for i, w in enumerate(seq)]
script = "Dee needed Four-fifty by five o'clock. Tear that page out of the notebook now. The seed phrase stays on paper, offline.".split()
heard = "D needed 450 by five oclock. Tier that page out of the notebook now. The seed phrase stays on paper, offline.".split()
res = R.whisper_check(segs, words(script), words(heard))
flags = res[0]["flagged"]
check(flags == [], "homophones heard as the script: no false flags (%s)" % flags)
bad = "D needed by. Tier that out now. The seed phrase stays on paper, offline.".split()
res = R.whisper_check(segs, words(script), words(bad))
check(res[0]["flagged"] == [1, 2], "real dropped words still flag lines 1-2")
random.seed(5); ok = True
for _ in range(300):
    seq = [random.choice(["dee", "d", "450", "four-fifty", "tear", "tier", "paper", "now"]) for _ in range(random.randint(1, 30))]
    try: R.whisper_check([{"index": 1, "text": " ".join(seq)}], words(seq), words(list(reversed(seq))))
    except Exception as e: ok = False; print(e); break
check(ok, "300 random scripts: whisper_check never crashes")
print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
