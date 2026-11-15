import subprocess
import time
import os
import sys
import socket
import httpx


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


_PORT = int(os.getenv('RECALL_PORT', str(_find_free_port())))
BASE = f'http://localhost:{_PORT}/webhook/recall'
HEADERS = {'Authorization': 'Bearer test-token-lite', 'Content-Type': 'application/json'}
TEST_DB = f'/tmp/recall_test_{_PORT}.db'

def post(command: str, extra: dict = None) -> dict:
    if extra is None:
        extra = {}
    return httpx.post(
        BASE, headers=HEADERS,
        json={'command': command, 'project': 'test', **extra},
        timeout=30
    ).json()


# ─── Test functions ───────────────────────────────────────────────────────────

def save_memory_plain():
    r = post('save_memory', {'title': 'auth uses JWT tokens', 'content_md': 'We use JWT for all API authentication.'})
    assert r.get('status') == 'saved', f'expected status=saved, got {r}'
    assert 'id' in r


def save_memory_tags():
    r = post('save_memory', {
        'title': 'database uses PostgreSQL',
        'content_md': 'Primary datastore is PostgreSQL 15 with pgvector.',
        'tags': ['database', 'postgres'],
        'memory_type': 'decision',
    })
    assert r.get('status') == 'saved', f'expected status=saved, got {r}'


def save_memory_duplicate():
    # Save same title twice — should return same id (ON CONFLICT DO NOTHING)
    r1 = post('save_memory', {'title': 'duplicate test memory', 'content_md': 'first version'})
    r2 = post('save_memory', {'title': 'duplicate test memory', 'content_md': 'second version'})
    assert r1['id'] == r2['id'], f'expected same id on duplicate, got {r1["id"]} vs {r2["id"]}'


def search_keyword():
    r = post('search', {'query': 'JWT authentication', 'limit': 5})
    assert 'results' in r, f'no results key in {r}'
    assert r['count'] >= 0
    titles = [x['title'] for x in r['results']]
    assert any('JWT' in t or 'auth' in t.lower() for t in titles), f'expected auth memory in results, got {titles}'


def search_semantic():
    # Save a memory with specific words, search with different synonyms
    post('save_memory', {'title': 'deployment uses containers', 'content_md': 'We use Docker containers for deployment.'})
    r = post('search', {'query': 'docker kubernetes orchestration', 'limit': 5})
    assert 'results' in r
    scores = [x['score'] for x in r['results']]
    if os.getenv('RECALL_EMBEDDING_API_KEY'):
        assert any(s > 0.25 for s in scores), f'expected score > 0.25, got scores {scores}'
    else:
        assert any(s != 0 for s in scores), f'expected non-zero score in FTS-only mode, got scores {scores}'


def search_token_budget():
    r = post('search', {'query': 'auth JWT tokens', 'limit': 5, 'max_tokens': 50})
    assert 'tokens_used' in r, f'tokens_used missing from {r}'
    assert r['tokens_used'] <= 50, f'token budget exceeded: {r["tokens_used"]}'


def search_alias_find():
    r = post('find', {'query': 'authentication'})
    assert r.get('_use_command') == 'search'
    assert r.get('_was_alias') is True


def search_alias_recall():
    r = post('recall', {'query': 'database'})
    assert r.get('_use_command') == 'search'
    assert r.get('_was_alias') is True


def get_memory_by_title():
    r = post('get_memory', {'title': 'auth uses JWT tokens'})
    assert 'id' in r, f'expected id in {r}'
    assert r.get('title') == 'auth uses JWT tokens'
    assert 'content_md' in r


def get_prompt_by_name():
    # First save a prompt memory
    post('save_memory', {
        'title': 'test:sample_prompt',
        'content_md': '# Sample\nDo the thing.',
        'memory_type': 'prompt',
    })
    r = post('get_prompt', {'prompt_name': 'test:sample_prompt'})
    assert 'content_md' in r, f'expected content_md in {r}'
    assert r.get('title') == 'test:sample_prompt'


def get_prompt_alias():
    r = post('fetch_prompt', {'prompt_name': 'test:sample_prompt'})
    assert r.get('_use_command') == 'get_prompt'
    assert r.get('_was_alias') is True


def log_run_plain():
    r = post('log_run', {
        'runner': 'test-agent',
        'status': 'success',
        'output_summary': 'Completed test run.',
        'tokens_input': 100,
        'tokens_output': 50,
    })
    assert r.get('status') == 'logged', f'expected status=logged, got {r}'
    assert 'id' in r


def log_run_auto_links_prompt_id():
    """v1.0.6 server-side handshake: get_prompt(runner=X) records pending_runs,
    and the next log_run(runner=X) auto-links prompt_id without the client
    ever having to know the UUID."""
    # Save a prompt to fetch
    post('save_memory', {
        'title': 'test:auto_link_prompt',
        'content_md': '# linked\nBody of the prompt under test.',
        'memory_type': 'prompt',
    })

    # Fetch with a runner — server records the handshake
    p = post('get_prompt', {
        'prompt_name': 'test:auto_link_prompt',
        'runner': 'handshake-host',
    })
    assert 'id' in p, f'expected id in get_prompt response, got {p}'
    expected_id = p['id']

    # Log run with the same runner and NO explicit prompt_id
    r = post('log_run', {
        'runner': 'handshake-host',
        'status': 'success',
        'output_summary': 'handshake verification',
        'tokens_input': 11,
        'tokens_output': 22,
    })
    assert r.get('status') == 'logged', f'expected status=logged, got {r}'
    run_id = r.get('id')

    # Verify linkage via direct DB read (webhook doesn't expose list_runs)
    import sqlite3
    conn = sqlite3.connect(TEST_DB)
    try:
        row = conn.execute(
            "SELECT prompt_id FROM prompt_runs WHERE id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f'run {run_id} not found in prompt_runs'
    assert row[0] == expected_id, f'expected prompt_id={expected_id}, got {row[0]}'

    # Second log_run from same runner (no new get_prompt) must NOT re-link —
    # pending_runs should have been consumed by the first call.
    r2 = post('log_run', {
        'runner': 'handshake-host',
        'status': 'success',
        'output_summary': 'second run, no new fetch',
    })
    run_id_2 = r2.get('id')
    conn = sqlite3.connect(TEST_DB)
    try:
        row2 = conn.execute(
            "SELECT prompt_id FROM prompt_runs WHERE id = ?", (run_id_2,)
        ).fetchone()
    finally:
        conn.close()
    assert row2 is not None and row2[0] is None, \
        f'expected prompt_id=NULL on second run (pending consumed), got {row2}'


def log_run_alias():
    r = post('log_session', {'runner': 'test-agent', 'status': 'success'})
    assert r.get('_use_command') == 'log_run'
    assert r.get('_was_alias') is True


def log_error_plain():
    r = post('log_error', {
        'runner': 'test-agent',
        'error_type': 'ValueError',
        'message': 'Something went wrong in test.',
    })
    assert r.get('status') == 'logged', f'expected status=logged, got {r}'
    assert 'id' in r


def save_requirement_plain():
    r = post('save_requirement', {
        'title': 'API must respond within 200ms',
        'content_md': 'All endpoints must return responses within 200ms under normal load.',
    })
    assert r.get('status') == 'saved', f'expected status=saved, got {r}'
    assert 'id' in r


def unknown_command():
    r = post('totally_unknown_command_xyz')
    assert 'error' in r, f'expected error key for unknown command, got {r}'
    assert 'available_commands' in r


def auth_failure():
    resp = httpx.post(
        BASE,
        headers={'Authorization': 'Bearer wrong-token', 'Content-Type': 'application/json'},
        json={'command': 'search', 'project': 'test', 'query': 'test'},
        timeout=10
    )
    assert resp.status_code == 401, f'expected 401, got {resp.status_code}'


def use_command_field():
    r = post('search', {'query': 'jwt'})
    assert '_use_command' in r, f'_use_command missing from {r}'
    assert r['_use_command'] == 'search'


def was_alias_field():
    r = post('find', {'query': 'database'})
    assert r.get('_was_alias') is True
    assert r.get('_raw_command') == 'find'
    assert r.get('_use_command') == 'search'


def search_returns_relevance():
    # Every result carries a query-relevance value in [0,1], distinct from the health score.
    r = post('search', {'query': 'JWT authentication', 'limit': 5})
    for x in r['results']:
        assert 'relevance' in x, f'relevance missing from result {x}'
        assert 0.0 <= x['relevance'] <= 1.0, f'relevance out of range: {x["relevance"]}'


def confidence_persist_and_preserve():
    # Confidence provided at save time is persisted...
    tok = 'zzqconfidencemarker'
    post('save_memory', {'title': f'{tok} alpha', 'content_md': 'confidence persistence probe', 'confidence': 0.2})
    r = post('search', {'query': tok, 'limit': 5})
    hit = next((x for x in r['results'] if x['title'] == f'{tok} alpha'), None)
    assert hit is not None, f'saved memory not found in {r}'
    assert abs(hit['confidence_score'] - 0.2) < 1e-6, f'expected confidence 0.2, got {hit["confidence_score"]}'
    # ...and a re-save WITHOUT confidence must not clobber it (COALESCE preserve).
    post('save_memory', {'title': f'{tok} alpha', 'content_md': 'updated body, no confidence'})
    r2 = post('search', {'query': tok, 'limit': 5})
    hit2 = next((x for x in r2['results'] if x['title'] == f'{tok} alpha'), None)
    assert hit2 is not None and abs(hit2['confidence_score'] - 0.2) < 1e-6, \
        f'confidence should survive a confidence-less re-save, got {hit2}'


def relevance_floor_suppresses():
    # Floor 0 returns matches; a floor just above the best match suppresses everything and
    # reports it. Deriving the threshold from observed relevance keeps this valid in both
    # keyword-only (relevance clamps to 1.0) and hybrid modes.
    q = {'query': 'JWT authentication', 'limit': 5}
    low = post('search', {**q, 'min_relevance': 0.0})
    assert low['count'] > 0, f'expected results at floor 0, got {low}'
    top = max(x['relevance'] for x in low['results'])
    high = post('search', {**q, 'min_relevance': round(top + 0.01, 4)})
    assert high['count'] == 0, f'expected all suppressed above top relevance {top}, got {high}'
    assert high.get('suppressed_low_relevance', 0) > 0, f'expected suppression count, got {high}'
    assert 'note' in high, f'expected a no-confident-match note, got {high}'


# ─── Test registry ────────────────────────────────────────────────────────────

TESTS = [
    ('save_memory plain',              save_memory_plain),
    ('save_memory with tags',          save_memory_tags),
    ('save_memory duplicate (upsert)', save_memory_duplicate),
    ('search keyword match',           search_keyword),
    ('search semantic (diff words)',   search_semantic),
    ('search token budget enforced',   search_token_budget),
    ('search alias: find',             search_alias_find),
    ('search alias: recall',           search_alias_recall),
    ('get_memory by title',            get_memory_by_title),
    ('get_prompt by name',             get_prompt_by_name),
    ('get_prompt alias: fetch_prompt', get_prompt_alias),
    ('log_run plain',                  log_run_plain),
    ('log_run auto-links prompt_id',   log_run_auto_links_prompt_id),
    ('log_run alias: log_session',     log_run_alias),
    ('log_error plain',                log_error_plain),
    ('save_requirement',               save_requirement_plain),
    ('search returns relevance field', search_returns_relevance),
    ('confidence persist + preserve',  confidence_persist_and_preserve),
    ('relevance floor suppresses',     relevance_floor_suppresses),
    ('unknown command fallback',       unknown_command),
    ('auth failure (bad token)',       auth_failure),
    ('_use_command present always',    use_command_field),
    ('_was_alias set on alias',        was_alias_field),
]


def run_all():
    env = os.environ.copy()
    env.update({
        'RECALL_TOKEN': 'test-token-lite',
        'RECALL_PORT': str(_PORT),
        'RECALL_DB_PATH': TEST_DB,
        'RECALL_EMBEDDING_API_KEY': os.getenv('RECALL_EMBEDDING_API_KEY', ''),
    })

    env['RECALL_SKIP_ONBOARDING'] = '1'
    proc = subprocess.Popen(
        [sys.executable, '-m', 'recall'],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    results = []
    try:
        for name, fn in TESTS:
            try:
                fn()
                results.append((name, 'PASS', None))
            except Exception as e:
                results.append((name, 'FAIL', str(e)))
    finally:
        proc.terminate()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    print()
    print(f"{'#':<4} {'Test':<45} {'Result'}")
    print('-' * 65)
    passed = 0
    for i, (name, status, err) in enumerate(results, 1):
        icon = '\u2705' if status == 'PASS' else '\u274c'
        print(f'{i:<4} {name:<45} {icon} {status}')
        if err:
            print(f'     Error: {err}')
        if status == 'PASS':
            passed += 1
    print()
    print(f'Results: {passed}/{len(results)} passed')
    return passed == len(results)


def test_suite():
    """Pytest entry point — runs the full integration suite via run_all()."""
    assert run_all(), "One or more integration tests failed — see output above"


if __name__ == '__main__':
    success = run_all()
    sys.exit(0 if success else 1)
