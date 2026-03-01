from fastapi.testclient import TestClient
import pytest

import database
from dashboard_api import app


@pytest.fixture(autouse=True)
def clean_rl_db(tmp_path, monkeypatch):
    db_file = tmp_path / "trading_test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def test_rl_cost_endpoint_reports_events_and_penalties(client):
    database.save_rl_event(
        mode="SPOT",
        profile_id="profile-a",
        state_key="state-a",
        event_type="SKIP_OPPORTUNITY",
        reason="edge",
        symbol="BTCUSDT",
        penalty=0.123456,
        reward=-0.05,
    )

    response = client.get("/api/rl/cost")
    assert response.status_code == 200

    payload = response.json()
    assert payload["session"]["events"] == 1
    assert payload["session"]["skip_penalty"] == 0.123456
    assert payload["session"]["total_penalty"] == 0.123456
    assert payload["session"]["total_reward"] == -0.05

    assert payload["recent"][0]["event_type"] == "SKIP_OPPORTUNITY"
    assert payload["recent"][0]["symbol"] == "BTCUSDT"


def test_rl_cost_endpoint_splits_hold_penalty_and_rewards(client):
    database.save_rl_event(
        mode="FUTURES",
        profile_id="profile-b",
        state_key="state-b",
        event_type="SKIP_OPPORTUNITY",
        penalty=0.02,
        reward=0.0,
    )
    database.save_rl_event(
        mode="OPTIONS",
        profile_id="profile-c",
        state_key="state-c",
        event_type="TRADE_CLOSE_REWARD",
        penalty=0.01,
        reward=0.25,
    )

    response = client.get("/api/rl/cost")
    payload = response.json()
    assert payload["session"]["events"] == 2
    assert payload["session"]["skip_penalty"] == 0.02
    assert payload["session"]["hold_penalty"] == 0.01
    assert payload["session"]["total_penalty"] == 0.03
    assert payload["session"]["total_reward"] == 0.25
    assert payload["today"]["events"] == 2
