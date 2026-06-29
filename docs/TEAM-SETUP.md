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
| **The Recall URL** | Your admin gives it to you — the server's tailnet name, e.g. `recall-1`. |

---

## 1 · Connect Claude Code to the memory

In your terminal:

```bash
claude mcp add --transport http recall http://<RECALL_URL>:8000/mcp \
  --header "Authorization: Bearer <YOUR_TOKEN>" -s user
```

> 💡 `-s user` makes Recall available in **every** project — don't skip it.

---

## 2 · Install the Recall commands

Inside Claude Code, type:

```
/plugin marketplace add gshepptech/recall
/plugin install recall@recall
```

---

## 3 · Restart Claude Code

That's it. You're in. 🎉

---

## 🧠 Using Recall

**Just talk** — Claude reads and writes the team's memory on its own:

> *"What's our auth pattern?"*
> *"Remember that we deploy on Tuesdays."*
> *"What did we decide about the database layer?"*

**Power moves** (run in a repo):

| Command | What it does |
|---|---|
| `/recall:scour .` | Deeply reads this codebase → writes evidence-backed facts to shared memory |
| `/recall:track` | Turn on auto-refresh — every commit updates memory (run once per repo) |

---

## 🛠 Troubleshooting

| Symptom | Fix |
|---|---|
| `claude mcp list` doesn't show `recall  ✔ Connected` | Confirm you're on Tailscale (`tailscale status`) and the URL + token are correct |
| `/plugin install` errors | Make sure your git can reach the private repo: `gh auth status` (you need `recall` org access) |
| Commands don't appear | Restart Claude Code (plugins load at startup) |
| Still stuck | Ping the admin — your token may need re-issuing |

---

<div align="center">

Welcome to the team brain. 📜

</div>
