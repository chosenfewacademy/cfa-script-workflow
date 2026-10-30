"""Per-person renderer keys. Keys are never printed; only their SHA-256 is stored (0600 file, outside the repo).
  python3 keys.py add NAME OUTFILE   -> new key written to OUTFILE (chmod 600), hash stored
  python3 keys.py revoke NAME        -> key stops working on the next request (no restart)
  python3 keys.py list               -> names only"""
import hashlib, json, os, secrets, sys
F = os.environ.get("CFA_RENDER_KEYS_FILE", "/home/box/secrets/cfa_render_keys.json")
def load():
    try: return json.load(open(F))
    except (OSError, ValueError): return {}
def save(d):
    os.makedirs(os.path.dirname(F), exist_ok=True)
    tmp = F + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: json.dump(d, f, indent=1)
    os.replace(tmp, F); os.chmod(F, 0o600)
if __name__ == "__main__":
    cmd = sys.argv[1:2] and sys.argv[1]
    d = load()
    if cmd == "add" and len(sys.argv) == 4:
        name, out = sys.argv[2], sys.argv[3]
        k = secrets.token_urlsafe(32)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: f.write(k + "\n")
        os.chmod(out, 0o600)
        d[name] = hashlib.sha256(k.encode()).hexdigest(); save(d)
        print("key for %s written to %s (not printed)" % (name, out))
    elif cmd == "revoke" and len(sys.argv) == 3:
        print("revoked" if d.pop(sys.argv[2], None) else "no such name"); save(d)
    elif cmd == "list":
        print("\n".join(sorted(d)) or "(none)")
    else:
        print(__doc__); sys.exit(2)
