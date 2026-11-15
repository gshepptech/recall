"""
Retrieval eval harness — measure search quality so ranking changes are provable, not vibes.

Boots a throwaway Recall server against a temp SQLite DB, seeds a small labeled corpus, then
reports recall@k / precision@k over a set of labeled queries and a relevance-floor sweep.

Runs in keyword-only (FTS) mode when RECALL_EMBEDDING_API_KEY is unset, so it is deterministic and
CI-friendly. Set RECALL_EMBEDDING_API_KEY to evaluate the full hybrid (semantic + keyword) path.

Usage:  python3 -m recall.tests.eval_retrieval
Extend: add rows to CORPUS and QUERIES below — this is scaffolding, not a fixed benchmark.
"""

import os
import socket
import subprocess
import sys
import time

import httpx


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


_PORT = int(os.getenv('RECALL_PORT', str(_free_port())))
BASE = f'http://localhost:{_PORT}/webhook/recall'
HEADERS = {'Authorization': 'Bearer test-token-lite', 'Content-Type': 'application/json'}
TEST_DB = f'/tmp/recall_eval_{_PORT}.db'
K = 5

# Labeled corpus — title is the identity we score against.
CORPUS = [
    ('jwt authentication tokens',   'API auth uses JWT bearer tokens signed per request.'),
    ('postgresql pgvector store',   'Primary datastore is PostgreSQL 15 with the pgvector extension.'),
    ('rate limiting middleware',    'Requests are throttled by a token-bucket rate limiter.'),
    ('s3 bucket file uploads',      'User uploads are streamed to an S3 bucket.'),
    ('cron scheduled jobs',         'Background work runs on a cron schedule.'),
]

# query -> set of titles that SHOULD be retrieved.
QUERIES = [
    ('jwt auth token',            {'jwt authentication tokens'}),
    ('postgres vector database',  {'postgresql pgvector store'}),
    ('rate limit throttle',       {'rate limiting middleware'}),
    ('upload files to s3',        {'s3 bucket file uploads'}),
    ('scheduled cron job',        {'cron scheduled jobs'}),
]


def post(command: str, extra: dict = None) -> dict:
    return httpx.post(
        BASE, headers=HEADERS,
        json={'command': command, 'project': 'eval', **(extra or {})},
        timeout=30,
    ).json()


def recall_precision_at_k(retrieved: list, relevant: set, k: int) -> tuple:
    top = retrieved[:k]
    hits = sum(1 for t in top if t in relevant)
    recall = hits / len(relevant) if relevant else 0.0
    precision = hits / len(top) if top else 0.0
    return recall, precision


def run_eval() -> bool:
    for title, body in CORPUS:
        post('save_memory', {'title': title, 'content_md': body})

    print(f'\nRetrieval eval — k={K}, mode={"hybrid" if os.getenv("RECALL_EMBEDDING_API_KEY") else "keyword-only (FTS)"}')
    print('-' * 68)

    recalls, precisions = [], []
    for query, relevant in QUERIES:
        r = post('search', {'query': query, 'limit': K, 'min_relevance': 0.0})
        titles = [x['title'] for x in r.get('results', [])]
        rec, prec = recall_precision_at_k(titles, relevant, K)
        recalls.append(rec)
        precisions.append(prec)
        mark = 'ok ' if rec == 1.0 else 'MISS'
        print(f'  [{mark}] {query:<26} recall@{K}={rec:.2f} precision@{K}={prec:.2f}')

    mean_r = sum(recalls) / len(recalls)
    mean_p = sum(precisions) / len(precisions)
    print('-' * 68)
    print(f'  mean recall@{K}={mean_r:.3f}   mean precision@{K}={mean_p:.3f}')
    if not os.getenv('RECALL_EMBEDDING_API_KEY'):
        print('  note: keyword-only mode cannot match morphological variants '
              '(e.g. "postgres" -> "postgresql", "vector" -> "pgvector").')
        print('        those MISSes are exactly what the semantic half of hybrid search recovers — '
              'set RECALL_EMBEDDING_API_KEY to see recall rise.')

    # Floor sweep — how many results survive each relevance floor for one query.
    print('\nRelevance-floor sweep  (query: "jwt auth token")')
    print('-' * 68)
    for floor in (0.0, 0.1, 0.25, 0.5, 0.9):
        r = post('search', {'query': 'jwt auth token', 'limit': K, 'min_relevance': floor})
        print(f'  floor={floor:<4}  returned={r.get("count", 0)}  '
              f'suppressed={r.get("suppressed_low_relevance", 0)}')

    # Sanity gate — the harness measures quality; it is not a strict correctness test.
    # Keyword mode legitimately misses morphological variants, so the bar is a floor, not 1.0.
    ok = mean_r >= 0.6
    print('\nRESULT:', 'PASS' if ok else f'FAIL — mean recall@{K}={mean_r:.3f} below sanity floor 0.60')
    return ok


def main() -> bool:
    env = os.environ.copy()
    env.update({
        'RECALL_TOKEN': 'test-token-lite',
        'RECALL_PORT': str(_PORT),
        'RECALL_DB_PATH': TEST_DB,
        'RECALL_EMBEDDING_API_KEY': os.getenv('RECALL_EMBEDDING_API_KEY', ''),
        'RECALL_SKIP_ONBOARDING': '1',
    })
    proc = subprocess.Popen(
        [sys.executable, '-m', 'recall'],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    try:
        return run_eval()
    finally:
        proc.terminate()
        try:
            os.remove(TEST_DB)
        except OSError:
            pass


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
