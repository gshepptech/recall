#!/usr/bin/env python3
"""Recall SessionStart hook: inject a concise brief of relevant team memory.

Auto-detects the current repo -> project, fetches that project's top facts plus
global conventions, and prints a short brief that Claude Code injects into the
session. Silent + fail-safe: any error (no creds, server unreachable) exits 0
and prints nothing, so it never blocks or slows a session.

Reads creds from ~/.recall/token (written by /recall:connect):
    RECALL_URL=http://<server>:8000
    RECALL_TOKEN=<token>
"""
import json
import os
import subprocess
import sys
import urllib.request

CRED = os.path.expanduser("~/.recall/token")
if not os.path.exists(CRED):
    sys.exit(0)

url = tok = ""
try:
    for line in open(CRED):
        if line.startswith("RECALL_URL="):
            url = line.split("=", 1)[1].strip()
        elif line.startswith("RECALL_TOKEN="):
            tok = line.split("=", 1)[1].strip()
except Exception:
    sys.exit(0)
if not url or not tok:
    sys.exit(0)

def project_name():
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=3).stdout.strip()
        return os.path.basename(root).lower() if root else ""
    except Exception:
        return ""

def search(project, limit):
    if not project:
        return []
    body = json.dumps({"command": "search", "query": "*",
                       "project": project, "limit": limit}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/webhook/recall", data=body,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.load(r).get("results", []) or []
    except Exception:
        return []

proj = project_name()
glob = search("global", 5)
projr = search(proj, 6)
if not glob and not projr:
    sys.exit(0)

def fmt(items):
    lines = []
    for it in items:
        t = (it.get("title") or "").strip()
        s = (it.get("snippet") or "").strip().replace("\n", " ")
        if len(s) > 140:
            s = s[:140] + "…"
        lines.append(f"- **{t}**: {s}" if s else f"- **{t}**")
    return "\n".join(lines)

print("## Recall: team memory")
if proj:
    print(f"\n_Context for **{proj}** + global conventions. Call the `recall_*` tools to recall more, "
          f"or `/recall:scour` to deepen this project's memory._")
if glob:
    print("\n**Global conventions**")
    print(fmt(glob))
if projr:
    print(f"\n**{proj}: project facts**")
    print(fmt(projr))
print("\n_If a fact looks stale, re-verify it against current code before relying on it._")
sys.exit(0)
