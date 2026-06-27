#!/usr/bin/env bash
# Recall one-command installer.
#   ./install.sh                       bring the whole stack up (generates .env if missing)
#   ./install.sh embedder              also start local Ollama + pull the model (semantic, zero-egress)
#   ./install.sh add-user <name> [role]   mint a token and print the teammate's connect command
#   ./install.sh down                  stop the stack
set -euo pipefail
cd "$(dirname "$0")"

URL_LOCAL="http://localhost:8000"
RAND() { python3 -c "import secrets;print(secrets.token_hex(16))"; }

need_docker() {
  command -v docker >/dev/null 2>&1 || { echo "✗ Docker is required. Install Docker, then re-run."; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "✗ 'docker compose' v2 is required."; exit 1; }
}

ensure_env() {
  if [[ -f .env ]]; then echo "• using existing .env"; return; fi
  echo "• generating .env (random secrets)"
  cat > .env <<EOF
RECALL_TOKEN=$(RAND)
POSTGRES_USER=recall
POSTGRES_PASSWORD=$(RAND)
POSTGRES_DB=recall
DB_BACKEND=postgres
RECALL_PROJECT=global
# semantic search off by default (keyword-only, zero egress). Enable with: ./install.sh embedder
RECALL_EMBED_DIM=1536
EOF
}

wait_health() {
  echo -n "• waiting for Recall to come up"
  for _ in $(seq 1 60); do
    if curl -fsS "$URL_LOCAL/health" >/dev/null 2>&1; then echo " — up ✓"; return 0; fi
    echo -n "."; sleep 2
  done
  echo; echo "✗ server did not become healthy — check: docker compose logs recall"; exit 1
}

token() { grep '^RECALL_TOKEN=' .env | cut -d= -f2-; }

print_done() {
  echo
  echo "════════════════════════════════════════════════════════════"
  echo " Recall is running at $URL_LOCAL"
  echo " Owner token:  $(token)"
  echo
  echo " Add a teammate:   ./install.sh add-user alice developer"
  echo " Expose to team:   cloudflared tunnel --url $URL_LOCAL"
  echo "════════════════════════════════════════════════════════════"
}

cmd="${1:-up}"
case "$cmd" in
  up)
    need_docker; ensure_env
    echo "• building + starting (postgres + recall)…"
    docker compose up -d --build
    wait_health; print_done
    ;;
  embedder)
    need_docker
    echo "• starting Ollama + pulling nomic-embed-text (CPU, ~274MB)…"
    docker compose --profile embedder up -d ollama
    docker exec recall_ollama ollama pull nomic-embed-text
    # enable semantic in .env (idempotent) and restart the server
    grep -q '^OPENAI_API_BASE=' .env || cat >> .env <<EOF
OPENAI_API_BASE=http://ollama:11434/v1
OPENAI_API_KEY=local
RECALL_EMBEDDING_MODEL=nomic-embed-text
EOF
    sed -i.bak 's/^RECALL_EMBED_DIM=.*/RECALL_EMBED_DIM=768/' .env && rm -f .env.bak
    docker compose up -d
    echo "✓ semantic search enabled (local, zero egress)."
    ;;
  add-user)
    name="${2:?usage: ./install.sh add-user <name> [role]}"; role="${3:-developer}"
    resp=$(curl -fsS -X POST "$URL_LOCAL/webhook/recall" \
      -H "Authorization: Bearer $(token)" -H "Content-Type: application/json" \
      -d "{\"command\":\"create_token\",\"token_name\":\"$name\",\"role\":\"$role\"}")
    tok=$(printf '%s' "$resp" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('token',''))" 2>/dev/null)
    [[ -z "$tok" ]] && { echo "✗ could not mint token. Response: $resp"; exit 1; }
    echo "✓ token for '$name' ($role): $tok"
    echo
    echo "  Send them this (swap in your public URL if tunneled):"
    echo "  claude mcp add --transport http recall $URL_LOCAL/mcp --header \"Authorization: Bearer $tok\""
    ;;
  down) docker compose --profile embedder down; echo "✓ stopped." ;;
  *) echo "usage: ./install.sh [up|embedder|add-user <name> [role]|down]"; exit 1 ;;
esac
