# Contributing to Recall

## Local development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[postgres,dev]"
cp .env.example .env          # set RECALL_TOKEN
python -m recall
```

## Checks

Run both before opening a pull request. CI runs the same commands.

```bash
ruff check .
pytest
```

The integration suites start their own server on a free port with a temporary SQLite
database, so they need no setup. If you change ranking, also run
`python -m recall.tests.eval_retrieval` and include the before and after numbers.

## Pull requests

1. Branch from `main` and keep each pull request to one change.
2. Add or update tests for behaviour you change.
3. Update the docs in `docs/` and `CHANGELOG.md` in the same pull request.
4. Use Conventional Commit messages, for example `fix(search): clamp negative limits`.

## Reporting bugs

Open an issue with the bug report template. Include the server log, the backend
(SQLite or PostgreSQL) and the request that failed, with tokens removed.
