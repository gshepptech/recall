"""Postgres memory writes and hybrid search: the memories row with its embedding, and wikilink edges."""
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from recall.config import VECTOR_SEARCH_K
from recall.db_common import extract_wikilinks, new_id
from recall.db_postgres import _iso, _vec_str
from recall.scoring import clamp_confidence, score as rescore

logger = logging.getLogger(__name__)


async def _store_wikilinks_pg(conn, from_id: str, content_md: str, project: str) -> None:
    """Replace from_id's rows in memory_links with edges parsed from content_md."""
    await conn.execute("DELETE FROM memory_links WHERE from_id = $1", from_id)
    anchors = extract_wikilinks(content_md)
    if not anchors:
        return
    for anchor in anchors:
        row = await conn.fetchrow(
            """SELECT id FROM memories
               WHERE title = $1 AND (project = $2 OR project = 'global')
               ORDER BY (project = $2) DESC LIMIT 1""",
            anchor, project,
        )
        if not row:
            continue
        await conn.execute(
            """INSERT INTO memory_links(from_id, to_id, anchor)
               VALUES ($1, $2, $3)
               ON CONFLICT DO NOTHING""",
            from_id, row['id'], anchor,
        )


async def save_memory_pg(pool: 'asyncpg.Pool', data: dict, embedding: list) -> str:
    memory_id = new_id()
    vec = _vec_str(embedding)
    conf = clamp_confidence(data.get('confidence_score', data.get('confidence')))

    async with pool.acquire() as conn:
        pending_review = data.get('pending_review', 0)
        if vec is not None:
            row = await conn.fetchrow("""
                INSERT INTO memories
                    (id, project, module, memory_type, title, content_md,
                     tags, resolution, created_by, searchable, pending_review, embedding, confidence_score)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,1,$10,$11::halfvec,COALESCE($12,1.0))
                ON CONFLICT (title, memory_type, project) DO UPDATE SET
                    content_md     = EXCLUDED.content_md,
                    tags           = EXCLUDED.tags,
                    embedding      = EXCLUDED.embedding,
                    pending_review = EXCLUDED.pending_review,
                    confidence_score = COALESCE($13, memories.confidence_score),
                    updated_at     = NOW()
                RETURNING id
            """,
                memory_id,
                data.get('project', 'global'),
                data.get('module'),
                data.get('memory_type', 'conversation'),
                data.get('title', ''),
                data.get('content_md') or data.get('content', ''),
                json.dumps(data.get('tags', [])),
                data.get('resolution'),
                data.get('created_by'),
                pending_review,
                vec,
                conf,
                conf,
            )
        else:
            row = await conn.fetchrow("""
                INSERT INTO memories
                    (id, project, module, memory_type, title, content_md,
                     tags, resolution, created_by, searchable, pending_review, confidence_score)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,1,$10,COALESCE($11,1.0))
                ON CONFLICT (title, memory_type, project) DO UPDATE SET
                    content_md     = EXCLUDED.content_md,
                    tags           = EXCLUDED.tags,
                    pending_review = EXCLUDED.pending_review,
                    confidence_score = COALESCE($12, memories.confidence_score),
                    updated_at     = NOW()
                RETURNING id
            """,
                memory_id,
                data.get('project', 'global'),
                data.get('module'),
                data.get('memory_type', 'conversation'),
                data.get('title', ''),
                data.get('content_md') or data.get('content', ''),
                json.dumps(data.get('tags', [])),
                data.get('resolution'),
                data.get('created_by'),
                pending_review,
                conf,
                conf,
            )

        resolved_id = row['id'] if row else memory_id
        await _store_wikilinks_pg(
            conn, resolved_id,
            data.get('content_md') or data.get('content', ''),
            data.get('project', 'global'),
        )

    return resolved_id


# ── search_memories ───────────────────────────────────────────────────────────

_TSQUERY_ALL = "plainto_tsquery('english', $1)"
# plainto_tsquery quotes each lexeme and joins them with &, so swapping the
# operator gives the same terms OR-ed together
_TSQUERY_ANY = "replace(plainto_tsquery('english', $1)::text, ' & ', ' | ')::tsquery"


async def _fts_query_pg(conn, tsquery: str, query_text: str, project_param, limit: int,
                        memory_type: str = None):
    """Run one tsvector match, ranked. Returns rows or raises."""
    sql = f"""
        SELECT id, title,
               SUBSTRING(content_md, 1, 500)  AS snippet,
               memory_type, project, module,
               created_at, access_count, confidence_score,
               ts_rank(to_tsvector('english', title || ' ' || content_md), {tsquery}) AS fts_score
        FROM memories
        WHERE to_tsvector('english', title || ' ' || content_md) @@ {tsquery}
          AND searchable = 1
          AND ($2::text IS NULL OR project = $2)
          AND ($4::text IS NULL OR memory_type = $4)
        ORDER BY fts_score DESC
        LIMIT $3
    """
    return await conn.fetch(sql, query_text, project_param, limit, memory_type)


async def _fts_search_pg(conn, query_text: str, project: str, limit: int,
                        memory_type: str = None) -> tuple:
    """tsvector FTS, AND then OR, then ILIKE. Returns (results, degraded, reason)."""
    # global → sees ALL memories; specific project → scoped to that project only
    project_param = None if project == 'global' else project
    rows = []
    degraded = False
    reason = ''

    # Level 1: every term must match
    try:
        rows = await _fts_query_pg(conn, _TSQUERY_ALL, query_text, project_param, limit, memory_type)
    except Exception as e:
        logger.warning(f'FTS MATCH failed: {e}')

    # Level 2: any term may match
    if not rows and len(query_text.split()) > 1:
        try:
            rows = await _fts_query_pg(conn, _TSQUERY_ANY, query_text, project_param, limit, memory_type)
            if rows:
                degraded = True
                reason = 'fts_or_fallback'
        except Exception as e:
            logger.warning(f'FTS OR fallback failed: {e}')

    # Level 3: ILIKE fallback
    if not rows:
        try:
            if memory_type:
                rows = await conn.fetch("""
                    SELECT id, title,
                           SUBSTRING(content_md, 1, 500) AS snippet,
                           memory_type, project, module,
                           created_at, access_count, confidence_score,
                           0.5::float AS fts_score
                    FROM memories
                    WHERE (title ILIKE $1 OR content_md ILIKE $1)
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                      AND memory_type = $4
                    LIMIT $3
                """, f'%{query_text}%', project_param, limit, memory_type)
            else:
                rows = await conn.fetch("""
                    SELECT id, title,
                           SUBSTRING(content_md, 1, 500) AS snippet,
                           memory_type, project, module,
                           created_at, access_count, confidence_score,
                           0.5::float AS fts_score
                    FROM memories
                    WHERE (title ILIKE $1 OR content_md ILIKE $1)
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                    LIMIT $3
                """, f'%{query_text}%', project_param, limit)
            if rows:
                degraded = True
                reason = 'like_fallback'
        except Exception as e:
            logger.warning(f'LIKE fallback failed: {e}')
            return [], True, 'all_search_methods_failed'

    results = []
    for row in rows:
        raw = round(min(float(row['fts_score']), 1.0), 4)
        created_str = _iso(row['created_at'])
        mem = {
            'created_at': created_str,
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
            'created_at': created_str,
            'access_count': row['access_count'],
            'confidence_score': row['confidence_score'],
        })
    return results, degraded, reason


async def search_memories_pg(pool: 'asyncpg.Pool', query_text: str,
                              query_embedding: list, project: str, limit: int,
                              memory_type: str = None) -> tuple:
    """Returns (results, degraded, reason)."""
    is_zero = not query_embedding or all(v == 0.0 for v in query_embedding)
    vec = None if is_zero else _vec_str(query_embedding)
    # global → sees ALL memories; specific project → scoped to that project only
    project_param = None if project == 'global' else project

    async with pool.acquire() as conn:
        if vec is None:
            return await _fts_search_pg(conn, query_text, project, limit, memory_type=memory_type)

        # Vector search: top K candidates
        try:
            if memory_type:
                vec_rows = await conn.fetch("""
                    SELECT id,
                           1.0 - (embedding <=> $1::halfvec) AS cosine_sim
                    FROM memories
                    WHERE embedding IS NOT NULL
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                      AND memory_type = $4
                    ORDER BY embedding <=> $1::halfvec
                    LIMIT $3
                """, vec, project_param, VECTOR_SEARCH_K, memory_type)
            else:
                vec_rows = await conn.fetch("""
                    SELECT id,
                           1.0 - (embedding <=> $1::halfvec) AS cosine_sim
                    FROM memories
                    WHERE embedding IS NOT NULL
                      AND searchable = 1
                      AND ($2::text IS NULL OR project = $2)
                    ORDER BY embedding <=> $1::halfvec
                    LIMIT $3
                """, vec, project_param, VECTOR_SEARCH_K)
        except Exception as e:
            logger.warning(f'Vector search failed, falling back to FTS: {e}')
            return await _fts_search_pg(conn, query_text, project, limit, memory_type=memory_type)

        if not vec_rows:
            return await _fts_search_pg(conn, query_text, project, limit, memory_type=memory_type)

        id_to_cosine = {r['id']: float(r['cosine_sim']) for r in vec_rows}
        ids = list(id_to_cosine.keys())

        # Hybrid re-rank: combine vector similarity + FTS rank
        rows = await conn.fetch("""
            SELECT m.id, m.title,
                   SUBSTRING(m.content_md, 1, 500) AS snippet,
                   m.memory_type, m.project, m.module,
                   m.created_at, m.access_count, m.confidence_score,
                   COALESCE(ts_rank(
                       to_tsvector('english', m.title || ' ' || m.content_md),
                       plainto_tsquery('english', $1)
                   ), 0.0) AS fts_score
            FROM memories m
            WHERE m.id = ANY($2)
        """, query_text, ids)

        results = []
        for row in rows:
            cosine_sim = id_to_cosine.get(row['id'], 0.0)
            fts = abs(float(row['fts_score']))
            raw = round(0.7 * cosine_sim + 0.3 * min(fts, 1.0), 4)
            created_str = _iso(row['created_at'])
            mem = {
                'created_at': created_str,
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
                'created_at': created_str,
                'access_count': row['access_count'],
                'confidence_score': row['confidence_score'],
            })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit], False, ''
