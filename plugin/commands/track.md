---
description: Keep this repo indexed in Recall. Installs git post-commit and post-merge hooks that save facts from each change to shared memory.
allowed-tools: Bash
---

# /recall:track: enable automatic incremental scour for this repo

Run the installer against the current working directory:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/recall-track"
```

This installs (idempotently, chaining onto any existing hooks):
- a post-commit hook that scours the files changed in that commit
- a post-merge hook that picks up changes pulled from teammates

After this, every commit or merge fires a headless incremental scour and updates the
shared Recall memory the team reads. It saves high-confidence facts only and skips
ambiguous ones for a later manual `/recall:scour`.

Requirements:
- The `recall` MCP server must be registered at user scope so the headless `claude -p`
  run inside the git hook can reach it. `/recall:connect` does this.
- Tell the user that the hooks fire on commit rather than on session end, so closing a
  terminal does not lose anything. They run locally with no CI, and they only read
  committed code.
