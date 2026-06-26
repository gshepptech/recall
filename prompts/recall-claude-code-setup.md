> This prompt is for Claude Code only — hooks, statusline, MCP config, session autolog.
> Gemini CLI and Codex setup prompts are coming soon.
> To update the Recall server itself, run ./update.sh on your server host.
> See prompts/recall-server-update.md for the server runbook.

# recall-claude-code-setup
Install or update Recall persistent memory for Claude Code.
Handles both first install and updates — run the same prompt either way.

Follow every step in order. Run all bash commands exactly as shown.
Proceed without asking for confirmation between steps.

---

## Step 1 — Check if already installed

```bash
cat ~/.recall/token 2>/dev/null
```

Parse the output. If `RECALL_URL`, `RECALL_TOKEN`, and `RECALL_PROJECT` are all present and non-empty:
- Source the file: `source ~/.recall/token`
- Set `MY_TOKEN="$RECALL_TOKEN"`
- Skip to **Step 5** (update hooks only — do not re-create token, do not overwrite CLAUDE.md)

Otherwise continue to Step 2.

---

## Step 2 — Ask 4 questions

Ask these four questions one at a time. Wait for each answer.

**Q1 — Recall URL**
Where is your Recall server running?
- Recall (local): `http://localhost:8000`
- Recall (remote): `https://yourserver.com/webhook/recall`

**Q2 — Admin token**
The token from your server admin, or the value of `RECALL_TOKEN` in `.env` on the server.
This is used once to create your machine token.

**Q3 — Your name**
First name or handle (lowercase, no spaces, e.g. `mukarram`).

**Q4 — Default project**
Leave blank to use `global`. Otherwise a lowercase project name (e.g. `backend`, `mobile`).

Store answers:
```
RECALL_URL=<Q1>
ADMIN_TOKEN=<Q2>
RECALL_PERSON=<Q3, lowercased>
RECALL_PROJECT=<Q4 or "global">
RECALL_MACHINE=$(hostname)
```

---

## Step 3 — Create a token for this user+machine

Use the admin token to register a developer token for this machine:

```bash
RESPONSE=$(curl -s -X POST "$RECALL_URL" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{
    \"command\":      \"create_token\",
    \"person_name\":  \"$RECALL_PERSON\",
    \"token_name\":   \"${RECALL_PERSON}-${RECALL_MACHINE}\",
    \"role\":         \"developer\",
    \"project\":      \"$RECALL_PROJECT\"
  }")
echo "$RESPONSE"
```

Parse the response:
- Contains `"token"` field → extract value as `MY_TOKEN`
- Contains `"already exists"` → ask: *"A token for this machine already exists. Paste your existing token:"* → store answer as `MY_TOKEN`
- Contains `401` or `Unauthorized` → admin token is wrong, return to Step 2 Q2

---

## Step 4 — Save credentials

```bash
mkdir -p ~/.recall
cat > ~/.recall/token <<EOF
RECALL_URL=$RECALL_URL
RECALL_TOKEN=$MY_TOKEN
RECALL_PROJECT=$RECALL_PROJECT
RECALL_PERSON=$RECALL_PERSON
RECALL_MACHINE=$RECALL_MACHINE
EOF
chmod 600 ~/.recall/token
```

Confirm by printing: `cat ~/.recall/token`

---

## Step 5 — Install/update hooks

Determine which raw GitHub URL to use:

```bash
RECALL_RAW="https://raw.githubusercontent.com/gshepptech/recall/main"
```

Download and install the autolog hook:

```bash
mkdir -p ~/.claude
curl -fsSL "$RECALL_RAW/hooks/recall_autolog.sh" -o ~/.claude/recall_autolog.sh
chmod +x ~/.claude/recall_autolog.sh
```

Replace all four placeholders (macOS uses `sed -i ''`, Linux/WSL uses `sed -i`):

```bash
OS="$(uname -s)"
SED_I() { [[ "$OS" == "Darwin" ]] && sed -i '' "$@" || sed -i "$@"; }

SED_I "s|RECALL_URL_PLACEHOLDER|${RECALL_URL}|g"                          ~/.claude/recall_autolog.sh
SED_I "s|RECALL_TOKEN_PLACEHOLDER|${MY_TOKEN}|g"                         ~/.claude/recall_autolog.sh
SED_I "s|DEFAULT_PROJECT_PLACEHOLDER|${RECALL_PROJECT}|g"                ~/.claude/recall_autolog.sh
```

Verify no placeholders remain:

```bash
grep "PLACEHOLDER" ~/.claude/recall_autolog.sh \
  && echo "WARNING: placeholders remain — check sed output above" \
  || echo "✓ recall_autolog.sh patched"
```

---

## Step 6 — Install CLAUDE.md (only if not already present)

```bash
OS="$(uname -s)"
SED_I() { [[ "$OS" == "Darwin" ]] && sed -i '' "$@" || sed -i "$@"; }

_patch_recall_claudemd() {
  SED_I "s|RECALL_URL_PLACEHOLDER|${RECALL_URL}|g"           "$1"
  SED_I "s|RECALL_TOKEN_PLACEHOLDER|${MY_TOKEN}|g"          "$1"
  SED_I "s|DEFAULT_PROJECT_PLACEHOLDER|${RECALL_PROJECT}|g" "$1"
  SED_I "s|RUNNER_PLACEHOLDER|${RECALL_PERSON}@${RECALL_MACHINE}|g" "$1"
}

if [ ! -f ~/.claude/CLAUDE.md ]; then
  curl -fsSL "$RECALL_RAW/context/CLAUDE.md" -o ~/.claude/CLAUDE.md
  _patch_recall_claudemd ~/.claude/CLAUDE.md
  echo "✓ CLAUDE.md installed"
elif grep -q "Recall" ~/.claude/CLAUDE.md 2>/dev/null; then
  echo "~ CLAUDE.md already contains Recall section — skipping"
else
  echo "CLAUDE.md already exists. Appending Recall section."
  _TMP_ZIKRA="$(mktemp)"
  curl -fsSL "$RECALL_RAW/context/CLAUDE.md" -o "$_TMP_ZIKRA"
  _patch_recall_claudemd "$_TMP_ZIKRA"
  printf '\n\n---\n## Recall Memory System\n\n' >> ~/.claude/CLAUDE.md
  cat "$_TMP_ZIKRA" >> ~/.claude/CLAUDE.md
  rm -f "$_TMP_ZIKRA"
  echo "✓ Recall section appended to existing CLAUDE.md"
fi
```

---

## Step 7 — Wire hooks into settings.json

Run the following Python inline. It adds Stop and PreCompact hooks without duplicating them if already present:

```bash
python3 - <<'PYEOF'
import json, os

settings_path = os.path.expanduser("~/.claude/settings.json")
autolog       = os.path.expanduser("~/.claude/recall_autolog.sh")

s = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        try:
            s = json.load(f)
        except json.JSONDecodeError:
            s = {}

s.setdefault("hooks", {})

# Stop hook
s["hooks"].setdefault("Stop", [])
stop_present = any(
    any(h.get("command") == autolog for h in e.get("hooks", []))
    for e in s["hooks"]["Stop"]
)
if not stop_present:
    s["hooks"]["Stop"].append({
        "matcher": "",
        "hooks": [{"type": "command", "command": autolog}]
    })
    print("✓ Stop hook wired")
else:
    print("~ Stop hook already present")

# PreCompact hook
s["hooks"].setdefault("PreCompact", [])
precompact_present = any(
    any(h.get("command") == autolog for h in e.get("hooks", []))
    for e in s["hooks"]["PreCompact"]
)
if not precompact_present:
    s["hooks"]["PreCompact"].append({
        "matcher": "auto",
        "hooks": [{"type": "command", "command": autolog}]
    })
    print("✓ PreCompact hook wired")
else:
    print("~ PreCompact hook already present")

with open(settings_path, "w") as f:
    json.dump(s, f, indent=2)
PYEOF
```

---

## Step 8 — Register this machine (new installs only)

Skip this step if you came from Step 1 (already installed).

```bash
curl -s -X POST "$RECALL_URL" \
  -H "Authorization: Bearer $MY_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{
    \"command\":     \"save_memory\",
    \"project\":     \"$RECALL_PROJECT\",
    \"memory_type\": \"decision\",
    \"title\":       \"machine onboarded: ${RECALL_MACHINE} (${RECALL_PERSON})\",
    \"content_md\":  \"Recall installed on ${RECALL_MACHINE} for ${RECALL_PERSON}. URL: ${RECALL_URL}. Project: ${RECALL_PROJECT}.\",
    \"tags\":        null,
    \"created_by\":  \"${RECALL_PERSON}@${RECALL_MACHINE}\"
  }" > /dev/null && echo "✓ Machine registered"
```

---

## Step 9 — Test the connection

```bash
SEARCH_RESP=$(curl -s -X POST "$RECALL_URL" \
  -H "Authorization: Bearer $MY_TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: curl/7.81.0" \
  -d "{\"command\":\"search\",\"query\":\"recall\",\"project\":\"$RECALL_PROJECT\",\"limit\":1}")

echo "$SEARCH_RESP"
```

- Response contains `"results"` array → **SUCCESS** — continue to Step 10
- Response contains `"error"` or no JSON → **FAIL** — print the full response, stop here, and tell the user what went wrong

---

## Step 10 — Print summary

Print this block with real values substituted:

```
─────────────────────────────────────────────────
  Recall connected ✓
─────────────────────────────────────────────────
  Machine : <RECALL_MACHINE>
  User    : <RECALL_PERSON>
  URL     : <RECALL_URL>
  Token   : <first 8 chars of MY_TOKEN>...
  Project : <RECALL_PROJECT>
  Status  : Recall connected   ← new install
            Recall updated     ← hooks refreshed
─────────────────────────────────────────────────
  Next: Start a new Claude Code session.
        Memory is active from the first message.
─────────────────────────────────────────────────
```

---

## Step 11 — Install statusline (Recall bar)

```bash
mkdir -p ~/.claude/hooks ~/.claude/cache

# Download statusline script
curl -fsSL $RECALL_RAW/hooks/recall-statusline.js \
  -o ~/.claude/hooks/recall-statusline.js
chmod +x ~/.claude/hooks/recall-statusline.js

# Patch placeholders
if [ "$OS" = "Darwin" ]; then
  sed -i '' "s|RECALL_URL_PLACEHOLDER|$RECALL_URL|g" ~/.claude/hooks/recall-statusline.js
  sed -i '' "s|RECALL_TOKEN_PLACEHOLDER|$MY_TOKEN|g" ~/.claude/hooks/recall-statusline.js
  sed -i '' "s|DEFAULT_PROJECT_PLACEHOLDER|$RECALL_PROJECT|g" ~/.claude/hooks/recall-statusline.js
else
  sed -i "s|RECALL_URL_PLACEHOLDER|$RECALL_URL|g" ~/.claude/hooks/recall-statusline.js
  sed -i "s|RECALL_TOKEN_PLACEHOLDER|$MY_TOKEN|g" ~/.claude/hooks/recall-statusline.js
  sed -i "s|DEFAULT_PROJECT_PLACEHOLDER|$RECALL_PROJECT|g" ~/.claude/hooks/recall-statusline.js
fi

# Seed the stats cache
echo '{"runs_today":0,"runs_total":0,"memory_count":0,"last_saved":null,"project":"'$RECALL_PROJECT'"}' \
  > ~/.claude/cache/recall-stats.json

# Download and install stats update hook
curl -fsSL $RECALL_RAW/hooks/recall-stats-update.sh \
  -o ~/.claude/hooks/recall-stats-update.sh
chmod +x ~/.claude/hooks/recall-stats-update.sh
```

Wire statusLine and stats update hook in settings.json using python3:
```python
import json, os
path = os.path.expanduser('~/.claude/settings.json')
s = json.load(open(path)) if os.path.exists(path) else {}

# Wire statusline
hook_cmd = 'node ~/.claude/hooks/recall-statusline.js'
if s.get('statusLine', {}).get('command') != hook_cmd:
    s['statusLine'] = {'type': 'command', 'command': hook_cmd}
    print('Statusline wired')
else:
    print('Statusline already wired')

# Wire stats update hook to Stop
home = os.path.expanduser('~')
stats_cmd = f'bash {home}/.claude/hooks/recall-stats-update.sh'
stop_hooks = s.setdefault('hooks', {}).setdefault('Stop', [])
if not any(stats_cmd in str(h) for h in stop_hooks):
    stop_hooks.append({'hooks': [{'type': 'command', 'command': stats_cmd, 'timeout': 10}]})
    print('Stats update hook wired to Stop')
else:
    print('Stats update hook already wired')

json.dump(s, open(path, 'w'), indent=2)
```

Print: Recall bar installed. Restart Claude Code to see it.

---

## Keeping Recall updated

Run `recall update` to pull the latest version and refresh hooks.
You will see a warning at startup if your install is behind:

```
⚠  Recall update available — run: recall update
```

`recall update` will:
1. Pull the latest code from GitHub (`git pull origin main`)
2. Re-run `pip install -e .` (or `.[postgres]` for Postgres installs)
3. Compare hook files in `hooks/` against your `~/.claude/` installs and update any that differ
4. Restart the systemd service automatically if it is running
5. Print a summary of what changed
