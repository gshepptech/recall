# Recall HTTP command reference

Recall exposes one HTTP endpoint for commands. Every command is a JSON POST to
`/webhook/recall`. This page lists each command, the fields it reads, the role
it needs, and what it returns.

The examples use two shell variables:

```bash
export RECALL_URL=http://localhost:8000   # server base URL, default port 8000
export RECALL_TOKEN=...                   # a bearer token
```

## Request shape

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "<name>", "project": "myapp", ...}'
```

- `command` is required. It is lowercased and trimmed before lookup, so
  `"Search "` works.
- The token goes in `Authorization: Bearer <token>`. A `?token=<token>` query
  parameter is also accepted when the header is missing.
- `project` is optional for most commands. When it is missing the server uses
  `global`.

### Response metadata

Every response from a command handler carries `_use_command`, the canonical
command name. When you call an alias, the response also has
`"_was_alias": true` and `_raw_command`, the name you sent.

### Errors

Errors raised inside a handler (a missing field, a bad value, a record that is
not found) come back with HTTP 200 and an `error` field. Check for `error`,
not only the status code.

The server itself returns these status codes:

| Status | When | Body |
|---|---|---|
| 400 | Body is not valid JSON | `{"error": "Request body is not valid JSON"}` |
| 400 | Unknown command | `error`, `hint`, `available_commands`, `commands` (the `recall_help` list) |
| 401 | Missing or unknown token | `{"detail": "Unauthorized"}` |
| 403 | Role too low | `{"error": "insufficient permissions", "required_role": "<role>"}` |
| 403 | Token scoped to another project | `{"detail": {"error": "token_scope_mismatch", "project_scope": ..., "requested_project": ..., "message": ..., "hint": ...}}` |
| 503 | Database not ready | `{"detail": "Database not ready"}` or `"Database not initialised"` |

The server checks in this order: token, JSON body, project scope, role, then
command name.

## Roles

Each token has one role. A role can run its own commands and every command
of the roles below it.

| Role | How you get it | Can run |
|---|---|---|
| owner | Only the `RECALL_TOKEN` environment variable. It cannot be granted through the API. | Everything, including `create_token` |
| admin | `create_token` with `"role": "admin"` | Everything except `create_token` |
| developer | `create_token` default | Viewer commands plus `save_memory`, `save_prompt`, `save_requirement`, `promote_requirement`, `log_run`, `log_error` |
| viewer | `create_token` with `"role": "viewer"` | `search`, `get_memory`, `get_prompt`, `list_prompts`, `list_requirements`, `hygiene_report`, `version`, `recall_help` |

Admin adds `get_schema`, `delete_memory` and `debug_protocol` on top of
developer. A token with a role the server does not know is treated as viewer.

### Project scope

A token created with `project_scope` can only touch that project. The server
compares the request's `project` (or `global` when it is missing) with the
scope and returns 403 `token_scope_mismatch` when they differ. This check runs
for every command, so a scoped token must send `"project": "<scope>"` even on
`version` or `recall_help`.

## Command index

| Command | Aliases | MCP tool | Minimum role |
|---|---|---|---|
| [search](#search) | find, query, recall, lookup, search_memory, find_memory, retrieve, remember | `recall_search` | viewer |
| [save_memory](#save_memory) | save, store, write_memory, add_memory, write | `recall_save_memory` | developer |
| [get_memory](#get_memory) | fetch_memory, read_memory, load_memory | `recall_get_memory` | viewer |
| [delete_memory](#delete_memory) | remove_memory, forget_memory, forget | `recall_delete_memory` | admin |
| [get_prompt](#get_prompt) | run_prompt, fetch_prompt, load_prompt, execute_prompt | `recall_get_prompt` | viewer |
| [save_prompt](#save_prompt) | write_prompt, store_prompt | `recall_save_prompt` | developer |
| [list_prompts](#list_prompts) | get_prompts | `recall_list_prompts` | viewer |
| [log_run](#log_run) | log_session, end_session, finish_run, log_completion | `recall_log_run` | developer |
| [log_error](#log_error) | log_bug, report_error, save_error, log_failure | `recall_log_error` | developer |
| [save_requirement](#save_requirement) | none | `recall_save_requirement` | developer |
| [list_requirements](#list_requirements) | list_reqs, get_requirements | `recall_list_requirements` | viewer |
| [promote_requirement](#promote_requirement) | promote | `recall_promote_requirement` | developer |
| [create_token](#create_token) | new_token, token | `recall_create_token` | owner |
| [get_schema](#get_schema) | schema, get_db | `recall_get_schema` | admin |
| [hygiene_report](#hygiene_report) | none | `recall_hygiene_report` | viewer |
| [version](#version) | ver, server_version | no MCP tool | viewer |
| [recall_help](#recall_help) | help | `recall_help` | viewer |
| [debug_protocol](#debug_protocol) | debug, dp | no MCP tool | admin |

## Memory types

`search` accepts these values for `memory_type`: `conversation`, `decision`,
`error`, `note`, `prompt`, `requirement`. Any other value is rejected with
`valid_types` in the error.

The save commands do not check `memory_type`. A memory saved with another
value is stored, but you cannot filter `search` by it. Use one of the six
values above.

## How `global` works

The project name `global` means different things to different commands:

- `search`, `list_prompts` and `list_requirements` treat `global` as "all
  projects".
- `get_prompt`, `hygiene_report` and the title lookup in
  `promote_requirement` treat `global` as the project literally named
  `global`. Pass the real project name to find records in it.
- `get_memory` and `delete_memory` search every project when `project` is
  missing.

---

## search

Find memories with hybrid vector and keyword search. When no embedding is
available the search falls back to keyword matching.

Minimum role: viewer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | string | yes | | `q` and `text` are also read |
| `project` | string | no | `global` | `global` searches all projects |
| `limit` | integer | no | 10 | Clamped to 1 through 100 |
| `memory_type` | string | no | | One of the six memory types |
| `max_tokens` | integer | no | 2000 | Token budget for titles and snippets, at 4 characters per token. The first result is always returned. |
| `min_relevance` | number | no | `RECALL_MIN_RELEVANCE`, or 0.0 | Drops results whose `relevance` is below this value. 0 disables it. A non-numeric value falls back to the default. |

Snippets are cut to 500, 300, 200, 150 and 150 characters for the first five
results, and 150 after that.

Errors: `'limit' must be an integer`, `max_tokens must be an integer`,
`Invalid memory_type '<value>'` (with `valid_types`), `query is required`.
Each error also returns `"results": []`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "search", "project": "myapp", "query": "JWT expiry", "limit": 5, "min_relevance": 0.3}'
```

```json
{
  "results": [
    {
      "id": "ad1561e6-df65-4a53-bf8a-8fecd3db70b0",
      "title": "Use JWT with 15 minute expiry",
      "snippet": "Access tokens expire after 15 minutes.",
      "memory_type": "decision",
      "project": "myapp",
      "module": null,
      "score": 0.9,
      "relevance": 0.7589,
      "created_at": "2026-11-15 13:52:33"
    }
  ],
  "count": 1,
  "total": 3,
  "tokens_used": 25,
  "degraded": true,
  "warning": "semantic search unavailable, results are keyword-only",
  "_use_command": "search"
}
```

Response fields:

- `relevance` is the match strength for this query, from 0 to 1.
- `score` is the memory's health score from 0 to 1, based on age, access
  count and confidence. It does not depend on the query.
- On SQLite each result also carries `access_count` and `confidence_score`.
- `count` is the number of results returned. `total` is the number of
  searchable memories in the project (all projects for `global`).
- `tokens_used` is the estimated size of the returned titles and snippets.
- `suppressed_low_relevance` appears when `min_relevance` dropped results. It
  is the number dropped. When nothing is left, `note` explains why the list is
  empty.
- `degraded` is `true` when the search ran in a reduced mode. With
  `warning` it means no query embedding was available. With
  `degraded_reason` it names the keyword fallback that was used:
  `fts_or_fallback`, `like_fallback` or `all_search_methods_failed`.

## save_memory

Save a memory. A memory with the same `title`, `memory_type` and `project` is
updated in place.

Minimum role: developer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `title` | string | yes | | |
| `content_md` | string | no | `""` | `content` is also read. `[[Title]]` references become links to memories with that title in the same project or in `global`, if they exist at save time. |
| `project` | string | no | `global` | |
| `memory_type` | string | no | `conversation` | Not validated. See [Memory types](#memory-types). |
| `module` | string | no | null | |
| `tags` | array of strings | no | `[]` | |
| `resolution` | string | no | null | |
| `created_by` | string | no | null | |
| `confidence` | number | no | 1.0 | `confidence_score` is also read. Clamped to 0 through 1. A non-numeric value is ignored. |

On an update, `content_md`, `tags` and the embedding are replaced. Confidence
is replaced only when you send it. `module`, `resolution` and `created_by`
keep their first saved values.

Errors: `title is required`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "save_memory", "project": "myapp", "memory_type": "decision",
       "title": "Use JWT with 15 minute expiry",
       "content_md": "Access tokens expire after 15 minutes.",
       "tags": ["auth"], "confidence": 0.9, "created_by": "laptop"}'
```

```json
{
  "id": "ad1561e6-df65-4a53-bf8a-8fecd3db70b0",
  "title": "Use JWT with 15 minute expiry",
  "status": "saved",
  "_use_command": "save_memory"
}
```

When the embedding service is not available the memory is still saved, and
the response adds `"warning": "semantic embedding unavailable; keyword search only for this entry"`.
The same applies to `save_prompt` and `save_requirement`.

## get_memory

Fetch one memory by id or title. Each fetch adds 1 to its access count.

Minimum role: viewer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `id` | string | one of `id` or `title` | | Wins over `title` when both are sent |
| `title` | string | one of `id` or `title` | | Exact match |
| `memory_type` | string | no | | Narrows a title lookup |
| `project` | string | no | any project | Narrows the lookup to one project |

Errors: `title or id is required`, `Memory not found`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "get_memory", "project": "myapp", "title": "Use JWT with 15 minute expiry"}'
```

```json
{
  "id": "ad1561e6-df65-4a53-bf8a-8fecd3db70b0",
  "title": "Use JWT with 15 minute expiry",
  "content_md": "Access tokens expire after 15 minutes.",
  "memory_type": "decision",
  "project": "myapp",
  "module": null,
  "tags": ["auth"],
  "resolution": null,
  "access_count": 0,
  "created_at": "2026-11-15 13:52:33",
  "updated_at": "2026-11-15 13:52:33",
  "links_out": [],
  "links_in": [],
  "_use_command": "get_memory"
}
```

`access_count` is the value before this fetch. `links_out` and `links_in`
list linked memories as `{id, title, memory_type}`.

## delete_memory

Delete one memory permanently.

Minimum role: admin.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `id` | string | one of `id` or `title` | | `memory_id` is also read |
| `title` | string | one of `id` or `title` | | Used only when no id is sent |
| `memory_type` | string | no | | Narrows a title lookup |
| `project` | string | no | any project | Only a memory in this project is deleted, whether you send an id or a title |

Errors: `id or title is required`, `Memory not found` (with `id` when an id
was sent).

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "delete_memory", "project": "myapp", "id": "ad1561e6-df65-4a53-bf8a-8fecd3db70b0"}'
```

```json
{
  "deleted": true,
  "id": "ad1561e6-df65-4a53-bf8a-8fecd3db70b0",
  "title": "Use JWT with 15 minute expiry",
  "memory_type": "decision",
  "project": "myapp",
  "_use_command": "delete_memory"
}
```

## get_prompt

Fetch a saved prompt by name. Each fetch adds 1 to its access count.

Minimum role: viewer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `prompt_name` | string | yes | | `name` and `title` are also read. Exact title match. |
| `project` | string | no | `global` | Matches only this project. `global` is not a wildcard here. |
| `runner` | string | no | | Remembers that this runner fetched this prompt. The next `log_run` from the same runner and project links to it. |

Errors: `prompt_name is required`, `Prompt not found: <name>`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "get_prompt", "project": "myapp", "prompt_name": "code-review", "runner": "laptop"}'
```

```json
{
  "id": "f8e08a2b-177b-49db-8067-8a6d78fb8b7a",
  "title": "code-review",
  "content_md": "Review the diff for correctness.",
  "project": "myapp",
  "access_count": 1,
  "_use_command": "get_prompt"
}
```

`access_count` includes this fetch.

## save_prompt

Save a prompt. This is `save_memory` with `memory_type` set to `prompt`. A
prompt with the same title and project is updated.

Minimum role: developer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `title` | string | yes | | The name `get_prompt` looks up |
| `content_md` | string | no | `""` | `content` is also read |
| `project` | string | no | `global` | |
| `tags`, `module`, `resolution`, `created_by`, `confidence` | | no | | As in `save_memory` |

Errors: `title is required`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "save_prompt", "project": "myapp", "title": "code-review", "content_md": "Review the diff for correctness."}'
```

```json
{
  "id": "f8e08a2b-177b-49db-8067-8a6d78fb8b7a",
  "title": "code-review",
  "status": "saved",
  "type": "prompt",
  "_use_command": "save_prompt"
}
```

## list_prompts

List saved prompts, most accessed first, then newest.

Minimum role: viewer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project` | string | no | `global` | `global` lists all projects |
| `limit` | integer | no | 50 | Maximum 100 |

Errors: `'limit' must be an integer`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "list_prompts", "project": "myapp"}'
```

```json
{
  "count": 1,
  "prompts": [
    {
      "id": "f8e08a2b-177b-49db-8067-8a6d78fb8b7a",
      "title": "code-review",
      "snippet": "Review the diff for correctness.",
      "project": "myapp",
      "access_count": 1,
      "created_by": null,
      "created_at": "2026-11-15 13:52:39"
    }
  ],
  "status": "success",
  "_use_command": "list_prompts"
}
```

`snippet` holds the first 300 characters of the prompt.

## log_run

Record one agent run with its token usage. No field is required.

Minimum role: developer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project` | string | no | `global` | |
| `runner` | string | no | | Host or agent name |
| `prompt_id` | string | no | | When missing and `runner` is set, the server uses the prompt this runner last fetched with `get_prompt` in the same project, then clears that link |
| `prompt_name` | string | no | | |
| `status` | string | no | `success` | Free text |
| `output_summary` | string | no | | |
| `tokens_input` | integer | no | | |
| `tokens_output` | integer | no | | |
| `tokens_cache_read` | integer | no | | |
| `tokens_cache_creation` | integer | no | | |
| `cost_usd` | number | no | | |

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "log_run", "project": "myapp", "runner": "laptop", "prompt_name": "code-review",
       "output_summary": "Reviewed 3 files", "tokens_input": 1200, "tokens_output": 300, "cost_usd": 0.01}'
```

```json
{
  "id": "9316c96e-ed22-427f-9a43-e28d9846ad4e",
  "status": "logged",
  "_use_command": "log_run"
}
```

## log_error

Record an error, failure or blocker.

Minimum role: developer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `message` | string | yes | | `error` is also read. Must not be blank. |
| `project` | string | no | `global` | |
| `runner` | string | no | | |
| `error_type` | string | no | | |
| `stack_trace` | string | no | | |
| `context_md` | string | no | | |

A `title` field is not stored. Errors:
`message is required (use field name 'message' or 'error')`, with a `hint`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "log_error", "project": "myapp", "runner": "laptop", "error_type": "build", "message": "tsc failed"}'
```

```json
{
  "id": "0aa4be4d-005f-4108-a9ec-064c5551c474",
  "status": "logged",
  "_use_command": "log_error"
}
```

## save_requirement

Save a requirement or user story. This is `save_memory` with `memory_type`
set to `requirement` and the requirement marked pending.

Minimum role: developer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `title` | string | yes | | |
| `content_md` | string | no | `""` | `content` is also read |
| `project` | string | no | `global` | |
| `tags`, `module`, `resolution`, `created_by`, `confidence` | | no | | As in `save_memory` |

Errors: `title is required`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "save_requirement", "project": "myapp", "title": "Users can export memories", "content_md": "Export as JSON."}'
```

```json
{
  "id": "ec29b08e-7c44-4e04-9ceb-382f71d9b5df",
  "title": "Users can export memories",
  "status": "saved",
  "_use_command": "save_requirement"
}
```

## list_requirements

List requirements, most accessed first, then newest.

Minimum role: viewer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project` | string | no | `global` | `global` lists all projects |
| `status` | string | no | all | `pending` or `resolved` |
| `limit` | integer | no | 20 | Maximum 100 |

Errors: `'limit' must be an integer`, `Invalid status '<value>'` (with
`valid_values`).

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "list_requirements", "project": "myapp", "status": "pending"}'
```

```json
{
  "count": 1,
  "requirements": [
    {
      "id": "ec29b08e-7c44-4e04-9ceb-382f71d9b5df",
      "title": "Users can export memories",
      "snippet": "Export as JSON.",
      "project": "myapp",
      "access_count": 0,
      "created_by": null,
      "created_at": "2026-11-15 13:52:46"
    }
  ],
  "status": "success",
  "_use_command": "list_requirements"
}
```

## promote_requirement

Change a requirement into another memory type and clear its pending flag.
Only memories whose type is `requirement` can be promoted.

Minimum role: developer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `id` | string | one of `id` or `title` | | `requirement_id` is also read |
| `title` | string | one of `id` or `title` | | Used only when no id is sent |
| `project` | string | no | `global` for a title lookup | Only a requirement in this project is promoted. With an id and no project, any project matches. |
| `promote_to` | string | no | `prompt` | The new memory type. Not validated. |

Errors: `id, requirement_id, or title is required`,
`Requirement with title "<title>" not found`,
`Requirement not found or already promoted`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "promote_requirement", "project": "myapp", "title": "Users can export memories", "promote_to": "decision"}'
```

```json
{
  "status": "promoted",
  "id": "ec29b08e-7c44-4e04-9ceb-382f71d9b5df",
  "title": "Users can export memories",
  "_use_command": "promote_requirement"
}
```

## create_token

Create a bearer token. Only the owner token can call this.

Minimum role: owner.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `label` | string | no | `unknown` | Name for the token's holder. `person_name` is also read. |
| `role` | string | no | `developer` | `admin`, `developer` or `viewer`. `owner` cannot be granted. |
| `project_scope` | string | no | none | Restricts the token to this project |

Errors: `Invalid role '<value>'.` with `allowed_roles`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "create_token", "label": "ci-bot", "role": "viewer", "project_scope": "myapp"}'
```

```json
{
  "status": "created",
  "token": "token-c4df15d80b6f47f3",
  "label": "ci-bot",
  "person_name": "ci-bot",
  "role": "viewer",
  "project_scope": "myapp",
  "_use_command": "create_token"
}
```

The token is shown only in this response. Store it before you close the
terminal.

## get_schema

Return the database tables and their definitions. Takes no fields.

Minimum role: admin.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "get_schema"}'
```

```json
{
  "engine": "sqlite3 + sqlite-vec (aiosqlite)",
  "tables": ["access_tokens", "error_log", "memories", "memories_fts", "..."],
  "schema": {
    "memories": "CREATE TABLE memories (...)"
  },
  "_use_command": "get_schema"
}
```

On SQLite, `schema` maps each table to its `CREATE TABLE` statement. On
PostgreSQL, `engine` is `postgresql + asyncpg + pgvector` and `schema` maps
each table to a comma-separated list of `column type` pairs.

## hygiene_report

List stale, unlinked memories. A memory is listed when it has not been
updated for more than `stale_days` days and no other memory links to it.
The most idle memories come first.

Minimum role: viewer.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project` | string | no | `global` | Matches only this project. `global` is not a wildcard here. |
| `stale_days` | integer | no | 30 | Negative values become 0 |

Errors: `'stale_days' must be an integer`.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "hygiene_report", "project": "myapp", "stale_days": 30}'
```

```json
{
  "project": "myapp",
  "stale_days": 30,
  "orphan_count": 1,
  "memories": [
    {
      "id": "84ca0abc-990a-4389-b238-9777d5701ce5",
      "title": "Refresh token rotation",
      "memory_type": "conversation",
      "project": "myapp",
      "days_idle": 45,
      "access_count": 0,
      "backlink_count": 0,
      "verdict": "review"
    }
  ],
  "_use_command": "hygiene_report"
}
```

`verdict` is `archive` when `days_idle` is over 90, and `review` otherwise.

## version

Return the running server version. Takes no fields. There is no MCP tool for
this command.

Minimum role: viewer.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "version"}'
```

```json
{
  "version": "1.1.0",
  "server": "recall",
  "_use_command": "version"
}
```

The server also looks up the newest release tag on GitHub, at most once a day.
When that lookup succeeds the response adds `latest_version`.

## recall_help

Return the built-in command list. Takes no fields.

Minimum role: viewer.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "recall_help"}'
```

```json
{
  "commands": [
    {
      "command": "search",
      "aliases": ["find", "query", "recall", "lookup", "search_memory", "find_memory", "retrieve", "remember"],
      "description": "Search memories using hybrid semantic + keyword search.",
      "required": ["query"],
      "optional": ["project", "limit", "max_tokens"]
    }
  ],
  "count": 17,
  "tip": "All commands are sent as POST to /webhook/recall with Authorization: Bearer <token>",
  "_use_command": "recall_help"
}
```

The built-in list is a quick summary. It leaves out `debug_protocol` and some
optional fields. This page is the full reference.

## debug_protocol

Return backend details for troubleshooting. Takes no fields. There is no MCP
tool for this command.

Minimum role: admin.

```bash
curl -s -X POST "$RECALL_URL/webhook/recall" \
  -H "Authorization: Bearer $RECALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "debug_protocol"}'
```

```json
{
  "backend": "sqlite",
  "db_path": "./recall.db",
  "memory_count": 5,
  "embedding_key_set": false,
  "version": "1.1.0",
  "_use_command": "debug_protocol"
}
```

`memory_count` counts every memory in every project. `db_path` is `null` on
PostgreSQL. `embedding_key_set` says whether `RECALL_EMBEDDING_API_KEY` is set.
