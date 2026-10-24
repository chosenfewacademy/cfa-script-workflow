#!/usr/bin/env python3
"""Operator CLI for Chris's feedback (used by the 8/13/18/23 ET routine).
  fb.py list [--status submitted]      fb.py inbox (items not yet resolved)
  fb.py set <id> in_progress|ready|declined [--resolution TEXT] [--accept] [--rule TEXT]
Writes the same files as the service (CFA_RENDER_DATA/feedback)."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import service as S
a = argparse.ArgumentParser(); sp = a.add_subparsers(dest="cmd", required=True)
l = sp.add_parser("list"); l.add_argument("--status")
sp.add_parser("inbox")
s = sp.add_parser("set"); s.add_argument("id"); s.add_argument("status"); s.add_argument("--resolution"); s.add_argument("--accept", action="store_true"); s.add_argument("--rule")
o = a.parse_args()
if o.cmd in ("list", "inbox"):
    for it in S.fb_items():
        if (o.cmd == "inbox" and it["status"] in ("ready", "declined")) or (getattr(o, "status", None) and it["status"] != o.status):
            continue
        print(json.dumps({k: it[k] for k in ("id", "status", "kind", "step", "rating", "ref", "episode", "comment")}))
else:
    print(json.dumps(S.fb_status(o.id, {"status": o.status, "resolution": o.resolution, "accept": o.accept, "rule": o.rule})))
