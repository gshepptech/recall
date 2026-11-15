import re
import secrets
import sqlite3
import uuid
from pathlib import Path


BANNER = """
Recall: shared memory for AI coding agents
==========================================
"""


def _ask(prompt: str, validator=None, default: str = None) -> str:
    while True:
        suffix = f' [{default}]' if default else ''
        raw = input(f'{prompt}{suffix}: ').strip()
        if not raw and default:
            return default
        if not raw:
            print('  Required — please enter a value.')
            continue
        if validator:
            err = validator(raw)
            if err:
                print(f'  {err}')
                continue
        return raw


def _validate_name(v: str):
    if ' ' in v:
        return 'No spaces allowed.'
    return None


def _validate_token_name(v: str):
    if not re.match(r'^[a-z0-9][a-z0-9\-]*$', v):
        return 'Lowercase letters, digits, and hyphens only. Must start with a letter or digit.'
    return None


def run_onboarding(conn: sqlite3.Connection, port: int = 8000):
    import os
    import sys
    if os.getenv('RECALL_SKIP_ONBOARDING') or not sys.stdin or not sys.stdin.isatty():
        return

    # Skip if any token already exists
    row = conn.execute('SELECT COUNT(*) FROM access_tokens').fetchone()
    if row[0] > 0:
        return

    # Seed global project memory
    memory_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO memories (id, project, memory_type, title, content_md, created_by)
        VALUES (?, 'global', 'decision', 'recall initialized',
                'Recall installed and running. Global project created.', 'system')
        ON CONFLICT(title, memory_type, project) DO NOTHING
    """, [memory_id])
    seed_row = conn.execute(
        "SELECT rowid FROM memories WHERE title='recall initialized' AND memory_type='decision'"
    ).fetchone()
    if seed_row:
        conn.execute(
            'INSERT OR REPLACE INTO memories_fts(rowid, title, content_md) VALUES (?, ?, ?)',
            [seed_row[0], 'recall initialized',
             'Recall installed and running. Global project created.']
        )
    conn.commit()

    # Ask for a name and a token label
    print(BANNER)
    print('Setting up your Recall install. Answer 2 quick questions.\n')

    person_name = _ask('Your name (no spaces)', _validate_name)
    token_name = _ask('Token name (e.g. my-laptop)', _validate_token_name)

    # Generate token and save to DB
    token = 'recall-' + secrets.token_hex(8)
    token_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO access_tokens (id, token, person_name, token_name, role, active)
        VALUES (?, ?, ?, ?, 'admin', 1)
    """, [token_id, token, person_name, token_name])
    conn.commit()

    recall_url = f'http://localhost:{port}'

    # Save token file
    token_dir = Path.home() / '.recall'
    token_dir.mkdir(parents=True, exist_ok=True)
    token_file = token_dir / 'token'
    token_file.write_text(
        f'RECALL_TOKEN={token}\n'
        f'RECALL_URL={recall_url}\n'
    )
    token_file.chmod(0o600)

    # Print Claude Code connect steps
    print('\n' + '=' * 60)
    print('  Recall is ready')
    print('=' * 60)
    print(f'\n  Token:   {token}')
    print(f'  URL:     {recall_url}')
    print(f'\n  Token saved to: {token_file}')
    print('\n' + '-' * 60)
    print('  Connect Claude Code to Recall:')
    print('-' * 60)
    print("""
  In Claude Code, install the plugin and connect. /recall:connect reads the
  token file written above, so the token never enters the conversation.

    /plugin marketplace add gshepptech/recall
    /plugin install recall@recall
    /recall:connect
""")
    print('=' * 60 + '\n')
