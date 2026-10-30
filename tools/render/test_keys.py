"""Per-person keys: owner token + a person's key both work, wrong key 401, revoke takes effect without a restart, keys never stored in plain text."""
import json, os, socket, stat, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
d = tempfile.mkdtemp()
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
base = "http://127.0.0.1:%d" % port
open(os.path.join(d, "token"), "w").write("owner-test-token\n")
env = dict(os.environ, CFA_RENDER_DATA=os.path.join(d, "data"), CFA_RENDER_TOKEN_FILE=os.path.join(d, "token"),
           CFA_RENDER_KEYS_FILE=os.path.join(d, "keys.json"), CFA_RENDER_PORT=str(port), CFA_RENDER_MUSIC="")
kf = os.path.join(d, "chris_key.txt")
r = subprocess.run([sys.executable, os.path.join(HERE, "keys.py"), "add", "chris", kf], env=env, capture_output=True, text=True)
key = open(kf).read().strip()
check("keys.py add writes the key 0600 and never prints it", r.returncode == 0 and key and key not in r.stdout + r.stderr and stat.S_IMODE(os.stat(kf).st_mode) == 0o600, r.stdout)
store = open(os.path.join(d, "keys.json")).read()
check("keys file holds only a hash (0600)", key not in store and "chris" in json.loads(store) and stat.S_IMODE(os.stat(os.path.join(d, "keys.json")).st_mode) == 0o600)
p = subprocess.Popen([sys.executable, os.path.join(HERE, "service.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get(tok):
    h = {"Authorization": "Bearer " + tok} if tok is not None else {}
    try:
        return urllib.request.urlopen(urllib.request.Request(base + "/feedback", headers=h), timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/health", timeout=2); break
        except Exception:
            time.sleep(0.2)
    check("owner token still works", get("owner-test-token") == 200)
    check("Chris's key works", get(key) == 200)
    check("wrong key -> 401", get("nope") == 401 and get(key + "x") == 401)
    check("no key -> 401", get(None) == 401)
    subprocess.run([sys.executable, os.path.join(HERE, "keys.py"), "revoke", "chris"], env=env, capture_output=True)
    check("revoked key -> 401 at once (no restart)", get(key) == 401)
    check("owner token unaffected by revoke", get("owner-test-token") == 200)
    r = subprocess.run([sys.executable, os.path.join(HERE, "keys.py"), "list"], env=env, capture_output=True, text=True)
    check("list shows names only", "chris" not in r.stdout and key not in r.stdout)
finally:
    p.terminate()
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
