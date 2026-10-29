#!/usr/bin/env python3
"""CFA render service — HTTP API around render.py (runs on the Grok Bot box).

  POST /jobs?aspect=landscape|vertical&notes=...   body = CFA_FinalEdit_*.zip  -> {"id": ...}
  POST /jobs/<id>/reedit   JSON {"notes": "...", "aspect": "landscape|vertical"} -> {"id": new}
  GET  /jobs/<id>          -> {state, stage, progress, elapsed, eta, queue_position, error, report}
  GET  /jobs/<id>/video    -> final.mp4        GET /jobs/<id>/thumbnail -> thumbnail.jpg
  POST /feedback           JSON {step, kind: episode|tool, rating 1-5, comment, ref, reviewer, episode} -> item
  GET  /feedback           -> {items: [...], memory: [...]}   (?since=<epoch> for changes only)
  GET  /feedback/<id>      -> item          GET /feedback/memory -> {memory: [...]}
  POST /feedback/<id>/status JSON {status: in_progress|ready|declined|reverted, resolution, accept} -> item
  GET  /health             -> {"ok": true, "queue": n}   (no auth)

Auth: "Authorization: Bearer <token>"; the token lives in CFA_RENDER_TOKEN_FILE (never in the repo).
CORS: only origins in CFA_ALLOWED_ORIGINS (default https://chosenfewacademy.github.io).
One render at a time; the rest queue (FIFO). Jobs persist in CFA_RENDER_DATA and are kept 7 days.
"""
import hmac, json, os, queue, re, shutil, subprocess, sys, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("CFA_RENDER_DATA", "/home/box/cfa-render-data")
TOKEN_FILE = os.environ.get("CFA_RENDER_TOKEN_FILE", "/home/box/secrets/cfa_render_token")
ORIGINS = [o.strip() for o in os.environ.get("CFA_ALLOWED_ORIGINS", "https://chosenfewacademy.github.io").split(",") if o.strip()]
MUSIC = os.environ.get("CFA_RENDER_MUSIC", os.path.join(DATA, "music.wav"))
MAX_UPLOAD = int(os.environ.get("CFA_MAX_UPLOAD_MB", "600")) * 1024 * 1024
EXTRA = os.environ.get("CFA_RENDER_ARGS", "").split()
KEEP_DAYS = 7
STAGES = [("queued", 0), ("unpacking", 2), ("planning edit", 5), ("rendering", 15), ("captions", 78), ("mixing", 82), ("encoding", 86), ("done", 100)]

jobs, lock, q = {}, threading.Lock(), queue.Queue()


def token():
    try:
        return open(TOKEN_FILE).read().strip()
    except OSError:
        return ""


def jdir(jid):
    return os.path.join(DATA, "jobs", jid)


def save(j):
    with open(os.path.join(jdir(j["id"]), "job.json"), "w") as f:
        json.dump(j, f)


def public(j):
    now = time.time()
    el = (j.get("finished") or now) - (j.get("started") or now) if j.get("started") else 0
    pos = 0
    if j["state"] == "queued":
        with lock:
            waiting = sorted((x for x in jobs.values() if x["state"] == "queued"), key=lambda x: x["created"])
        pos = [x["id"] for x in waiting].index(j["id"]) + 1 if j["id"] in [x["id"] for x in waiting] else 0
    p = j.get("progress", 0)
    eta = None
    if j["state"] == "running":
        est = j.get("estimate") or 120
        eta = max(5, round(est - el)) if p < 15 else max(3, round(el * (100 - p) / max(p, 1)))
    elif j["state"] == "queued":
        eta = round((j.get("estimate") or 120) * pos)
    out = {k: j.get(k) for k in ("id", "state", "stage", "progress", "error", "aspect", "notes", "parent", "created", "test_s", "test_from", "cap")}
    out.update(elapsed=round(el, 1), eta=eta, queue_position=pos,
               wait=round(now - j["created"], 1))
    if j["state"] == "done":
        out["report"] = j.get("report")
        out["video"], out["thumbnail"] = "/jobs/%s/video" % j["id"], "/jobs/%s/thumbnail" % j["id"]
    return out


def test_params(qs):
    """Test-clip mode from the query string: test_s clamped to 15-30 s, cap clamped to $0-10."""
    out = {}
    try:
        v = float((qs.get("test_s") or [""])[0])
        out["test_s"] = min(30.0, max(15.0, v))
    except ValueError:
        pass
    try:
        if "test_s" in out and qs.get("test_from"):
            out["test_from"] = min(3600.0, max(0.0, float(qs["test_from"][0])))
    except ValueError:
        pass
    try:
        out["cap"] = min(10.0, max(0.0, float((qs.get("cap") or [""])[0])))
    except ValueError:
        pass
    return out


def new_job(bundle_path, aspect, notes, parent=None, test=None):
    jid = uuid.uuid4().hex[:12]
    os.makedirs(jdir(jid))
    dst = os.path.join(jdir(jid), "bundle.zip")
    if parent:
        os.link(bundle_path, dst) if os.stat(bundle_path).st_dev == os.stat(jdir(jid)).st_dev else shutil.copy(bundle_path, dst)
    else:
        os.replace(bundle_path, dst)
    est = 0
    with lock:
        done = [x for x in jobs.values() if x["state"] == "done" and x.get("render_seconds")]
    if done:
        est = sum(x["render_seconds"] for x in done[-5:]) / len(done[-5:])
    j = {"id": jid, "state": "queued", "stage": "queued", "progress": 0, "aspect": aspect, "notes": notes[:2000],
         "parent": parent, "created": time.time(), "estimate": round(est or 150)}
    j.update(test or {})
    with lock:
        jobs[jid] = j
    save(j)
    q.put(jid)
    return j


def set_stage(j, stage, prog):
    j["stage"], j["progress"] = stage, max(j.get("progress", 0), prog)
    save(j)


def worker():
    while True:
        jid = q.get()
        j = jobs.get(jid)
        if not j or j["state"] != "queued":
            continue
        j.update(state="running", started=time.time())
        set_stage(j, "unpacking", 2)
        out = os.path.join(jdir(jid), "out")
        cmd = [sys.executable, "-u", os.path.join(HERE, "render.py"), os.path.join(jdir(jid), "bundle.zip"), "-o", out] + EXTRA
        if j["aspect"] == "vertical":
            cmd.append("--vertical")
        if j.get("notes"):
            cmd += ["--notes", j["notes"]]
        if j.get("test_s"):
            cmd += ["--max-seconds", "%.1f" % j["test_s"]]
            if j.get("test_from"):
                cmd += ["--from-seconds", "%.2f" % j["test_from"]]
        if j.get("cap") is not None:
            cmd += ["--total-cap", "%.2f" % j["cap"]]
        if MUSIC and os.path.exists(MUSIC):
            cmd += ["--music", MUSIC]
        logf = open(os.path.join(jdir(jid), "render.log"), "w")
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in p.stdout:
                logf.write(line); logf.flush()
                if "beats ->" in line:
                    set_stage(j, "planning edit", 5)
                elif "EDL from" in line:
                    set_stage(j, "rendering", 15)
                elif (m := re.search(r"\] shot (\d+)/(\d+)", line)):
                    set_stage(j, "rendering", 15 + int(60 * int(m.group(1)) / int(m.group(2))))
                elif "stage: captions" in line:
                    set_stage(j, "captions", 78)
                elif "stage: mixing" in line:
                    set_stage(j, "mixing", 82)
                elif "stage: encoding" in line:
                    set_stage(j, "encoding", 86)
            rc = p.wait()
            rep = os.path.join(out, "report.json")
            if rc == 0 and os.path.exists(os.path.join(out, "final.mp4")):
                r = json.load(open(rep)) if os.path.exists(rep) else {}
                keep = {k: r.get(k) for k in ("duration", "resolution", "lufs", "edl_source", "arc", "punch_ins", "shot_lengths", "min_shot", "avg_shot")}
                j.update(state="done", stage="done", progress=100, report=keep)
            else:
                tail = open(os.path.join(jdir(jid), "render.log")).read()[-600:]
                j.update(state="error", stage="failed", error="render failed (exit %s): %s" % (rc, tail.strip().splitlines()[-1] if tail.strip() else ""))
        except Exception as e:
            j.update(state="error", stage="failed", error=str(e)[:300])
        finally:
            logf.close()
            j["finished"] = time.time()
            j["render_seconds"] = round(j["finished"] - j["started"], 1)
            save(j)


def load_jobs():
    os.makedirs(os.path.join(DATA, "jobs"), exist_ok=True)
    cutoff = time.time() - KEEP_DAYS * 86400
    pending = []
    for jid in os.listdir(os.path.join(DATA, "jobs")):
        try:
            j = json.load(open(os.path.join(jdir(jid), "job.json")))
        except Exception:
            continue
        if j["created"] < cutoff:
            shutil.rmtree(jdir(jid), ignore_errors=True)
            continue
        if j["state"] in ("queued", "running"):        # interrupted by a restart: run again
            j.update(state="queued", stage="queued", progress=0)
            pending.append(j)
        jobs[jid] = j
    for j in sorted(pending, key=lambda x: x["created"]):
        q.put(j["id"])


FB_STEPS = ("research", "script", "voices", "registry", "shotlist", "stills", "clips", "lipsync", "narration", "music", "edit", "final")
FB_STATUS = ("submitted", "in_progress", "ready", "declined", "reverted")
fb_lock = threading.Lock()


def fb_dir(*p):
    d = os.path.join(DATA, "feedback")
    os.makedirs(os.path.join(d, "items"), exist_ok=True)
    return os.path.join(d, *p)


def fb_clean(v, n):
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", str(v or ""))[:n]


def fb_items():
    out = []
    for f in sorted(os.listdir(fb_dir("items"))):
        if f.endswith(".json"):
            try:
                out.append(json.load(open(fb_dir("items", f))))
            except (OSError, ValueError):
                pass
    return sorted(out, key=lambda x: x.get("created", 0))


def fb_memory():
    try:
        return [json.loads(l) for l in open(fb_dir("memory.jsonl")) if l.strip()]
    except (OSError, ValueError):
        return []


def fb_write(it):
    tmp = fb_dir("items", it["id"] + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump(it, f)
    os.replace(tmp, fb_dir("items", it["id"] + ".json"))


def fb_new(body):
    step = body.get("step")
    kind = body.get("kind")
    if step not in FB_STEPS or kind not in ("episode", "tool"):
        raise ValueError("step must be one of %s and kind episode|tool" % ",".join(FB_STEPS))
    comment = fb_clean(body.get("comment"), 4000).strip()
    if not comment:
        raise ValueError("comment is required")
    try:
        rating = int(body.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    now = time.time()
    it = {"id": "fb_" + uuid.uuid4().hex[:12], "step": step, "kind": kind, "rating": max(0, min(5, rating)),
          "comment": comment, "ref": fb_clean(body.get("ref"), 200), "reviewer": fb_clean(body.get("reviewer") or "Chris", 60),
          "episode": fb_clean(body.get("episode"), 200), "status": "submitted", "resolution": "",
          "created": now, "updated": now, "history": [{"status": "submitted", "at": now}]}
    with fb_lock:
        fb_write(it)
        with open(fb_dir("inbox.jsonl"), "a") as f:
            f.write(json.dumps(it) + "\n")
    return it


def fb_status(fid, body):
    st = body.get("status")
    if st not in FB_STATUS[1:]:
        raise ValueError("status must be in_progress, ready, declined or reverted")
    with fb_lock:
        path = fb_dir("items", fid + ".json")
        it = json.load(open(path))
        now = time.time()
        it["status"], it["updated"] = st, now
        if body.get("resolution") is not None:
            it["resolution"] = fb_clean(body.get("resolution"), 2000)
        it["history"].append({"status": st, "at": now})
        if body.get("accept") and st == "ready" and not it.get("accepted"):
            it["accepted"] = True
            rule = fb_clean(body.get("rule") or it["comment"], 600)
            with open(fb_dir("memory.jsonl"), "a") as f:
                f.write(json.dumps({"id": it["id"], "step": it["step"], "rule": rule, "at": now}) + "\n")
        fb_write(it)
    return it


class H(BaseHTTPRequestHandler):
    server_version = "cfa-render/1"

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % a))

    def cors(self):
        o = self.headers.get("Origin")
        if o and o in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Expose-Headers", "Content-Length")

    def send(self, code, obj=None, ctype="application/json", body=None):
        body = body if body is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        t = token()
        got = self.headers.get("Authorization", "")
        ok = bool(t) and hmac.compare_digest(got.encode(), ("Bearer " + t).encode())
        if not ok:
            self.send(401, {"error": "missing or wrong access token"})
        return ok

    def origin_ok(self):
        o = self.headers.get("Origin")
        if o and o not in ORIGINS:
            self.send(403, {"error": "origin not allowed"})
            return False
        return True

    def do_OPTIONS(self):
        o = self.headers.get("Origin")
        self.send_response(204 if o in ORIGINS else 403)
        if o in ORIGINS:
            self.cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, ngrok-skip-browser-warning")
            self.send_header("Access-Control-Max-Age", "600")
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")   # Chrome: https page -> local service
        self.send_header("Content-Length", "0")
        self.end_headers()

    def route(self):
        u = urlparse(self.path)
        return [x for x in u.path.split("/") if x], parse_qs(u.query)

    def do_GET(self):
        parts, qs = self.route()
        if parts == ["health"]:
            return self.send(200, {"ok": True, "queue": sum(1 for j in jobs.values() if j["state"] in ("queued", "running"))})
        if not self.origin_ok() or not self.authed():
            return
        if parts[:1] == ["feedback"]:
            if parts == ["feedback"]:
                try:
                    since = float((qs.get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                return self.send(200, {"items": [i for i in fb_items() if i["updated"] > since], "memory": fb_memory(), "now": time.time()})
            if parts == ["feedback", "memory"]:
                return self.send(200, {"memory": fb_memory()})
            if len(parts) == 2 and re.fullmatch(r"fb_[0-9a-f]{12}", parts[1]) and os.path.exists(fb_dir("items", parts[1] + ".json")):
                return self.send(200, json.load(open(fb_dir("items", parts[1] + ".json"))))
            return self.send(404, {"error": "not found"})
        if len(parts) >= 2 and parts[0] == "jobs" and parts[1] in jobs:
            j = jobs[parts[1]]
            if len(parts) == 2:
                return self.send(200, public(j))
            name = {"video": ("final.mp4", "video/mp4"), "thumbnail": ("thumbnail.jpg", "image/jpeg")}.get(parts[2] if len(parts) > 2 else "")
            path = name and os.path.join(jdir(j["id"]), "out", name[0])
            if name and j["state"] == "done" and os.path.exists(path):
                return self.stream(path, name[1])
        self.send(404, {"error": "not found"})

    def stream(self, path, ctype):
        size = os.path.getsize(path)
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", 'inline; filename="%s"' % os.path.basename(path))
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def do_POST(self):
        parts, qs = self.route()
        if not self.origin_ok() or not self.authed():
            return
        n = int(self.headers.get("Content-Length") or 0)
        if parts == ["jobs"]:
            if n <= 0 or n > MAX_UPLOAD:
                return self.send(413 if n else 411, {"error": "upload must be 1 byte to %d MB" % (MAX_UPLOAD >> 20)})
            os.makedirs(os.path.join(DATA, "uploads"), exist_ok=True)
            tmp = os.path.join(DATA, "uploads", uuid.uuid4().hex + ".zip")
            left = n
            with open(tmp, "wb") as f:
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk); left -= len(chunk)
            with open(tmp, "rb") as f:
                magic = f.read(4)
            if left or magic[:2] != b"PK":
                os.remove(tmp)
                return self.send(400, {"error": "body must be the CFA_FinalEdit zip"})
            aspect = "vertical" if (qs.get("aspect") or [""])[0] == "vertical" else "landscape"
            j = new_job(tmp, aspect, (qs.get("notes") or [""])[0], test=test_params(qs))
            return self.send(202, public(j))
        if parts[:1] == ["feedback"]:
            try:
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("JSON object expected")
                if parts == ["feedback"]:
                    return self.send(201, fb_new(body))
                if len(parts) == 3 and parts[2] == "status" and re.fullmatch(r"fb_[0-9a-f]{12}", parts[1]) and os.path.exists(fb_dir("items", parts[1] + ".json")):
                    return self.send(200, fb_status(parts[1], body))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            return self.send(404, {"error": "not found"})
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "reedit" and parts[1] in jobs:
            try:
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
            except ValueError:
                return self.send(400, {"error": "JSON body expected"})
            old = jobs[parts[1]]
            aspect = body.get("aspect") if body.get("aspect") in ("landscape", "vertical") else old["aspect"]
            j = new_job(os.path.join(jdir(old["id"]), "bundle.zip"), aspect, str(body.get("notes") or ""), parent=old["id"])
            return self.send(202, public(j))
        self.send(404, {"error": "not found"})


def main():
    load_jobs()
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get("CFA_RENDER_PORT", "8787"))
    srv = ThreadingHTTPServer((os.environ.get("CFA_RENDER_HOST", "127.0.0.1"), port), H)
    print("cfa-render listening on %d, origins %s, token file %s (%s)" % (port, ORIGINS, TOKEN_FILE, "present" if token() else "MISSING"), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
