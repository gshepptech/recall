"""Bearer-token authentication and role permissions shared by the webhook and MCP transports."""
import os
import secrets
from fastapi import HTTPException, Request

from recall.db import get_db_and_lock

RECALL_TOKEN = os.getenv('RECALL_TOKEN', '')

ROLE_ORDER = ['viewer', 'developer', 'admin', 'owner']

# Minimum role required per canonical command
COMMAND_MIN_ROLE = {
    'search':               'viewer',
    'get_memory':           'viewer',
    'get_prompt':           'viewer',
    'list_prompts':         'viewer',
    'list_requirements':    'viewer',
    'recall_help':          'viewer',
    'version':              'viewer',
    'hygiene_report':       'viewer',
    'save_memory':          'developer',
    'save_prompt':          'developer',
    'save_requirement':     'developer',
    'promote_requirement':  'developer',
    'log_run':              'developer',
    'log_error':            'developer',
    'get_schema':           'admin',
    'delete_memory':        'admin',
    'debug_protocol':       'admin',
    'create_token':         'owner',
}

# Commands each role may not run: everything whose minimum role ranks above it
ROLE_PERMISSIONS = {
    role: [
        cmd for cmd, min_role in COMMAND_MIN_ROLE.items()
        if ROLE_ORDER.index(min_role) > ROLE_ORDER.index(role)
    ]
    for role in ROLE_ORDER
}


async def verify_auth(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:].strip()
    else:
        token = request.query_params.get('token', '').strip()
    if not token:
        raise HTTPException(status_code=401, detail='Unauthorized')

    # Reload env token each call so RECALL_TOKEN changes are picked up at runtime
    env_token = os.getenv('RECALL_TOKEN', RECALL_TOKEN)

    # The env token is the owner: every command, no project scope
    if env_token and secrets.compare_digest(token.encode(), env_token.encode()):
        info = {'token': token, 'role': 'owner', 'label': 'owner', 'project_scope': None}
        request.state.token_label = 'owner'
        return info

    backend = os.getenv('RECALL_DB_BACKEND', 'sqlite').lower()
    if backend == 'postgres':
        from recall.db_postgres import get_pg_pool, verify_token_pg
        pool = get_pg_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail='Database not ready')
        result = await verify_token_pg(pool, token)
        if not result:
            raise HTTPException(status_code=401, detail='Unauthorized')
        request.state.token_label = result['label']
        return {
            'token': token,
            'role': result['role'],
            'label': result['label'],
            'project_scope': result.get('project_scope'),
        }

    # SQLite path
    db, lock = get_db_and_lock()
    if db is None or lock is None:
        raise HTTPException(status_code=503, detail='Database not initialised')
    with lock:
        row = db.execute(
            'SELECT role, person_name, project_scope FROM access_tokens WHERE token = ? AND active = 1',
            [token]
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail='Unauthorized')

    label = row[1] or ''
    request.state.token_label = label
    return {'token': token, 'role': row[0], 'label': label, 'project_scope': row[2]}


def assert_scope(auth_info: dict, project: str) -> None:
    """Raise 403 if the token is restricted to a different project."""
    scope = auth_info.get('project_scope')
    if scope and scope != project:
        raise HTTPException(status_code=403, detail=scope_mismatch_detail(scope, project))


def scope_mismatch_detail(scope: str, project: str) -> dict:
    """Error payload for a project-scoped token used against another project."""
    return {
        'error': 'token_scope_mismatch',
        'project_scope': scope,
        'requested_project': project,
        'message': (
            f"This token is restricted to project '{scope}'. "
            f"Set \"project\": \"{scope}\" in your request to continue."
        ),
        'hint': f'Change your project parameter to "{scope}".',
    }
