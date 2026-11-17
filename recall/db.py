import logging
import sqlite3
import sqlite_vec
import sys
import threading
import json
import os
from typing import Optional
from recall.db_common import new_id
from recall.db_sqlite_search import save_memory_sqlite, search_memories

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

logger = logging.getLogger(__name__)

# ── Backend state ──────────────────────────────────────────────────────────────
# _db / _lock: kept for auth.py which does a synchronous token lookup via
#              get_db_and_lock().  Do NOT use these in the async public API.
# _aio_db:     aiosqlite connection used by all async public functions so that
#              no blocking sqlite3 call stalls the event loop.

_db: Optional[sqlite3.Connection] = None
_lock = threading.Lock()
_aio_db: Optional['aiosqlite.Connection'] = None
_is_pg: bool = False


def is_postgres() -> bool:
    return _is_pg


def set_aio_db(conn: 'aiosqlite.Connection') -> None:
    """Called once from server.py lifespan after opening the aiosqlite connection."""
    global _aio_db
    _aio_db = conn


# ── SQLite internals (sync, for init_db / auth only) ─────────────────────────

def _make_connection(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    try:
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
    except sqlite3.OperationalError as e:
        print(
            "\nERROR: Could not load the sqlite-vec extension.\n"
            "Your Python installation does not support SQLite extension loading.\n"
            "Fix: install Python from python.org or use 'brew install python' on macOS.\n"
            f"Detail: {e}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return db


def init_db() -> tuple:
    """Initialise the active backend.

    SQLite (default):  opens sync db, runs migrations, returns (db, lock).
    Postgres:          sets the _is_pg flag; actual async pool init is
                       done by server.py startup via db_postgres.init_pg().
                       Returns (None, None).

    Safe to call multiple times; skips setup if already initialised.
    """
    global _db, _is_pg
    backend = os.getenv('RECALL_DB_BACKEND', 'sqlite').lower()

    if backend == 'postgres':
        _is_pg = True
        return None, None

    if _db is not None:   # already initialised (e.g. by __main__.py before uvicorn)
        return _db, _lock

    from recall.migrate import run_migrations
    path = os.getenv('RECALL_DB_PATH', './recall.db')
    _db = _make_connection(path)
    run_migrations(_db)
    return _db, _lock


def get_db_and_lock() -> tuple:
    """Return the raw SQLite (db, lock), used by auth.py for sync token lookup."""
    return _db, _lock


# ── aiosqlite helpers ──────────────────────────────────────────────────────────

async def open_aio_db(path: str) -> 'aiosqlite.Connection':
    """Open an aiosqlite connection with WAL, foreign keys, and sqlite-vec loaded."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.enable_load_extension(True)
    await db.load_extension(sqlite_vec.loadable_path())
    await db.enable_load_extension(False)
    return db


# ── Async public API: dispatches to SQLite or Postgres ───────────────────────
#
# Commands call these functions; they work transparently with both backends.
# SQLite path uses _aio_db (aiosqlite): no blocking, no threading.

async def store_memory(data: dict, embedding: list) -> str:
    """Upsert a memory and its embedding."""
    if _is_pg:
        from recall.db_postgres import get_pg_pool
        from recall.db_postgres_search import save_memory_pg
        return await save_memory_pg(get_pg_pool(), data, embedding)
    return await save_memory_sqlite(_aio_db, data, embedding)


async def find_memories(query_text: str, query_embedding: list,
                        project: str, limit: int, memory_type: str = None) -> tuple:
    """Hybrid vector + FTS search. Returns (results, degraded, reason)."""
    if _is_pg:
        from recall.db_postgres import get_pg_pool
        from recall.db_postgres_search import search_memories_pg
        return await search_memories_pg(get_pg_pool(), query_text, query_embedding, project, limit,
                                        memory_type=memory_type)
    return await search_memories(_aio_db, query_text, query_embedding, project, limit,
                                 memory_type=memory_type)


async def fetch_memory(memory_id: str = None, title: str = None,
                       memory_type: str = None, project: str = None) -> Optional[dict]:
    """Fetch a single memory by id or title, scoped to project when provided."""
    if _is_pg:
        from recall.db_postgres import get_memory_pg, get_pg_pool
        return await get_memory_pg(get_pg_pool(), memory_id, title, memory_type, project)

    _COLS = ("id, title, content_md, memory_type, project, module, "
             "tags, resolution, access_count, created_at, updated_at")

    if memory_id:
        if project:
            sql = f"SELECT {_COLS} FROM memories WHERE id = ? AND project = ?"
            params = [memory_id, project]
        else:
            sql = f"SELECT {_COLS} FROM memories WHERE id = ?"
            params = [memory_id]
    elif memory_type:
        if project:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? AND memory_type = ? AND project = ?"
            params = [title, memory_type, project]
        else:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? AND memory_type = ?"
            params = [title, memory_type]
    else:
        if project:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? AND project = ? LIMIT 1"
            params = [title, project]
        else:
            sql = f"SELECT {_COLS} FROM memories WHERE title = ? LIMIT 1"
            params = [title]

    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_memory_links(memory_id: str) -> dict:
    """Return {links_out, links_in} for a memory. Each list item is
    {id, title, memory_type}. Missing memory → empty lists."""
    if not memory_id:
        return {'links_out': [], 'links_in': []}
    if _is_pg:
        from recall.db_postgres import fetch_memory_links_pg, get_pg_pool
        return await fetch_memory_links_pg(get_pg_pool(), memory_id)

    async with _aio_db.execute(
        """SELECT m.id, m.title, m.memory_type
           FROM memory_links l JOIN memories m ON m.id = l.to_id
           WHERE l.from_id = ? ORDER BY m.title""",
        [memory_id],
    ) as cur:
        out_rows = await cur.fetchall()
    async with _aio_db.execute(
        """SELECT m.id, m.title, m.memory_type
           FROM memory_links l JOIN memories m ON m.id = l.from_id
           WHERE l.to_id = ? ORDER BY m.title""",
        [memory_id],
    ) as cur:
        in_rows = await cur.fetchall()
    return {
        'links_out': [dict(r) for r in out_rows],
        'links_in':  [dict(r) for r in in_rows],
    }


async def hygiene_report(project: str, stale_days: int) -> list:
    """Return memories idle for more than stale_days AND with zero incoming
    wikilinks. Each row has {id, title, memory_type, project, days_idle,
    access_count, backlink_count}. Sorted most-idle-first.
    """
    if _is_pg:
        from recall.db_postgres import hygiene_report_pg, get_pg_pool
        return await hygiene_report_pg(get_pg_pool(), project, stale_days)

    async with _aio_db.execute(
        """
        SELECT
            m.id,
            m.title,
            m.memory_type,
            m.project,
            m.access_count,
            CAST(
                (julianday('now') -
                 julianday(COALESCE(m.updated_at, m.created_at))
                ) AS INTEGER
            ) AS days_idle,
            (SELECT COUNT(*) FROM memory_links l WHERE l.to_id = m.id) AS backlink_count
        FROM memories m
        WHERE m.project = ?
          AND (julianday('now') -
               julianday(COALESCE(m.updated_at, m.created_at))) > ?
          AND (SELECT COUNT(*) FROM memory_links l WHERE l.to_id = m.id) = 0
        ORDER BY days_idle DESC
        """,
        [project, stale_days],
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def fetch_links_between(memory_ids: list) -> list:
    """Return memory_links rows where both endpoints are in memory_ids.

    Used by the graph builder so wikilink edges can be rendered alongside the
    scored semantic edges. Each row is {from_id, to_id, anchor}.
    """
    if not memory_ids:
        return []
    if _is_pg:
        from recall.db_postgres import fetch_links_between_pg, get_pg_pool
        return await fetch_links_between_pg(get_pg_pool(), memory_ids)

    placeholders = ','.join('?' * len(memory_ids))
    sql = (
        f"SELECT from_id, to_id, anchor FROM memory_links "
        f"WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})"
    )
    async with _aio_db.execute(sql, list(memory_ids) + list(memory_ids)) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def record_run(data: dict, run_id: str) -> None:
    """Insert a prompt_run record."""
    if _is_pg:
        from recall.db_postgres import log_run_pg, get_pg_pool
        await log_run_pg(get_pg_pool(), data, run_id)
        return

    await _aio_db.execute(
        """INSERT INTO prompt_runs
           (id, project, runner, prompt_id, prompt_name, status, output_summary,
            tokens_input, tokens_output, tokens_cache_read, tokens_cache_creation, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            run_id,
            data.get('project', 'global'),
            data.get('runner'),
            data.get('prompt_id'),
            data.get('prompt_name'),
            data.get('status', 'success'),
            data.get('output_summary'),
            data.get('tokens_input'),
            data.get('tokens_output'),
            data.get('tokens_cache_read'),
            data.get('tokens_cache_creation'),
            data.get('cost_usd'),
        ]
    )
    await _aio_db.commit()


async def record_pending_run(runner: str, prompt_id: str, project: str) -> None:
    """Record that `runner` just fetched `prompt_id`. UPSERT; last write wins."""
    if _is_pg:
        from recall.db_postgres import record_pending_run_pg, get_pg_pool
        await record_pending_run_pg(get_pg_pool(), runner, prompt_id, project)
        return
    await _aio_db.execute("""
        INSERT INTO pending_runs (runner, project, prompt_id) VALUES (?, ?, ?)
        ON CONFLICT(runner, project) DO UPDATE SET
            prompt_id = excluded.prompt_id,
            created_at = datetime('now')
    """, [runner, project, prompt_id])
    await _aio_db.commit()


async def consume_pending_run(runner: str, project: str) -> Optional[str]:
    """Atomically read-and-delete the pending prompt_id for this (runner, project).
    Returns the prompt_id string or None if no pending handshake exists."""
    if _is_pg:
        from recall.db_postgres import consume_pending_run_pg, get_pg_pool
        return await consume_pending_run_pg(get_pg_pool(), runner, project)
    async with _aio_db.execute(
        "SELECT prompt_id FROM pending_runs WHERE runner = ? AND project = ?",
        [runner, project]
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    await _aio_db.execute(
        "DELETE FROM pending_runs WHERE runner = ? AND project = ?",
        [runner, project]
    )
    await _aio_db.commit()
    return row['prompt_id']


async def list_runs(project: str = 'global', prompt_id: str = None,
                    prompt_name: str = None, limit: int = 100) -> list:
    """List prompt_runs rows joined with prompt title from memories."""
    if _is_pg:
        from recall.db_postgres import list_runs_pg, get_pg_pool
        return await list_runs_pg(get_pg_pool(), project, prompt_id, prompt_name, limit)

    where = []
    params: list = []
    if project and project != 'global':
        where.append('r.project = ?'); params.append(project)
    if prompt_id:
        where.append('r.prompt_id = ?'); params.append(prompt_id)
    if prompt_name:
        where.append('r.prompt_name = ?'); params.append(prompt_name)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    params.append(limit)
    sql = f"""
        SELECT r.id, r.project, r.runner, r.prompt_id, r.prompt_name,
               r.status, r.output_summary,
               r.tokens_input, r.tokens_output,
               r.tokens_cache_read, r.tokens_cache_creation,
               r.cost_usd, r.created_at,
               m.title AS prompt_title
        FROM prompt_runs r
        LEFT JOIN memories m ON m.id = r.prompt_id
        {where_sql}
        ORDER BY r.created_at DESC
        LIMIT ?
    """
    async with _aio_db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def run_stats(project: str = 'global', prompt_id: str = None,
                    prompt_name: str = None) -> dict:
    """Aggregate token usage across prompt_runs (filterable)."""
    if _is_pg:
        from recall.db_postgres import run_stats_pg, get_pg_pool
        return await run_stats_pg(get_pg_pool(), project, prompt_id, prompt_name)

    where = []
    params: list = []
    if project and project != 'global':
        where.append('project = ?'); params.append(project)
    if prompt_id:
        where.append('prompt_id = ?'); params.append(prompt_id)
    if prompt_name:
        where.append('prompt_name = ?'); params.append(prompt_name)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    sql = f"""
        SELECT COUNT(*) AS run_count,
               COALESCE(SUM(tokens_input),0)          AS sum_in,
               COALESCE(SUM(tokens_output),0)         AS sum_out,
               COALESCE(SUM(tokens_cache_read),0)     AS sum_cache_read,
               COALESCE(SUM(tokens_cache_creation),0) AS sum_cache_creation,
               COALESCE(AVG(tokens_input),0)          AS avg_in,
               COALESCE(AVG(tokens_output),0)         AS avg_out,
               COALESCE(AVG(tokens_cache_read),0)     AS avg_cache_read
        FROM prompt_runs
        {where_sql}
    """
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else {}


async def record_error(data: dict, error_id: str) -> None:
    """Insert an error_log record."""
    if _is_pg:
        from recall.db_postgres import log_error_pg, get_pg_pool
        await log_error_pg(get_pg_pool(), data, error_id)
        return

    await _aio_db.execute(
        """INSERT INTO error_log
           (id, project, runner, error_type, message, stack_trace, context_md)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            error_id,
            data.get('project', 'global'),
            data.get('runner'),
            data.get('error_type'),
            data.get('message') or data.get('error', ''),
            data.get('stack_trace'),
            data.get('context_md'),
        ]
    )
    await _aio_db.commit()


async def get_schema_info() -> dict:
    """Return schema info for the active backend."""
    if _is_pg:
        from recall.db_postgres import get_schema_pg, get_pg_pool
        return await get_schema_pg(get_pg_pool())

    async with _aio_db.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ) as cur:
        tables = await cur.fetchall()
    schema = {t['name']: t['sql'] for t in tables if t['sql']}
    return {
        'engine': 'sqlite3 + sqlite-vec (aiosqlite)',
        'tables': list(schema.keys()),
        'schema': schema,
    }


async def fetch_prompt_row(prompt_name: str, project: str = None) -> Optional[dict]:
    """Fetch a prompt memory by title, scoped to project when provided."""
    if _is_pg:
        from recall.db_postgres import get_prompt_pg, get_pg_pool
        return await get_prompt_pg(get_pg_pool(), prompt_name, project)

    if project:
        sql = ("SELECT id, title, content_md, project, access_count, created_at "
               "FROM memories WHERE title = ? AND memory_type = 'prompt' AND project = ?")
        params = [prompt_name, project]
    else:
        sql = ("SELECT id, title, content_md, project, access_count, created_at "
               "FROM memories WHERE title = ? AND memory_type = 'prompt'")
        params = [prompt_name]

    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_memory(memory_id: str, project: str = None) -> Optional[dict]:
    """Delete a memory by UUID, scoped to project when provided.
    Returns {id, title, ...} on success, None if not found."""
    if _is_pg:
        from recall.db_postgres import delete_memory_pg, get_pg_pool
        return await delete_memory_pg(get_pg_pool(), memory_id, project)

    sql = "SELECT rowid, id, title, memory_type, project FROM memories WHERE id = ?"
    params = [memory_id]
    if project:
        sql += " AND project = ?"
        params.append(project)
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    rowid = row['rowid']
    await _aio_db.execute("DELETE FROM memories WHERE id = ?", [memory_id])
    await _aio_db.execute("DELETE FROM memories_vec WHERE rowid = ?", [rowid])
    await _aio_db.execute("DELETE FROM memories_fts WHERE rowid = ?", [rowid])
    await _aio_db.commit()
    return {
        'id': row['id'],
        'title': row['title'],
        'memory_type': row['memory_type'],
        'project': row['project'],
    }


async def bump_access_count(memory_id: str) -> None:
    """Increment access_count for a memory."""
    if _is_pg:
        from recall.db_postgres import bump_access_count_pg, get_pg_pool
        await bump_access_count_pg(get_pg_pool(), memory_id)
        return

    await _aio_db.execute(
        "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
        [memory_id]
    )
    await _aio_db.commit()


async def add_token(token_id: str, token: str, person_name: str, role: str,
                    project_scope: str = None) -> None:
    """Insert a new access token."""
    if _is_pg:
        from recall.db_postgres import add_token_pg, get_pg_pool
        await add_token_pg(get_pg_pool(), token_id, token, person_name, role, project_scope)
        return

    await _aio_db.execute(
        "INSERT INTO access_tokens (id, token, person_name, role, active, project_scope) VALUES (?, ?, ?, ?, 1, ?)",
        [token_id, token, person_name, role, project_scope]
    )
    await _aio_db.commit()


async def log_token_hit(label: str, command: str) -> None:
    if _is_pg:
        from recall.db_postgres import log_token_hit_pg, get_pg_pool
        await log_token_hit_pg(get_pg_pool(), label, command)
        return
    await _aio_db.execute(
        "INSERT INTO token_hits (id, label, command) VALUES (?, ?, ?)",
        [new_id(), label, command]
    )
    await _aio_db.commit()


async def token_usage_stats() -> list:
    if _is_pg:
        from recall.db_postgres import token_usage_stats_pg, get_pg_pool
        return await token_usage_stats_pg(get_pg_pool())
    async with _aio_db.execute("""
        SELECT label,
               COUNT(*)                                              AS hits_total,
               COUNT(CASE WHEN ts > datetime('now','-7 days') THEN 1 END) AS hits_7d,
               COUNT(CASE WHEN ts > datetime('now','-1 day')  THEN 1 END) AS hits_24h,
               MAX(ts)                                               AS last_seen
        FROM token_hits
        GROUP BY label
        ORDER BY hits_total DESC
    """) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def list_token_labels() -> list:
    """Return person_name for all active non-owner tokens, ordered by creation."""
    if _is_pg:
        from recall.db_postgres import list_token_labels_pg, get_pg_pool
        return await list_token_labels_pg(get_pg_pool())

    async with _aio_db.execute(
        "SELECT person_name FROM access_tokens WHERE active = 1 AND role != 'owner' ORDER BY created_at"
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows if r[0]]


async def list_by_memory_type(memory_type: str, project: str, limit: int,
                              status: str = None) -> list:
    """List memories of one type. status 'pending' or 'resolved' filters on
    pending_review; any other value returns both."""
    if _is_pg:
        from recall.db_postgres import list_by_type_pg, get_pg_pool
        return await list_by_type_pg(get_pg_pool(), memory_type, project, limit, status)

    pending_review = {'pending': 1, 'resolved': 0}.get(status)

    # global → sees ALL memories; specific project → scoped to that project only
    if pending_review is not None:
        if project == 'global':
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                  AND pending_review = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, pending_review, limit]
        else:
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                  AND project = ?
                  AND pending_review = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, project, pending_review, limit]
    else:
        if project == 'global':
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, limit]
        else:
            sql = """
                SELECT id, title, SUBSTR(content_md, 1, 300) AS snippet,
                       project, access_count, created_by, created_at
                FROM memories
                WHERE memory_type = ?
                  AND project = ?
                ORDER BY access_count DESC, created_at DESC
                LIMIT ?
            """
            params = [memory_type, project, limit]

    async with _aio_db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def change_memory_type(memory_id: str, new_type: str,
                             project: str = None) -> Optional[dict]:
    """Promote a requirement to a different memory_type, scoped to project when provided.
    Returns the row or None."""
    if _is_pg:
        from recall.db_postgres import change_memory_type_pg, get_pg_pool
        return await change_memory_type_pg(get_pg_pool(), memory_id, new_type, project)

    sql = "SELECT id, title FROM memories WHERE id = ? AND memory_type = 'requirement'"
    params = [memory_id]
    if project:
        sql += " AND project = ?"
        params.append(project)
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    await _aio_db.execute("""
        UPDATE memories
        SET memory_type = ?, pending_review = 0, updated_at = datetime('now')
        WHERE id = ?
    """, [new_type, memory_id])
    await _aio_db.commit()
    return dict(row) if row else None


async def list_projects() -> list[str]:
    """Return distinct project names."""
    if _is_pg:
        from recall.db_postgres import list_projects_pg, get_pg_pool
        return await list_projects_pg(get_pg_pool())

    async with _aio_db.execute("""
        SELECT DISTINCT project
        FROM memories
        WHERE project IS NOT NULL AND project != ''
        ORDER BY project
    """) as cur:
        rows = await cur.fetchall()
    return [r['project'] for r in rows]


async def list_all_memories(project: str = 'global', limit: int = 250) -> list[dict]:
    """Return a compact list of memories for UI views such as graph browsing."""
    if _is_pg:
        from recall.db_postgres import list_all_memories_pg, get_pg_pool
        return await list_all_memories_pg(get_pg_pool(), project, limit)

    if project == 'global':
        sql = """
            SELECT id, title, SUBSTR(content_md, 1, 280) AS snippet,
                   content_md, memory_type, project, module, tags,
                   access_count, created_by, pending_review, resolved, created_at
            FROM memories
            WHERE searchable = 1
            ORDER BY access_count DESC, created_at DESC
            LIMIT ?
        """
        params = [limit]
    else:
        sql = """
            SELECT id, title, SUBSTR(content_md, 1, 280) AS snippet,
                   content_md, memory_type, project, module, tags,
                   access_count, created_by, pending_review, resolved, created_at
            FROM memories
            WHERE searchable = 1
              AND project = ?
            ORDER BY access_count DESC, created_at DESC
            LIMIT ?
        """
        params = [project, limit]

    async with _aio_db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    out = []
    for row in rows:
        item = dict(row)
        try:
            item['tags'] = json.loads(item.get('tags') or '[]')
        except (TypeError, json.JSONDecodeError):
            item['tags'] = []
        out.append(item)
    return out


async def count_memories_by_project(project: str) -> int:
    """Return memory count scoped by project. 'global' sees all."""
    if _is_pg:
        from recall.db_postgres import count_memories_pg, get_pg_pool
        return await count_memories_pg(get_pg_pool(), project)
    if project == 'global':
        sql = "SELECT COUNT(*) FROM memories WHERE searchable = 1"
        params = ()
    else:
        sql = "SELECT COUNT(*) FROM memories WHERE searchable = 1 AND project = ?"
        params = (project,)
    async with _aio_db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def debug_memory_count() -> int:
    """Return total count of memories (for debug_protocol)."""
    if _is_pg:
        from recall.db_postgres import debug_count_pg, get_pg_pool
        return await debug_count_pg(get_pg_pool())

    async with _aio_db.execute('SELECT COUNT(*) FROM memories') as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
