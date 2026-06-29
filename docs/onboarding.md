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

Install the plugin (inside Claude Code):

```
/plugin marketplace add gshepptech/recall
/plugin install recall@recall
```

Save your creds **in your terminal** (token read silently — never in chat/history):

```bash
read -rp 'Recall URL (http://host:8000): ' U; read -rsp 'Recall token: ' T; echo; \
mkdir -p ~/.recall; printf 'RECALL_URL=%s\nRECALL_TOKEN=%s\n' "$U" "$T" > ~/.recall/token; \
chmod 600 ~/.recall/token; unset T
```

Then register, in Claude Code: `/recall:connect`

Restart Claude Code. The `recall_*` tools load, a **memory brief auto-loads** each session, and
you can talk to memory naturally ("recall what we decided about auth", "remember we always X").
Then `/recall:scour` to seed a repo and `/recall:track` to keep it fresh on every commit.

→ Full step-by-step: **[TEAM-SETUP.md](TEAM-SETUP.md)**

---

## Adding a teammate

1. Admin mints a token: `./install.sh add-user <name> developer`
2. Share the **token** + the **server URL** with them.
3. They follow **[TEAM-SETUP.md](TEAM-SETUP.md)** — install plugin → `/recall:connect` → restart.

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
