# Changelog

Recall is a fork of [Zikra](https://github.com/getzikra/zikra) (MIT). This changelog
starts at the fork; full history is in git.

## Unreleased

### Added
- **`/recall:scour`** — deliberate, evidence-backed codebase comprehension (reader + skeptic agents).
- **`/recall:track`** — git commit/merge hooks for incremental, hands-off memory refresh.
- **`/recall:connect`** — token-safe MCP registration (token read from `~/.recall/token`, never via chat).
- **SessionStart auto-brief** — injects the current repo's facts + global conventions at session start.
- **Config-driven embedding dimension** (`RECALL_EMBED_DIM`) so any embedder fits.
- **Bundled local embedder** (Ollama / `nomic-embed-text`) for zero-egress semantic search.
- **One-command deploy** — `Dockerfile` + containerized `docker-compose` stack + `install.sh` (`up` / `embedder` / `add-user`).
- Claude Code **marketplace plugin** (`plugin/`) + `marketplace.json`.

### Changed
- Rebranded Zikra → Recall; package, env vars (`RECALL_*`), MCP tools (`recall_*`), and `/webhook/recall`.
- Generic git-repo-based project detection (removed author-specific hardcoding).

### Removed
- Zikra's client-integration subsystem replaced by the plugin + deliberate-write design:
  interactive `installer.py`, `update.sh`, the auto-log/statusline/Codex/Gemini `hooks/`,
  the n8n watcher `daemon/`, raw-fetch `prompts/`, and `extras/`.
