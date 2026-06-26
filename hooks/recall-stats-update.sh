#!/bin/bash
# Recall stats updater — runs on Stop hook to bump runs_today counter

CACHE="$HOME/.claude/cache/recall-stats.json"
RECALL_URL="${RECALL_URL:-$(grep RECALL_URL "$HOME/.recall/token" 2>/dev/null | cut -d= -f2)}"
RECALL_TOKEN="${RECALL_TOKEN:-$(grep RECALL_TOKEN "$HOME/.recall/token" 2>/dev/null | cut -d= -f2)}"
RECALL_PROJECT="${RECALL_PROJECT:-$(grep RECALL_PROJECT "$HOME/.recall/token" 2>/dev/null | cut -d= -f2)}"
mkdir -p "$HOME/.claude/cache"

# Normalize URL: strip trailing slash, append suffix only if not already present
_SUFFIX="/webhook/recall"
RECALL_URL="${RECALL_URL%/}"
[[ "$RECALL_URL" != *"$_SUFFIX" ]] && RECALL_URL="${RECALL_URL}${_SUFFIX}"

# Read CWD from hook payload stdin for dynamic project detection
PAYLOAD="$(cat 2>/dev/null || echo '{}')"
HOOK_CWD="$(printf '%s' "$PAYLOAD" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" \
  2>/dev/null || echo "")"

# Detect project from CWD now (same logic as the python block below) so the
# memory-count query can be scoped to the current project. Without this the
# statusline shows the global total even when you're inside a specific repo.
PROJECT=$(python3 -c "
import sys, os, subprocess
cwd = sys.argv[1] if len(sys.argv) > 1 else ''
fallback = sys.argv[2] if len(sys.argv) > 2 else 'global'
def detect(cwd, fb):
    if not cwd: return fb
    try:
        root = subprocess.run(['git','-C',cwd,'rev-parse','--show-toplevel'],
                              capture_output=True, text=True, timeout=3).stdout.strip()
        if root: return os.path.basename(root).lower()
    except Exception: pass
    return os.path.basename(cwd).lower() if os.path.isdir(cwd) else fb
print(detect(cwd, fallback))
" "$HOOK_CWD" "${RECALL_PROJECT:-global}")

# Fetch live memory count from Recall, scoped to the current project so the
# '187 memories' tag actually reflects what's visible in this project. When
# PROJECT resolves to 'global', the server treats it as a wildcard and
# returns the cross-project total (the same behavior as before).
MEMORY_COUNT=$(curl -s -X POST "$RECALL_URL" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"search\",\"query\":\"*\",\"limit\":1,\"project\":\"$PROJECT\"}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', d.get('count', 0)))" 2>/dev/null || echo "0")

# Fetch server version
SERVER_VERSION=$(curl -s -X POST "$RECALL_URL" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"version"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('version',''))" 2>/dev/null || echo "")

# Fetch orphan/stale count for statusline warning. Silent fail on older
# servers that don't know the hygiene_report command.
ORPHAN_COUNT=$(curl -s -X POST "$RECALL_URL" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"hygiene_report\",\"project\":\"$PROJECT\",\"stale_days\":30}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('orphan_count',0))" 2>/dev/null || echo "0")

python3 - "$MEMORY_COUNT" "$HOOK_CWD" "${RECALL_PROJECT:-global}" "$SERVER_VERSION" "$ORPHAN_COUNT" <<'PYEOF'
import json, os, datetime, sys, socket

cache_path = os.path.expanduser('~/.claude/cache/recall-stats.json')
memory_count_arg   = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
hook_cwd           = sys.argv[2] if len(sys.argv) > 2 else ''
default_project    = sys.argv[3] if len(sys.argv) > 3 else 'global'
server_version_arg = sys.argv[4].strip() if len(sys.argv) > 4 else ''
orphan_count_arg   = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].lstrip('-').isdigit() else 0

def detect_project(cwd, fallback):
    if not cwd: return fallback
    import subprocess
    try:
        root = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=3).stdout.strip()
        if root: return os.path.basename(root).lower()
    except Exception: pass
    return os.path.basename(cwd).lower() if os.path.isdir(cwd) else fallback

project = detect_project(hook_cwd, default_project)

try:
    with open(cache_path) as f:
        stats = json.load(f)
except:
    stats = {"runs_today": 0, "runs_total": 0, "memory_count": 0, "updated_at": None, "project": project}

# Check if we need to reset daily counter
today = datetime.date.today().isoformat()
last_saved = stats.get("updated_at", "")[:10] if stats.get("updated_at") else ""

if last_saved != today:
    stats["runs_today"] = 0

stats["runs_today"] = stats.get("runs_today", 0) + 1
stats["runs_total"] = stats.get("runs_total", 0) + 1
stats["updated_at"] = datetime.datetime.now().isoformat()
stats["project"]    = project
# Update memory_count if we got a valid value; preserve previous value otherwise
if memory_count_arg > 0:
    stats["memory_count"] = memory_count_arg

# Always refresh orphan_count (0 is a valid state, not "missing data")
stats["orphan_count"] = max(0, orphan_count_arg)

# Cache server version if we got one
if server_version_arg:
    v = server_version_arg if server_version_arg.startswith('v') else f'v{server_version_arg}'
    stats["server_version"] = v

# Check latest Recall version from GitHub once per day (for update comparison)
version_checked = stats.get("version_checked", "")
if version_checked != today:
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/gshepptech/recall/tags",
            headers={"User-Agent": "recall-stats/1.0"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        tags = json.loads(resp.read().decode())
        if tags and isinstance(tags, list) and "name" in tags[0]:
            stats["latest_version"] = tags[0]["name"]
        stats["version_checked"] = today
    except:
        pass  # silent fail — keep previous cached value

with open(cache_path, 'w') as f:
    json.dump(stats, f)
PYEOF
