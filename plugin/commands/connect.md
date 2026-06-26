---
description: Connect this Claude Code to your team's Recall memory server (one-time setup).
argument-hint: "<server-url> <token>"
allowed-tools: Bash
---

# /recall:connect — wire Claude Code to the team Recall server

Parse `$ARGUMENTS` as `<server-url> <token>`. If either is missing, ask the user for it.

1. Register the Recall MCP server:
   ```bash
   claude mcp add --transport http recall "<server-url>/mcp" --header "Authorization: Bearer <token>"
   ```
2. Confirm it connected:
   ```bash
   claude mcp list
   ```
   Look for `recall: ... ✔ Connected`.
3. Tell the user to **restart Claude Code** so the `recall_*` tools load, then they can:
   - `/recall:scour` to seed memory from a codebase, and
   - just talk naturally — "recall what we decided about auth", "remember we always X" — and
     Claude will call the `recall_*` tools itself.

Note: the embedder and database live on the server. This machine only needs the URL + token.
Nothing else is installed locally.
