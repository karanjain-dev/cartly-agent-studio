"""Local development startup. No Docker requirement; optional external PostgreSQL."""
import os
import secrets
from pathlib import Path

from service.repository import Repository, ROOT

STATE_DIR = ROOT / ".cartly-service"


def repository():
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    dsn = os.environ.get("CARTLY_DATABASE_URL")
    handle = None
    if not dsn:
        import pgserver
        # Socket-only local postgres. pgserver retains the cluster when it stops.
        handle = pgserver.get_server(STATE_DIR / "postgres", cleanup_mode="stop")
        dsn = handle.get_uri()
    repo = Repository(dsn)
    repo._local_postgres = handle  # Hold its lifetime through the server/command.
    repo.migrate()
    return repo


def operator_key():
    configured = os.environ.get("CARTLY_SERVICE_KEY")
    if configured:
        return configured
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    keyfile = STATE_DIR / "operator.key"
    try:
        descriptor = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return keyfile.read_text().strip()
    with os.fdopen(descriptor, "w") as file:
        key = secrets.token_urlsafe(40)
        file.write(key + "\n")
    return key
