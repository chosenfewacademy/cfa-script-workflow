"""One-time self-serve key claim (POST /keys/claim): works once for an open slot, second claim refused, closed /
expired / unknown slot refused, wrong or missing Origin 403, claimed key authorizes, claim replaces the old key,
rate limit, and keys never stored or printed in plain text."""
import hashlib, json, os, socket, stat, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n, x if not ok else ""); ok or fails.append(n)
d = tempfile.mkdtemp()
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
base = "http://127.0.0.1:%d" % port
ORIGIN = "https://chosenfewacademy.github.io"
open(os.path.join(d, "token"), "w").write("owner-test-token\n")
KF, CF = os.path.join(d, "keys.json"), os.path.join(d, "claims.json")
env = dict(os.environ, CFA_RENDER_DATA=os.path.join(d, "data"), CFA_RENDER_TOKEN_FILE=os.path.join(d, "token"),
           CFA_RENDER_KEYS_FILE=KF, CFA_RENDER_CLAIMS_FILE=CF, CFA_RENDER_PORT=str(port), CFA_RENDER_MUSIC="")
def kp(*a):
    return subprocess.run([sys.executable, os.path.join(HERE, "keys.py")] + list(a), env=env, capture_output=True, text=True)
def req(method, path, body=None, origin=ORIGIN, tok=None, xff="10.0.0.1"):
    h = {"Content-Type": "application/json", "X-Forwarded-For": xff}
    if origin: h["Origin"] = origin
    if tok: h["Authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=h, method=method), timeout=10)
        return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)
old = os.path.join(d, "old_key.txt"); kp("add", "chris", old); oldkey = open(old).read().strip()
r = kp("open-claim", "Chris", "7")
check("open-claim opens a slot (name normalised)", r.returncode == 0 and "chris" in json.load(open(CF)), r.stdout + r.stderr)
kp("open-claim", "gone", "7"); kp("close-claim", "gone")
cl = json.load(open(CF)); cl["late"] = {"opened": time.time() - 9 * 86400, "expires": time.time() - 2 * 86400}; json.dump(cl, open(CF, "w"))
check("open-claim rejects bad days", kp("open-claim", "x", "99").returncode == 2)
p = subprocess.Popen([sys.executable, os.path.join(HERE, "service.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/health", timeout=2); break
        except Exception:
            time.sleep(0.2)
    c, b, _ = req("POST", "/keys/claim", {"name": "chris"}, origin="https://evil.example")
    check("wrong origin -> 403, slot untouched", c == 403 and "claimed_at" not in json.load(open(CF))["chris"], (c, b))
    c, b, _ = req("POST", "/keys/claim", {"name": "chris"}, origin=None)
    check("missing origin (curl/script) -> 403", c == 403, (c, b))
    pre = urllib.request.Request(base + "/keys/claim", method="OPTIONS", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    pr = urllib.request.urlopen(pre, timeout=5)
    check("CORS preflight allowed for the tool origin", pr.status == 204 and pr.headers.get("Access-Control-Allow-Origin") == ORIGIN)
    c, b, h = req("POST", "/keys/claim", {"name": " Chris "})
    newkey = b.get("key", "")
    check("claim works once for an open slot", c == 200 and b.get("name") == "chris" and len(newkey) >= 40 and h.get("Access-Control-Allow-Origin") == ORIGIN and h.get("Cache-Control") == "no-store", (c, b))
    c2, b2, _ = req("POST", "/keys/claim", {"name": "chris"}, xff="10.0.0.2")
    check("second claim refused (409, no key)", c2 == 409 and "key" not in b2, (c2, b2))
    c, b, _ = req("POST", "/keys/claim", {"name": "gone"}, xff="10.0.0.2")
    check("closed slot refused (404)", c == 404 and "key" not in b, (c, b))
    c, b, _ = req("POST", "/keys/claim", {"name": "late"}, xff="10.0.0.2")
    check("expired slot refused (410)", c == 410 and "key" not in b, (c, b))
    c, b, _ = req("POST", "/keys/claim", {"name": "nobody"}, xff="10.0.0.3")
    check("unknown name refused (404)", c == 404 and "key" not in b, (c, b))
    c, b, _ = req("POST", "/keys/claim", {"name": "../x"}, xff="10.0.0.3")
    check("bad name -> 400", c == 400, (c, b))
    c, b, _ = req("POST", "/keys/claim", ["x"], xff="10.0.0.3")
    check("non-object body -> 400", c == 400, (c, b))
    c, b, _ = req("GET", "/feedback", tok=newkey)
    check("claimed key authorizes", c == 200, (c, b))
    c, b, _ = req("GET", "/feedback", tok=oldkey)
    check("claim replaced the old key for that name (401)", c == 401, (c, b))
    c, b, _ = req("GET", "/feedback", tok="owner-test-token")
    check("owner token unaffected", c == 200, (c, b))
    store, cstore = open(KF).read(), open(CF).read()
    check("keys never stored in plain text", newkey not in store and newkey not in cstore and oldkey not in store
          and json.loads(store)["chris"] == hashlib.sha256(newkey.encode()).hexdigest())
    check("keys + claims files are 0600", stat.S_IMODE(os.stat(KF).st_mode) == 0o600 and stat.S_IMODE(os.stat(CF).st_mode) == 0o600)
    r = kp("list")
    check("list shows claim state, never keys", "claim chris: claimed" in r.stdout and "claim late: expired" in r.stdout and newkey not in r.stdout, r.stdout)
    codes = [req("POST", "/keys/claim", {"name": "nobody"}, xff="10.9.9.9")[0] for _ in range(7)]
    check("per-client rate limit -> 429", codes[:5] == [404] * 5 and codes[5:] == [429, 429], codes)
    kp("open-claim", "dana", "1")
    c, b, _ = req("POST", "/keys/claim", {"name": "dana"}, xff="10.9.9.9")
    check("rate-limited client can't claim even an open slot", c == 429 and "key" not in b, (c, b))
    c, b, _ = req("POST", "/keys/claim", {"name": "dana"}, xff="10.8.8.8")
    check("another client still can", c == 200 and b.get("key"), (c, b))
    dkey = b.get("key", "x")
    kp("revoke", "dana")
    check("revoke kills a claimed key", req("GET", "/feedback", tok=dkey)[0] == 401)
finally:
    p.terminate()
    try:
        err = p.communicate(timeout=5)[1].decode()
    except Exception:
        err = ""
check("service log never contains a key", newkey not in err and oldkey not in err, "")
print("%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
