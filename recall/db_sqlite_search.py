"""SQLite memory writes and hybrid search: the memories row, its FTS and vector rows, and wikilink edges."""
import json
import logging
import re
import struct
from typing import TYPE_CHECKING

from recall.config import VECTOR_SEARCH_K
from recall.db_common import extract_wikilinks, new_id

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


async def _store_wikilinks_sqlite(db: 'aiosqlite.Connection', from_id: str,
                                  content_md: str, project: str) -> None:
    """Replace from_id's rows in memory_links with edges parsed from content_md."""
    await db.execute("DELETE FROM memory_links WHERE from_id = ?", [from_id])
    anchors = extract_wikilinks(content_md)
    if not anchors:
        return
    for anchor in anchors:
        async with db.execute(
            """SELECT id FROM memories
               WHERE title = ? AND (project = ? OR project = 'global')
               ORDER BY (project = ?) DESC LIMIT 1""",
            [anchor, project, project],
        ) as cur:
            row = await cur.fetchone()
        if not row:
            continue
        await db.execute(
            """INSERT OR IGNORE INTO memory_links(from_id, to_id, anchor)
               VALUES (?, ?, ?)""",
            [from_id, row['id'], anchor],
        )


async def save_memory_sqlite(db: 'aiosqlite.Connection', data: dict, embedding: list) -> str:
    from recall.scoring import clamp_confidence
    memory_id = new_id()
    vec_bytes = struct.pack(f'{len(embedding)}f', *embedding)

    conf = clamp_confidence(data.get('confidence_score', data.get('confidence')))
    await db.execute("""
        INSERT INTO memories
            (id, project, module, memory_type, title, content_md,
             tags, resolution, created_by, searchable, pending_review, confidence_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, COALESCE(?, 1.0))
        ON CONFLICT(title, memory_type, project) DO UPDATE SET
            content_md = excluded.content_md,
            tags = excluded.tags,
            pending_review = excluded.pending_review,
            confidence_score = COALESCE(?, memories.confidence_score),
            updated_at = CURRENT_TIMESTAMP
    """, [
        memory_id,
        data.get('project', 'global'),
        data.get('module'),
        data.get('memory_type', 'conversation'),
        data.get('title', ''),
        data.get('content_md') or data.get('content', ''),
        json.dumps(data.get('tags', [])),
        data.get('resolution'),
        data.get('created_by'),
        data.get('pending_review', 0),
        conf,
        conf,
    ])

    async with db.execute(
        "SELECT rowid FROM memories WHERE title=? AND memory_type=? AND project=?",
        [data.get('title', ''), data.get('memory_type', 'conversation'), data.get('project', 'global')]
    ) as cur:
        row = await cur.fetchone()

    if row:
        rowid = row['rowid']
        await db.execute("DELETE FROM memories_vec WHERE rowid = ?", [rowid])
        await db.execute(
            "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
            [rowid, vec_bytes]
        )
        await db.execute(
            "INSERT OR REPLACE INTO memories_fts(rowid, title, content_md) VALUES (?, ?, ?)",
            [rowid, data.get('title', ''), data.get('content_md') or data.get('content', '')]
        )

    async with db.execute(
        "SELECT id FROM memories WHERE title=? AND memory_type=? AND project=?",
        [data.get('title', ''), data.get('memory_type', 'conversation'), data.get('project', 'global')]
    ) as cur:
        row = await cur.fetchone()
    resolved_id = row['id'] if row else memory_id

    await _store_wikilinks_sqlite(
        db, resolved_id,
        data.get('content_md') or data.get('content', ''),
        data.get('project', 'global'),
    )

    await db.commit()
    return resolved_id


# ── SQLite async: search_memories ─────────────────────────────────────────────

async def _fts_query(db: 'aiosqlite.Connection', match_expr: str, project: str, limit: int,
                    memory_type: str = None):
    """Run a single FTS5 MATCH query. Returns rows or raises."""
    # global → sees ALL memories; specific project → scoped to that project only
    if project == 'global':
        base_sql = """
            SELECT
                m.rowid, m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at, f.rank AS fts_score,
                m.access_count, m.confidence_score
            FROM memories m
            JOIN memories_fts f ON f.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND m.searchable = 1
        """
        params = [match_expr]
    else:
        base_sql = """
            SELECT
                m.rowid, m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at, f.rank AS fts_score,
                m.access_count, m.confidence_score
            FROM memories m
            JOIN memories_fts f ON f.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND m.searchable = 1
              AND m.project = ?
        """
        params = [match_expr, project]
    if memory_type:
        base_sql += "  AND m.memory_type = ?\n"
        params.append(memory_type)
    base_sql += "ORDER BY f.rank\nLIMIT ?"
    params.append(limit)
    async with db.execute(base_sql, params) as cur:
        return await cur.fetchall()


async def _fts_search(db: 'aiosqlite.Connection', query_text: str, project: str, limit: int,
                     memory_type: str = None) -> tuple:
    """Full-text search fallback: AND → OR → LIKE.
    Returns (results, degraded, reason)."""
    rows = []
    degraded = False
    reason = ''

    # Level 1: FTS MATCH
    try:
        rows = await _fts_query(db, query_text, project, limit, memory_type=memory_type)
    except Exception as e:
        logger.warning(f'FTS MATCH failed: {e}')

    # Level 2: OR token MATCH
    if not rows:
        tokens = [t for t in re.sub(r'[^\w\s]', ' ', query_text).split() if t]
        if len(tokens) > 1:
            try:
                rows = await _fts_query(db, ' OR '.join(tokens), project, limit, memory_type=memory_type)
                if rows:
                    degraded = True
                    reason = 'fts_or_fallback'
            except Exception as e:
                logger.warning(f'FTS OR fallback failed: {e}')

    # Level 3: LIKE
    if not rows:
        try:
            # global → sees ALL memories; specific project → scoped to that project only
            if project == 'global':
                like_sql = """
                    SELECT
                        rowid, id, title,
                        SUBSTR(content_md, 1, 500) AS snippet,
                        memory_type, project, module, created_at,
                        -0.5 AS fts_score,
                        access_count, confidence_score
                    FROM memories
                    WHERE (title LIKE ? OR content_md LIKE ?)
                      AND searchable = 1
                """
                like_params = [f'%{query_text}%', f'%{query_text}%']
            else:
                like_sql = """
                    SELECT
                        rowid, id, title,
                        SUBSTR(content_md, 1, 500) AS snippet,
                        memory_type, project, module, created_at,
                        -0.5 AS fts_score,
                        access_count, confidence_score
                    FROM memories
                    WHERE (title LIKE ? OR content_md LIKE ?)
                      AND searchable = 1
                      AND project = ?
                """
                like_params = [f'%{query_text}%', f'%{query_text}%', project]
            if memory_type:
                like_sql += "  AND memory_type = ?\n"
                like_params.append(memory_type)
            like_sql += "LIMIT ?"
            like_params.append(limit)
            async with db.execute(like_sql, like_params) as cur:
                rows = await cur.fetchall()
            if rows:
                degraded = True
                reason = 'like_fallback'
        except Exception as e:
            logger.warning(f'LIKE fallback failed: {e}')
            return [], True, 'all_search_methods_failed'

    from recall.scoring import score as rescore
    results = []
    for row in rows:
        fts = abs(float(row['fts_score']))
        raw = round(min(fts, 1.0), 4)
        mem = {
            'created_at': row['created_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
        }
        results.append({
            'id': row['id'],
            'title': row['title'],
            'snippet': row['snippet'] or '',
            'memory_type': row['memory_type'],
            'project': row['project'],
            'module': row['module'],
            'score': round(rescore(raw, mem), 4),
            'relevance': raw,
            'created_at': row['created_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
        })
    return results, degraded, reason


async def search_memories(db: 'aiosqlite.Connection', query_text: str, query_embedding: list,
                          project: str, limit: int = 5, memory_type: str = None) -> tuple:
    """Returns (results, degraded, reason)."""
    is_zero = all(v == 0.0 for v in query_embedding)

    vec_results = []
    if not is_zero:
        try:
            vec_bytes = struct.pack(f'{len(query_embedding)}f', *query_embedding)
            async with db.execute("""
                SELECT rowid, distance
                FROM memories_vec
                WHERE embedding MATCH ?
                  AND k = ?
            """, [vec_bytes, VECTOR_SEARCH_K]) as cur:
                vec_results = await cur.fetchall()
        except Exception as e:
            logger.warning(f'Vector search failed, falling back to FTS: {e}')
            vec_results = []

    if not vec_results:
        return await _fts_search(db, query_text, project, limit, memory_type=memory_type)

    rowid_to_distance = {row['rowid']: row['distance'] for row in vec_results}
    rowids = list(rowid_to_distance.keys())
    placeholders = ','.join('?' * len(rowids))

    # global → sees ALL memories; specific project → scoped to that project only
    if project == 'global':
        vec_sql = f"""
            SELECT
                m.rowid,
                m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at,
                COALESCE(f.rank, 0.0) AS fts_score,
                m.access_count, m.confidence_score
            FROM memories m
            LEFT JOIN (
                SELECT rowid, rank
                FROM memories_fts
                WHERE memories_fts MATCH ?
            ) f ON f.rowid = m.rowid
            WHERE m.rowid IN ({placeholders})
              AND m.searchable = 1
        """
        vec_params = [query_text] + rowids
    else:
        vec_sql = f"""
            SELECT
                m.rowid,
                m.id, m.title,
                SUBSTR(m.content_md, 1, 500) AS snippet,
                m.memory_type, m.project, m.module,
                m.created_at,
                COALESCE(f.rank, 0.0) AS fts_score,
                m.access_count, m.confidence_score
            FROM memories m
            LEFT JOIN (
                SELECT rowid, rank
                FROM memories_fts
                WHERE memories_fts MATCH ?
            ) f ON f.rowid = m.rowid
            WHERE m.rowid IN ({placeholders})
              AND m.searchable = 1
              AND m.project = ?
        """
        vec_params = [query_text] + rowids + [project]
    if memory_type:
        vec_sql += "  AND m.memory_type = ?\n"
        vec_params.append(memory_type)
    async with db.execute(vec_sql, vec_params) as cur:
        rows = await cur.fetchall()

    from recall.scoring import score as rescore
    results = []
    for row in rows:
        distance = rowid_to_distance.get(row['rowid'], 1.0)
        cosine_sim = 1.0 - distance
        fts = abs(float(row['fts_score']))
        raw = round(0.7 * cosine_sim + 0.3 * min(fts, 1.0), 4)
        mem = {
            'created_at': row['created_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
        }
        results.append({
            'id': row['id'],
            'title': row['title'],
            'snippet': row['snippet'] or '',
            'memory_type': row['memory_type'],
            'project': row['project'],
            'module': row['module'],
            'score': round(rescore(raw, mem), 4),
            'relevance': raw,
            'created_at': row['created_at'],
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:limit], False, ''
