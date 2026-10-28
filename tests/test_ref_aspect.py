"""Every embedded character reference (2D and 3D looks) must be accepted by fal/Kling: aspect ratio 0.4-2.5."""
import re, base64, io, os, sys
from PIL import Image
s = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'CFA_Script_Workflow.html')).read()
fails = 0; n = 0
for m in re.finditer(r"\b([A-Z]+_B64_(?:2D|3D))\s*=\s*['\"](?:data:image/\w+;base64,)?([A-Za-z0-9+/=]{200,})", s):
    w, h = Image.open(io.BytesIO(base64.b64decode(m.group(2)))).size; r = w / h; n += 1
    ok = 0.4 <= r <= 2.5; fails += not ok
    print(('PASS' if ok else 'FAIL'), m.group(1), w, h, round(r, 2))
ok = n >= 10; fails += not ok
print(('PASS' if ok else 'FAIL'), 'found %d refs (>=10 expected: 5 characters x 2 looks)' % n)
print('%d/%d passed' % (n + 1 - fails, n + 1)); sys.exit(1 if fails else 0)
