"""Per-person renderer keys. Keys are never printed; only their SHA-256 is stored (0600 file, outside the repo).
  python3 keys.py add NAME OUTFILE      -> new key written to OUTFILE (chmod 600), hash stored
  python3 keys.py revoke NAME           -> key stops working on the next request (no restart)
  python3 keys.py open-claim NAME [DAYS] -> NAME may fetch their own key ONCE from the tool (Settings ->
                                          "Get my access key") within DAYS (default 7). Claiming replaces any
                                          older key for NAME. Nothing secret to relay: the key goes straight to them.
  python3 keys.py close-claim NAME      -> close an unused claim slot
  python3 keys.py list                  -> names only, plus claim slots and their state"""
import hashlib, json, os, re, secrets, sys, time
F = os.environ.get("CFA_RENDER_KEYS_FILE", "/home/box/secrets/cfa_render_keys.json")
CLAIMS = os.environ.get("CFA_RENDER_CLAIMS_FILE", os.path.join(os.path.dirname(F), "cfa_render_claims.json"))
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}")


def _load(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, path); os.chmod(path, 0o600)


def load(): return _load(F)
def save(d): _save(F, d)
def load_claims(): return _load(CLAIMS)
def save_claims(d): _save(CLAIMS, d)


def norm(name):
    n = str(name or "").strip().lower()
    return n if NAME_RE.fullmatch(n) else None


def claim(name, now=None):
    """One-time self-serve key. Returns (http_status, payload). The plaintext key only ever exists in the
    returned payload; the keys file gets its SHA-256. Caller must serialize calls (service holds a lock)."""
    now = time.time() if now is None else now
    n = norm(name)
    if not n:
        return 400, {"error": "Enter your first name (letters, numbers, - _ . only)."}
    cl = load_claims()
    c = cl.get(n)
    if not isinstance(c, dict):
        return 404, {"error": "There's no key waiting for that name. Check the spelling, or ask the owner to open one for you."}
    if c.get("claimed_at"):
        return 409, {"error": "That key was already collected. If it wasn't you, or you lost it, ask the owner to open a new one."}
    if now > float(c.get("expires") or 0):
        return 410, {"error": "This key offer has expired. Ask the owner to open a new one."}
    k = secrets.token_urlsafe(32)
    d = load(); d[n] = hashlib.sha256(k.encode()).hexdigest(); save(d)
    c["claimed_at"] = now; cl[n] = c; save_claims(cl)
    return 200, {"name": n, "key": k}


def main(argv):
    cmd = argv[1:2] and argv[1]
    d = load()
    if cmd == "add" and len(argv) == 4:
        name, out = argv[2], argv[3]
        k = secrets.token_urlsafe(32)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: f.write(k + "\n")
        os.chmod(out, 0o600)
        d[name] = hashlib.sha256(k.encode()).hexdigest(); save(d)
        print("key for %s written to %s (not printed)" % (name, out))
    elif cmd == "revoke" and len(argv) == 3:
        print("revoked" if d.pop(argv[2], None) else "no such name"); save(d)
    elif cmd == "open-claim" and len(argv) in (3, 4):
        n = norm(argv[2])
        try:
            days = float(argv[3]) if len(argv) == 4 else 7.0
        except ValueError:
            days = -1
        if not n or not 0 < days <= 30:
            print("name must be letters/numbers (-_.), days 0-30"); return 2
        cl = load_claims(); now = time.time()
        cl[n] = {"opened": now, "expires": now + days * 86400}; save_claims(cl)
        print("claim slot open for %s until %s (one use)" % (n, time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(now + days * 86400))))
    elif cmd == "close-claim" and len(argv) == 3:
        cl = load_claims(); n = norm(argv[2])
        print("closed" if n and cl.pop(n, None) is not None else "no such slot"); save_claims(cl)
    elif cmd == "list":
        print("\n".join(sorted(d)) or "(no keys)")
        now = time.time()
        for n, c in sorted(load_claims().items()):
            st = "claimed" if c.get("claimed_at") else ("expired" if now > float(c.get("expires") or 0) else
                 "open until " + time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(float(c["expires"]))))
            print("claim %s: %s" % (n, st))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
