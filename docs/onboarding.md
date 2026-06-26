# Recall — Onboarding Guide

## Memory types

| Type | What it is | Example |
|------|-----------|---------|
| `decision` | Choices made and why | "Chose JWT over sessions — stateless fits our multi-region setup" |
| `architecture` | System design, schema, structure | "Auth service owns all token issuance. No other service mints tokens." |
| `requirement` | Features and specs | "Users must be able to export their data as CSV within 2 clicks" |
| `prompt` | Saved Claude Code prompts | "recall:rebuild_auth — runbook for replacing auth middleware" |
| `conversation` | Session summaries, diary entries, auto-captured context | Auto-logged by the Stop hook at session end |
| `error` | Bugs and fixes | "SQLite lock on concurrent writes — fixed by WAL mode" |

---

## User roles

> The role matrix below is enforced by Recall. `create_token` requires `owner` or `admin` role.

| Role | Search | Save memories | Save prompts | Create tokens | Delete |
|------|--------|--------------|-------------|--------------|--------|
| owner | yes | yes | yes | yes | yes |
| admin | yes | yes | yes | yes | no |
| developer | yes | yes | no | no | no |
| requirements_engineer | yes | requirements only | no | no | no |
| viewer | yes | no | no | no | no |

---

## Personas

Tokens have an optional `persona` string that shapes how the agent approaches its work:

| Persona | Focus |
|---------|-------|
| `architect` | System design, trade-offs, structure |
| `developer` | Code, implementation, bugs |
| `requirements_engineer` | Capturing and validating requirements |
| Any custom string | Whatever you define |

Set a persona when creating a token in the Web UI or via `create_token`.

---

## Onboarding: Web UI

1. Open https://recall.yourdomain.com (or your self-hosted URL)
2. Enter your token (issued by your admin via the Tokens tab)
3. Select your default project (e.g. `global`)
4. Browse memories, search, view runs, manage tokens
5. Copy the MCP config from Settings and paste it into Claude Desktop

---

## Onboarding: Claude Code

Your admin gives you two things: the **server URL** and your **token**. Then:

```bash
claude mcp add --transport http recall https://recall.yourdomain.com/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```

Restart Claude Code — the `recall_*` tools are now available, and you can talk to memory
naturally ("recall what we decided about auth", "remember we always X").

For `/recall:scour`, `/recall:connect`, and the auto-save hooks + statusline, install the
**Recall plugin** (this repo's [`plugin/`](../plugin/)) as a Claude Code plugin. Because the
repo is private, use the plugin (or a local clone) rather than fetching a raw URL.

---

## Adding a teammate

1. Open the Web UI → Tokens tab → Create token
2. Enter name, label, role, and default project
3. Share the token with your teammate
4. They paste the Claude Code install prompt above and enter the token when prompted

Recall runs on your server — teammates connect directly to your webhook URL. No tunnel needed.

---

## Projects

A project is a namespace like `global`, `backend`, or `mobile`.

- Use `global` for team-wide memories that everyone should see
- Use project names for scoped work — only developers on that project need to search it
- A token's `default_project` controls where memories land when no project is specified
- You can search across all projects by passing `"project": null` or omitting it

---

## How the hooks work

| Hook | When it fires | What it does |
|------|--------------|-------------|
| Stop | Every time a Claude Code session ends | Logs a diary entry to Recall automatically |
| PreCompact | Before context window reset | Saves a summary of the current context |

Both hooks are silent — they run in the background and never interrupt your work.
