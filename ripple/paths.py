"""Shared storage-path resolution for the Ripple agent plugin and its dashboard backend.

Both surfaces call these helpers so they always target the active profile's
plugin data dir (``<hermes home>/plugin-data/ripple/``) — the same path for the
agent tool subprocess and the dashboard server. ``RIPPLE_DB`` /
``RIPPLE_RELEASES_DIR`` override the location for tests and seed scripts.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PLUGIN_NAME = "ripple"
DB_FILENAME = "data.db"
RELEASES_SUBDIR = "releases"


def _plugin_data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir(PLUGIN_NAME)


def db_path() -> Path:
    """Absolute path of the profile-local SQLite database (shared helper)."""
    env = os.environ.get("RIPPLE_DB")
    if env:
        return Path(env)
    return _plugin_data_dir() / DB_FILENAME


def releases_dir() -> Path:
    """Directory where published artifact HTML is written (created on demand)."""
    env = os.environ.get("RIPPLE_RELEASES_DIR")
    path = Path(env) if env else (_plugin_data_dir() / RELEASES_SUBDIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: Path) -> sqlite3.Connection:
    """Open a WAL-mode connection with manual transaction control.

    ``isolation_level=None`` puts sqlite3 in autocommit mode so the engine can
    issue explicit ``BEGIN IMMEDIATE`` ... ``COMMIT``/``ROLLBACK`` transactions.
    ``check_same_thread=False`` allows the threaded dashboard/tool environment
    to share one connection; ``busy_timeout`` makes a second writer wait.
    """
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,
        check_same_thread=False,
        timeout=30.0,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def open_connection() -> sqlite3.Connection:
    """Open a connection to the shared database path for the active profile."""
    return connect(db_path())
