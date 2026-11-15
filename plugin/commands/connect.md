---
description: Register the Recall MCP server from credentials saved in ~/.recall/token. The token never enters the conversation.
allowed-tools: Bash
---

# /recall:connect — register Recall (token-safe)

Recall reads your credentials from `~/.recall/token` — so your token is **never typed into this
conversation**. You save it once in your terminal (silently), then this command just registers
the MCP server using it.

Run exactly this:

```bash
if [ ! -f "$HOME/.recall/token" ]; then
  echo "No saved credentials yet."
  echo "In your TERMINAL (not here), run this ONCE — it reads the token silently, so it never"
  echo "appears on screen, in shell history, or in any chat:"
  echo
  echo "  read -rp 'Recall URL (http://host:8000): ' U; read -rsp 'Recall token: ' T; echo; \\"
  echo "  mkdir -p ~/.recall; printf 'RECALL_URL=%s\\nRECALL_TOKEN=%s\\n' \"\$U\" \"\$T\" > ~/.recall/token; \\"
  echo "  chmod 600 ~/.recall/token; unset T"
  echo
  echo "Then re-run /recall:connect."
  exit 0
fi
set -a; . "$HOME/.recall/token"; set +a
claude mcp remove recall >/dev/null 2>&1 || true
claude mcp add --transport http recall "$RECALL_URL/mcp" --header "Authorization: Bearer $RECALL_TOKEN" -s user
echo "✓ Recall registered at user scope from ~/.recall/token."
echo "  Restart Claude Code — the recall_* tools + the SessionStart memory brief load next session."
```

Why this is safe: the token is read from the file into an environment variable and passed to
`claude mcp add` **by reference** (`$RECALL_TOKEN`), so its value never appears in this
conversation. It lives only in your local MCP config and `~/.recall/token` (mode 600) — on your
machine, never in the repo, never in chat.

(`<RECALL_URL>` is the base URL, e.g. `http://host:8000`, no `/mcp`. The URL is not a secret —
only the token is, which is why only the token uses the silent prompt.)
