#!/usr/bin/env python3
"""End-to-end test for service.py: auth, CORS, upload, queue (1 at a time), status stages, video/thumbnail, re-edit, restart recovery."""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_render import make_bundle  # noqa: E402

fails = 0
def check(c, m):
    global fails
    print(("PASS " if c else "FAIL ") + m, flush=True)
    fails += 0 if c else 1

ORIGIN = "https://chosenfewacademy.github.io"
def req(base, path, method="GET", data=None, token=None, origin=ORIGIN, ctype=None):
    h = {}
    if token: h["Authorization"] = "Bearer " + token
    if origin: h["Origin"] = origin
    if ctype: h["Content-Type"] = ctype
    r = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, dict(x.headers), x.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()

def start(env):
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "service.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(50):
        try:
            urllib.request.urlopen(env["BASE"] + "/health", timeout=1); return p
        except Exception: time.sleep(0.2)
    raise SystemExit("service did not start")

def wait(base, tok, jid, timeout=400):
    seen, t = set(), time.time()
    while time.time() - t < timeout:
        s = json.loads(req(base, "/jobs/" + jid, token=tok)[2])
        seen.add(s["stage"])
        if s["state"] in ("done", "error"): return s, seen
        time.sleep(0.5)
    return s, seen

def main():
    d = tempfile.mkdtemp(prefix="cfa-svc-")
    z, _ = make_bundle(os.path.join(d, "src"))
    tok = "test-" + os.urandom(8).hex()
    open(os.path.join(d, "token"), "w").write(tok + "\n")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    base = "http://127.0.0.1:%d" % port
    env = dict(os.environ, CFA_RENDER_DATA=os.path.join(d, "data"), CFA_RENDER_TOKEN_FILE=os.path.join(d, "token"),
               CFA_RENDER_PORT=str(port), CFA_RENDER_ARGS="--no-grok", CFA_RENDER_MUSIC="", BASE=base)
    p = start(env)
    try:
        body = open(z, "rb").read()
        check(req(base, "/health", origin=None)[0] == 200, "health is open")
        check(req(base, "/jobs", "POST", body)[0] == 401, "upload without token -> 401")
        check(req(base, "/jobs", "POST", body, token="wrong")[0] == 401, "wrong token -> 401")
        code, h, _ = req(base, "/jobs", "OPTIONS", origin=ORIGIN)
        check(code == 204 and h.get("Access-Control-Allow-Origin") == ORIGIN and "Authorization" in h.get("Access-Control-Allow-Headers", ""), "CORS preflight allowed for the Pages origin")
        check(req(base, "/jobs", "OPTIONS", origin="https://evil.example")[0] == 403, "CORS preflight refused for other origins")
        check(req(base, "/jobs", "POST", body, token=tok, origin="https://evil.example")[0] == 403, "requests from other origins refused even with the token")
        check(req(base, "/jobs", "POST", b"not a zip", token=tok)[0] == 400, "non-zip body rejected")
        c1, h1, r1 = req(base, "/jobs", "POST", body, token=tok, ctype="application/zip")
        c2, _, r2 = req(base, "/jobs?aspect=vertical", "POST", body, token=tok, ctype="application/zip")
        j1, j2 = json.loads(r1), json.loads(r2)
        check(c1 == 202 and c2 == 202 and h1.get("Access-Control-Allow-Origin") == ORIGIN, "two jobs accepted (202) with CORS header")
        time.sleep(1.0)
        s2 = json.loads(req(base, "/jobs/" + j2["id"], token=tok)[2])
        check(s2["state"] == "queued" and s2["queue_position"] == 1 and s2["eta"], "second job waits in the queue (position 1, eta %s)" % s2["eta"])
        st1, seen = wait(base, tok, j1["id"])
        check(st1["state"] == "done" and st1["progress"] == 100, "job 1 finished: %s" % st1.get("error"))
        check({"rendering", "captions", "mixing"} <= seen or {"rendering", "encoding"} <= seen, "status reported stages %s" % sorted(seen))
        check(st1["report"]["resolution"] == "1920x1080" and st1["elapsed"] > 0, "landscape report + elapsed time")
        code, h, v = req(base, "/jobs/%s/video" % j1["id"], token=tok)
        check(code == 200 and v[4:8] == b"ftyp" and h.get("Access-Control-Allow-Origin") == ORIGIN, "video download (%d bytes)" % len(v))
        check(req(base, "/jobs/%s/video" % j1["id"])[0] == 401, "video needs the token")
        code, _, t = req(base, "/jobs/%s/thumbnail" % j1["id"], token=tok)
        check(code == 200 and t[:2] == b"\xff\xd8", "thumbnail download")
        st2, _ = wait(base, tok, j2["id"])
        check(st2["state"] == "done" and st2["report"]["resolution"] == "1080x1920", "queued vertical job rendered after job 1")
        check(st2["created"] >= st1["created"] and json.loads(req(base, "/jobs/" + j2["id"], token=tok)[2])["elapsed"] > 0, "jobs ran one at a time")
        c3, _, r3 = req(base, "/jobs/%s/reedit" % j1["id"], "POST", json.dumps({"notes": "slower ending", "aspect": "vertical"}).encode(), token=tok, ctype="application/json")
        j3 = json.loads(r3)
        check(c3 == 202 and j3["parent"] == j1["id"] and j3["notes"] == "slower ending" and j3["aspect"] == "vertical", "re-edit with notes creates a child job")
        # restart while job 3 is queued/running: it must resume
        p.terminate(); p.wait()
        p = start(env)
        st3, _ = wait(base, tok, j3["id"])
        check(st3["state"] == "done", "job interrupted by a restart re-runs and finishes")
        log = open(os.path.join(d, "data", "jobs", j3["id"], "render.log")).read()
        check("render" in log, "render log kept per job")
        check(json.loads(req(base, "/jobs/" + j1["id"], token=tok)[2])["state"] == "done", "finished jobs survive a restart")
        check(req(base, "/jobs/nope", token=tok)[0] == 404, "unknown job -> 404")
    finally:
        p.terminate()
    print("\n%d failure(s)" % fails)
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
