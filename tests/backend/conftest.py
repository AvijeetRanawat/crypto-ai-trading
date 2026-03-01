import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import database
import dashboard_api


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "trading_data_test.db"
    monkeypatch.setenv("TRADING_SESSION_ID", "test-session")
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(database, "RUNTIME_SESSION_ID", "test-session")
    monkeypatch.setattr(dashboard_api.database, "DB_PATH", str(db_path))

    database.init_db()

    monkeypatch.setattr(dashboard_api, "SESSION_ID", "test-session")
    monkeypatch.setattr(dashboard_api, "SESSION_START", "1970-01-01T00:00:00")
    monkeypatch.setattr(dashboard_api, "SESSION_START_MS", 0)
    return db_path


@pytest.fixture()
def api_module(isolated_db: Path):
    return dashboard_api


@pytest.fixture()
def seed_basic_market_data(isolated_db: Path):
    import sqlite3

    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO prices (timestamp, symbol, price) VALUES (?, ?, ?)",
        [
            ("2026-01-01T00:00:00", "BTCUSDT", 100000.0),
            ("2026-01-01T00:01:00", "BTCUSDT", 100050.0),
            ("2026-01-01T00:02:00", "BTCUSDT", 100120.0),
            ("2026-01-01T00:03:00", "BTCUSDT", 100090.0),
            ("2026-01-01T00:04:00", "BTCUSDT", 100180.0),
            ("2026-01-01T00:05:00", "BTCUSDT", 100210.0),
            ("2026-01-01T00:06:00", "BTCUSDT", 100240.0),
            ("2026-01-01T00:07:00", "BTCUSDT", 100260.0),
            ("2026-01-01T00:08:00", "BTCUSDT", 100230.0),
            ("2026-01-01T00:09:00", "BTCUSDT", 100310.0),
        ],
    )
    conn.commit()
    conn.close()
