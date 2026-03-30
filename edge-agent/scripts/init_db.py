#!/usr/bin/env python3
"""Initialize SQLite database for edge agent."""

import sqlite3
import os

DB_PATH = os.environ.get("EDGE_DB_PATH", "/data/edge.db")

SCHEMA = """
-- Discovered devices
CREATE TABLE IF NOT EXISTS devices (
    device_id       INTEGER PRIMARY KEY,  -- BACnet device instance
    address         TEXT NOT NULL,        -- IP:port
    name            TEXT,
    vendor          TEXT,
    model           TEXT,
    discovered_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

-- Discovered objects per device
CREATE TABLE IF NOT EXISTS objects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER NOT NULL REFERENCES devices(device_id),
    object_type     TEXT NOT NULL,        -- analog-input, binary-value, etc.
    object_instance INTEGER NOT NULL,
    object_name     TEXT,
    unit            TEXT,
    discovered_at   TEXT NOT NULL,
    UNIQUE(device_id, object_type, object_instance)
);

-- Readings buffer (for offline/retry)
CREATE TABLE IF NOT EXISTS readings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER NOT NULL,
    object_type     TEXT NOT NULL,
    object_instance INTEGER NOT NULL,
    value           REAL,
    status_flags    TEXT,                 -- JSON
    read_at         TEXT NOT NULL,        -- ISO8601 timestamp
    uploaded        INTEGER DEFAULT 0     -- 0=pending, 1=uploaded
);

-- Config cache (intervals, platform settings)
CREATE TABLE IF NOT EXISTS config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,        -- JSON
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS readings_pending_idx ON readings(uploaded, read_at);
CREATE INDEX IF NOT EXISTS objects_device_idx ON objects(device_id);
"""


def init_db():
    """Create database and tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # Enable WAL mode for concurrent access
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()
    print(f"Initialized database at {DB_PATH} (WAL mode)")


if __name__ == "__main__":
    init_db()
