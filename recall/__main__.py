import argparse
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv


# ── Update check (background, fail-silent) ────────────────────────────────────

def _check_for_updates():
    """Spawn a daemon thread that compares local git SHA to GitHub HEAD."""
    def _check():
        try:
            import json
            import urllib.request

            req = urllib.request.Request(
                'https://api.github.com/repos/gshepptech/recall/commits/main',
                headers={'User-Agent': 'recall-update-check/1.0'},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            remote_sha = data['sha'][:7]

            # Try git rev-parse first, fall back to reading .git/refs directly
            install_dir = Path(__file__).parent.parent
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=install_dir, capture_output=True, text=True, timeout=2,
                )
                local_sha = result.stdout.strip()[:7]
            except Exception:
                ref_file = install_dir / '.git' / 'refs' / 'heads' / 'main'
                local_sha = ref_file.read_text().strip()[:7] if ref_file.exists() else None

            if local_sha and remote_sha != local_sha:
                print('\n\u26a0  Recall update available \u2014 run: recall update\n', flush=True)
        except Exception:
            pass  # unreachable host, not a git repo, etc.: fail silently

    t = threading.Thread(target=_check, daemon=True)
    t.start()


# ── Update subcommand ─────────────────────────────────────────────────────────

def run_update():
    """Pull the latest code, reinstall the package, and restart the service if it runs under systemd."""
    install_dir = Path(__file__).parent.parent

    print('Updating Recall...\n')

    # 1. git pull
    try:
        result = subprocess.run(
            ['git', 'pull', 'origin', 'main'],
            cwd=install_dir, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        print(result.stdout.strip() or 'Already up to date.')
    except Exception as e:
        print('Cannot update \u2014 not installed via git.')
        print('Download the latest release from https://github.com/gshepptech/recall')
        print(f'({e})')
        sys.exit(1)

    # 2. pip install
    load_dotenv(install_dir / '.env')
    backend = os.getenv('RECALL_DB_BACKEND', 'sqlite').lower()
    pip_arg = '-e .[postgres]' if backend == 'postgres' else '-e .'
    pip_result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install'] + pip_arg.split(),
        cwd=install_dir, capture_output=True, text=True,
    )
    if pip_result.returncode != 0:
        print(f'pip install warning: {pip_result.stderr[-300:]}')
    else:
        print(f'pip: {pip_arg} installed OK')

    # 3. new sha
    try:
        sha_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=install_dir, capture_output=True, text=True,
        )
        new_sha = sha_result.stdout.strip()[:7]
    except Exception:
        new_sha = 'unknown'

    # 4. Docker: print rebuild instructions, do not rebuild automatically
    if Path('/.dockerenv').exists():
        print('\nRunning inside Docker \u2014 to apply the update, run on the host:')
        print('  docker compose up -d --build')
        restart_status = 'manual step required'
    else:
        # 5. systemd: restart if the service is active
        try:
            check = subprocess.run(
                ['systemctl', '--user', 'is-active', 'recall'],
                capture_output=True, text=True, timeout=5,
            )
            if check.stdout.strip() == 'active':
                subprocess.run(
                    ['systemctl', '--user', 'restart', 'recall'], check=True, timeout=10,
                )
                restart_status = 'done (systemd restarted)'
            else:
                restart_status = 'not running as systemd service'
        except Exception:
            restart_status = 'not running as systemd service'

    print(f'\nRecall updated to {new_sha}')
    print(f'Restart: {restart_status}')


# ── Server entry point ────────────────────────────────────────────────────────

def main():
    # Handle `recall update` before argparse so the server flags don't interfere
    if len(sys.argv) > 1 and sys.argv[1] == 'update':
        run_update()
        return

    parser = argparse.ArgumentParser(
        prog='recall',
        description='Recall: a self-hosted shared memory server for AI coding agents.',
        epilog='Run "recall update" to pull the latest version. '
               'Settings are read from .env; see .env.example.',
    )
    parser.add_argument('--host', default=None,
                        help='address to bind (default: RECALL_HOST or 0.0.0.0)')
    parser.add_argument('--port', type=int, default=None,
                        help='port to listen on (default: RECALL_PORT or 8000)')
    parser.add_argument('--no-onboarding', action='store_true',
                        help='skip the interactive first-run setup (read settings from the environment)')
    args = parser.parse_args()

    if args.no_onboarding:
        os.environ['RECALL_SKIP_ONBOARDING'] = '1'

    if not os.path.exists('.env') and os.environ.get('RECALL_SKIP_ONBOARDING') != '1':
        print('No .env found. Run: ./install.sh  (or: cp .env.example .env)', file=sys.stderr)
        sys.exit(1)

    load_dotenv()

    # Warn if env-token auth is disabled
    if not os.getenv('RECALL_TOKEN', '').strip():
        print(
            'WARNING: RECALL_TOKEN is empty \u2014 all auth will fall through to DB token lookup. '
            'Set RECALL_TOKEN in .env to enable env-token auth.',
            file=sys.stderr,
        )

    host = args.host or os.getenv('RECALL_HOST', '0.0.0.0')
    port = args.port or int(os.getenv('RECALL_PORT', '8000'))
    backend = os.getenv('RECALL_DB_BACKEND', 'sqlite').lower()

    if backend not in ('sqlite', 'postgres'):
        print(
            f'ERROR: RECALL_DB_BACKEND={backend!r} is not valid. Use: sqlite or postgres',
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')

    # SQLite: run migrations + onboarding once before uvicorn starts.
    # init_db() is idempotent; the server's lifespan will call it again and skip.
    if backend == 'sqlite':
        from recall.db import init_db
        from recall.onboarding import run_onboarding
        db, _ = init_db()
        run_onboarding(db, port=port)

    # Background update check: non-blocking, fail-silent
    _check_for_updates()

    import uvicorn
    uvicorn.run('recall.server:app', host=host, port=port, reload=False, log_level='info')


if __name__ == '__main__':
    main()
