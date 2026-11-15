---
description: Keep this repo indexed in Recall. Installs git post-commit and post-merge hooks that save facts from each change to shared memory.
allowed-tools: Bash
---

# /recall:track — enable automatic incremental scour for this repo

Run the installer against the current working directory:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/recall-track"
```

This installs (idempotently, chaining onto any existing hooks):
- a **post-commit** hook → incrementally scours that commit's changed files
- a **post-merge** hook → catches changes pulled from teammates

After this, nobody runs anything: every commit/merge fires a headless incremental
scour (high-confidence facts only; ambiguous ones are skipped for a later manual
`/recall:scour` review) and updates the **shared** Recall memory the whole team reads.

Requirements:
- The `recall` MCP server must be registered at **user scope** so the headless `claude -p`
  run inside the git hook can reach it. `/recall:connect` does this.
- Tell the user it's reliable across terminal-close (fires on commit, not on session end),
  local (no CI), and only captures committed — never half-written — code.
