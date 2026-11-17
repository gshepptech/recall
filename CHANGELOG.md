# Changelog

All notable changes to Recall are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Server and plugin versions are tracked
separately: the server version is in `recall/version.py`, the plugin version in
`plugin/.claude-plugin/plugin.json`.

## Unreleased

### Changed
- **Breaking:** every setting now uses the `RECALL_` prefix. Rename these keys in an
  existing `.env`:
  `DB_BACKEND` → `RECALL_DB_BACKEND`, `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`
  → `RECALL_DB_*`, `OPENAI_API_BASE` → `RECALL_EMBEDDING_API_BASE`, `OPENAI_API_KEY` →
  `RECALL_EMBEDDING_API_KEY`, `RECALL_EMBED_DIM` → `RECALL_EMBEDDING_DIM`.
- `recall --help` and the plugin command descriptions say what each command does.
- `recall update` no longer tries to sync client hook files.
- `setup.py` reads its version from `recall/version.py`.

### Fixed
- A token scoped to one project could delete or promote a memory in another project
  by id.
- A stored confidence of 0 ranked as full confidence.
- The server failed to start with `mcp` 2.x. The dependency is now pinned below 2.0.
- The first-run wizard saved `RECALL_URL` with `/webhook/recall` appended, which broke
  `/recall:connect` and the session brief.
- `./install.sh add-user` labelled every new token `unknown`.
- `recall_help` listed two `hygiene_report` aliases that the server rejects.
- On PostgreSQL, search results left out `access_count` and `confidence_score`.
- On PostgreSQL, a multi-word keyword search found nothing unless every word matched. It
  now falls back to matching any word, as SQLite does.
- Over MCP, a blocked tool reported `owner` as the required role instead of the tool's
  minimum role.

### Added
- GitHub Actions CI that runs `ruff check` and `pytest` on Python 3.10 and 3.12, and the
  integration suite against PostgreSQL with pgvector.
- Unit tests for the scoring helpers and a regression test for project-scoped deletes.
- A command reference (`docs/commands.md`), a setup guide (`docs/setup.md`) and an
  architecture guide (`docs/architecture.md`).

### Removed
- The unused `RECALL_PROJECT` setting.

## 1.1.0 - 2026-07-02 (plugin 0.4.0)

### Added
- Search results carry a `relevance` score between 0 and 1.
- A relevance floor, set with `RECALL_MIN_RELEVANCE` or per request with
  `min_relevance`. Suppressed matches are counted in `suppressed_low_relevance`.
- `confidence` on saves is stored as `confidence_score`, kept across later saves, and
  used in ranking.
- `/recall:scour` passes its post-skeptic confidence on every save.
- A retrieval evaluation harness: `python -m recall.tests.eval_retrieval`.

## 1.0.13 - 2026-06-29 (plugin 0.3.0)

### Added
- `/recall:scour`: a multi-agent read of a codebase with reader and skeptic agents,
  `file:line` evidence and commit-SHA provenance.
- `/recall:track`: chained `post-commit` and `post-merge` hooks that run an incremental
  scour on each change.
- `/recall:connect`: registers the MCP server from `~/.recall/token`, so the token never
  enters the chat.
- A SessionStart brief that loads the current repo's facts and global conventions.
- A configurable embedding dimension and a bundled local Ollama embedder.
- One-command deploy: `Dockerfile`, a Compose stack with PostgreSQL and pgvector, and
  `install.sh` (`up`, `embedder`, `add-user`, `down`).
- Claude Code marketplace manifest.
