---
description: Connect this Claude Code to your team's Recall memory server (one-time setup).
argument-hint: "<server-url> <token>"
allowed-tools: Bash
---

# /recall:connect — wire Claude Code to the team Recall server

Parse `$ARGUMENTS` as `<server-url> <token>`, where `<server-url>` is the BASE url
(e.g. `http://recall-1:8000`, no `/mcp`). If either is missing, ask the user.

Run this (substituting the values):

```bash
URL="<server-url>"; TOKEN="<token>"
# 1. register the MCP server at USER scope (available in every project + headless hooks)
claude mcp add --transport http recall "$URL/mcp" --header "Authorization: Bearer $TOKEN" -s user
# 2. write creds for the SessionStart brief + git-hook incremental scour to use
mkdir -p ~/.recall
printf 'RECALL_URL=%s\nRECALL_TOKEN=%s\n' "$URL" "$TOKEN" > ~/.recall/token
chmod 600 ~/.recall/token
# 3. confirm
claude mcp list | grep -i recall || true
```

Then tell the user:
- **Restart Claude Code.** From the next session, the `recall_*` tools are live and a short
  **memory brief auto-loads** for the current repo (project facts + global conventions).
- Just talk — *"recall what we decided about auth"*, *"remember we always X"* — Claude calls
  the tools itself.
- `/recall:scour` to seed a repo's knowledge; `/recall:track` to keep it fresh on every commit.

Note: the database + embedder live on the server. This machine only stores the URL + token
(in `~/.recall/token`, mode 600). Nothing else is installed locally.
