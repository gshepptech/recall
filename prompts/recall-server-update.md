# recall-server-update

> This prompt updates the **Recall server** (the Docker container or bare-Python process).
> To configure your Claude Code client (hooks, statusline, MCP token), use `prompts/recall-claude-code-setup.md` instead.

Update the Recall server safely — detects Docker or bare Python automatically.
Follow every step in order. Run all bash commands exactly as shown.
Proceed without asking for confirmation between steps.

---

## Step 1 — Locate the Recall installation

```bash
ls ~/recall 2>/dev/null && echo "FOUND ~/recall" || echo "NOT AT ~/recall"
```

If found, set `RECALL_DIR="$HOME/recall"`.
If not found, ask the user where Recall is installed and use that path throughout.

---

## Step 2 — Check for pending commits

```bash
cd "$RECALL_DIR"
git fetch origin main --quiet
git log HEAD..origin/main --oneline
```

If the output is **empty**, the server is already up to date — report this and stop.

Store the commit list for the summary in Step 6.

---

## Step 3 — Snapshot any local edits

```bash
git status --short
```

If there are **any local changes**:

```bash
WIP="local-wip-$(date +%Y-%m-%d-%H%M%S)"
git checkout -b "$WIP"
git add -A
git commit -m "wip: snapshot before update $(date +%Y-%m-%d)"
git checkout main
echo "Saved to branch: $WIP"
```

Record the branch name for the summary.

---

## Step 4 — Pull latest code

```bash
git pull origin main
```

---

## Step 5 — Detect runtime and restart

```bash
docker inspect recall 2>/dev/null && echo "DOCKER_RUNNING" || echo "NO_DOCKER"
```

**If Docker:**

```bash
# Determine mount type
docker inspect recall --format '{{range .Mounts}}{{.Source}} {{end}}'
```

- If the output contains `$RECALL_DIR` → bind-mounted source:
  ```bash
  docker restart recall
  sleep 4
  docker inspect --format='{{.State.Health.Status}}' recall
  ```

- If not bind-mounted → image-baked:
  ```bash
  docker compose up -d --build recall   # or: docker build -t recall . && docker restart recall
  sleep 4
  docker inspect --format='{{.State.Health.Status}}' recall
  ```

**If no Docker (bare Python):**

```bash
cd "$RECALL_DIR"
source .venv/bin/activate 2>/dev/null || true
pip install -e . --quiet
```

Tell the user: "Restart `python3 -m recall` manually to apply changes."

---

## Step 6 — Print summary

Report:

```
─────────────────────────────────────────────────
  Recall server updated ✓
─────────────────────────────────────────────────
  Commits pulled : <count from Step 2>
  Runtime        : Docker (bind-mount | image-baked) | bare Python
  Container      : <health status if Docker>
  WIP branch     : <branch name if created in Step 3, else —>
─────────────────────────────────────────────────
  ⚠  MCP clients (Claude Code, claude.ai, Cursor) must
     reconnect after any container restart.
─────────────────────────────────────────────────
```

---

## Quick reference

| Task | Command |
|------|---------|
| Run this script automatically | `./update.sh` from the server host |
| Check current version | `curl http://localhost:8000/health` |
| View logs (Docker) | `docker logs recall --tail 50` |
| Update Claude Code hooks only | Run `prompts/recall-claude-code-setup.md` |
