<div align="center">

<img src="../assets/recall-logo.svg" alt="Recall" width="110" height="110" />

# Join Recall

**Shared team memory for Claude Code — you'll be up in ~2 minutes.**

The server is already running. You're just plugging into it.

</div>

---

## ✅ Before you start

| You need | How to get it |
|---|---|
| **Tailscale**, connected | You already use it — check with `tailscale status`. Recall lives on the tailnet (nothing is public). |
| **A Recall token** | Ask your admin. *(Admin mints one with `./install.sh add-user <yourname> developer`.)* |
| **The Recall URL** | Your admin gives it to you — the server's tailnet address, e.g. `http://<host>:8000`. |

---

## 1 · Install the Recall plugin

Inside Claude Code:

```
/plugin marketplace add gshepptech/recall
/plugin install recall@recall
/reload-plugins
```

> Updating later? `/plugin marketplace update recall` then `/plugin install recall@recall`.

## 2 · Connect to the server

```
/recall:connect <RECALL_URL> <YOUR_TOKEN>
```

`<RECALL_URL>` is the **base** URL (e.g. `http://<host>:8000`, no `/mcp`). This one command
registers the memory server **and** saves your credentials locally so the auto-brief works.

## 3 · Restart Claude Code

That's it. 🎉 From your next session, a short **memory brief auto-loads** for whatever repo
you're in (its facts + global conventions) — Claude starts already knowing.

---

## 🧠 Using Recall

**Just talk** — Claude reads and writes the team's memory on its own:

> *"What's our auth pattern?"*
> *"Remember that we deploy on Tuesdays."*
> *"What did we decide about the database layer?"*

**Power moves** (run in a repo):

| Command | What it does | How often |
|---|---|---|
| `/recall:scour .` | Deeply reads this codebase → writes evidence-backed facts to shared memory | occasionally, to deepen |
| `/recall:track` | Turns on auto-refresh — every commit/merge updates memory, hands-off | **once** per repo |

After `/recall:track`, you never run anything for freshness — commits keep memory current automatically.

---

## 🗂 How memory is organized

| Scope | Holds | Example |
|---|---|---|
| **global** | Team-wide conventions, true everywhere | "We write tests first" |
| **project** (the repo name) | Facts about one codebase | "auth issues a 15-min JWT" |

Recall pulls from **both** automatically — you never specify a scope.

---

## 🛠 Troubleshooting

| Symptom | Fix |
|---|---|
| `recall` not connecting | Confirm you're on Tailscale (`tailscale status`); re-run `/recall:connect`; restart Claude Code |
| `/plugin install` errors | Make sure git can reach the private repo: `gh auth status` (you need `recall` org access) |
| Commands don't appear | `/reload-plugins`, then restart Claude Code |
| No memory brief at start | You haven't run `/recall:connect` yet (it writes the creds the brief needs), or there are no facts for this repo yet |
| Still stuck | Ping the admin — your token may need re-issuing |

---

<div align="center">

Welcome to the team brain. 📜

</div>
