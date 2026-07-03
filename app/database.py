"""
Database connection and initialization for PoolMon.

Uses Python's built-in sqlite3 module - no ORM, no migration framework.
The schema is applied once at startup via schema_v4.sql. All queries are
plain SQL with parameterized inputs (no string formatting of user data).
"""

import sqlite3
import os
from pathlib import Path

# Data directory is a mounted Docker volume in production.
# Falls back to a local path for development.
DATA_DIR = Path(os.environ.get("POOLMON_DATA_DIR", "/home/claude/pooltracker"))
DB_PATH = DATA_DIR / "poolmon.db"
SCHEMA_PATH = Path(__file__).parent.parent / "schema_v4.sql"


def get_connection() -> sqlite3.Connection:
    """
    Open and return a database connection with:
    - Foreign key enforcement enabled (SQLite requires this per-connection)
    - Row factory set so results come back as dict-like objects
    - WAL journal mode for slightly better concurrent read performance
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    """
    Initialize the database from schema_v4.sql if it hasn't been set up yet.
    Safe to call on every startup - CREATE TABLE IF NOT EXISTS handles re-runs,
    but the schema uses CREATE TABLE (not IF NOT EXISTS) so we check first.
    """
    db_exists = DB_PATH.exists() and DB_PATH.stat().st_size > 0

    if db_exists:
        return  # already initialized, nothing to do

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text()
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
