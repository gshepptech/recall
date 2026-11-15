# Setting up Recall

This guide covers running the server, adding people, and connecting Claude Code.

## 1. Run the server

On the machine that will host Recall (it needs Docker with Compose v2):

```bash
git clone https://github.com/gshepptech/recall && cd recall
./install.sh
```

`install.sh` writes a `.env` with a random owner token and database password, builds
the image, starts PostgreSQL and Recall, waits for `/health`, and prints the owner
token. Keep that token private: it is the only one that can mint other tokens.

Other `install.sh` commands:

| Command | What it does |
|---|---|
| `./install.sh embedder` | Starts a local Ollama container, pulls `nomic-embed-text` (about 274 MB, CPU only), resizes the vector column to 768 dimensions and turns on semantic search. Memories saved before this have no vectors until they are saved again. |
| `./install.sh add-user <name> [role]` | Mints a token for a teammate. The role defaults to `developer`. |
| `./install.sh down` | Stops the stack. Data stays in the `postgres_data` volume. |

Teammates need to reach the server over the network. A private network such as
Tailscale or a VPN is the simplest choice. If you expose it publicly, put TLS in front
of it, for example with a Cloudflare tunnel (`cloudflared tunnel --url http://localhost:8000`).

To run without Docker on one machine, see Development in the [README](../README.md).
That setup uses SQLite.

## 2. Add a teammate

```bash
./install.sh add-user alice developer
```

Send Alice the token and the server URL over a private channel.

### Roles

| Role | Can do |
|---|---|
| owner | Everything, including minting tokens. Only the `RECALL_TOKEN` in `.env` has this role. |
| admin | Everything except minting tokens. Adds `delete_memory`, `get_schema` and `debug_protocol`. |
| developer | Read, plus save memories, prompts and requirements, promote requirements, and log runs and errors. |
| viewer | Read only: search, get memories and prompts, list prompts and requirements, hygiene report. |

A token can also be limited to one project with `project_scope` (see
[commands.md](commands.md#create_token)). A scoped token cannot read or write any
other project.

## 3. Connect Claude Code

Each person does this once.

**a. Save the credentials in a terminal.** The token prompt does not echo, so the token
stays out of your screen, your shell history and any chat:

```bash
read -rp 'Recall URL (http://host:8000): ' U; read -rsp 'Recall token: ' T; echo; \
mkdir -p ~/.recall; printf 'RECALL_URL=%s\nRECALL_TOKEN=%s\n' "$U" "$T" > ~/.recall/token; \
chmod 600 ~/.recall/token; unset T
```

Use the base URL, without `/mcp` or `/webhook/recall`.

**b. Install the plugin and register the server, inside Claude Code:**

```
/plugin marketplace add gshepptech/recall
/plugin install recall@recall
/recall:connect
```

`/recall:connect` reads `~/.recall/token` and runs `claude mcp add` at user scope,
passing the token by variable so its value never appears in the conversation.

**c. Restart Claude Code.** From the next session, the `recall_*` tools are available and
a short memory brief loads at the start of each session.

To update the plugin later, run `/plugin marketplace update recall` and then
`/plugin install recall@recall`.

## 4. Use it

Talk to Claude normally. It calls the Recall tools on its own:

- "What is our auth pattern?"
- "Remember that we deploy on Tuesdays."
- "What did we decide about the database layer?"

Two commands fill memory from the code itself:

| Command | What it does | When |
|---|---|---|
| `/recall:scour .` | Reads the repo in depth and saves facts with `file:line` evidence, after a skeptic pass and your answers to any open questions | Once per repo, then occasionally |
| `/recall:track` | Installs `post-commit` and `post-merge` hooks that run an incremental scour on each change | Once per repo |

The hooks run in the background through `claude -p`, never block a commit, and log to
`~/.recall/incremental.log`. They chain onto existing hooks and respect
`core.hooksPath`.

## How memory is organized

| Scope | Holds | Example |
|---|---|---|
| `global` | Conventions that hold across every repo | "We write tests first." |
| a project (the repo's directory name) | Facts about one codebase | "auth issues a 15-minute JWT" |

The session brief pulls from both: the current repo's project and `global`.

Memories have a type:

| Type | For |
|---|---|
| `note` | Conventions and how code is written here |
| `decision` | A choice the team made, and why |
| `requirement` | How a feature must work |
| `prompt` | A reusable, named instruction or style rule |
| `error` | A failure and its fix |
| `conversation` | Session summaries |

## Web UI

Open the server URL in a browser and sign in with a token to browse memories, the
wikilink graph, prompts, requirements, runs and token usage.

## Troubleshooting

| Symptom | Check |
|---|---|
| Claude cannot reach `recall` | Open `<RECALL_URL>/health` from your machine. Re-run `/recall:connect`, then restart Claude Code. |
| Slash commands are missing | Run `/reload-plugins`, then restart Claude Code. |
| No memory brief at session start | Check that `~/.recall/token` exists and holds the base URL. The brief stays silent when the server is unreachable or the repo has no facts yet. |
| Commits do not update memory | Read `~/.recall/incremental.log`. The hooks need `claude` on `PATH` and the `recall` MCP server registered at user scope. |
| `403 token_scope_mismatch` | The token is limited to one project. Send that project name in the request. |
| Semantic search shows `degraded` | No embedder is configured, or it failed. Run `./install.sh embedder` or set the `RECALL_EMBEDDING_*` keys. |
