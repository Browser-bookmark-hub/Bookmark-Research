"""One open policy for every local SQLite store.

Read paths must keep working when the data directory is read-only: a shared
index, a read-only mount, or a host sandbox that only allows the workspace.
Writers keep WAL and schema initialization; readers fall back to ``mode=ro``
instead of failing or silently creating sidecar files next to the index.
"""
import sqlite3
from pathlib import Path

_READONLY_HINTS = (
    "readonly",
    "read-only",
    "unable to open database",
    "operation not permitted",
    "permission denied",
    "no authorization to access",
)


def is_readonly_failure(error):
    """True when the filesystem refused a write, rather than the query being wrong."""
    if isinstance(error, (PermissionError, NotADirectoryError)):
        return True
    message = str(error).casefold()
    return any(hint in message for hint in _READONLY_HINTS)


def connect(path, readonly=False, timeout=10.0):
    """Open ``path`` read-only (URI, ``mode=ro``) or read-write."""
    path = Path(path)
    if not readonly:
        return sqlite3.connect(str(path), timeout=timeout)
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=timeout)
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()  # open now, not on first use
        return connection
    except sqlite3.OperationalError as error:
        # A WAL database with no ``-shm`` beside it cannot be opened read-only on
        # a read-only directory. The sidecars are absent exactly when no writer is
        # active, so reading the main file as immutable is safe here.
        if "unable to open database file" not in str(error).casefold():
            raise
        return sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=timeout)


def mark_query_only(connection):
    """Tell shared helpers that this connection must not attempt self-healing writes."""
    try:
        connection.execute("PRAGMA query_only=ON")
    except sqlite3.DatabaseError:
        pass
    return connection


def is_query_only(connection):
    try:
        return bool(connection.execute("PRAGMA query_only").fetchone()[0])
    except (sqlite3.DatabaseError, TypeError):
        return False
