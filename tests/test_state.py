import json
import pytest
import config
from state import load_state, save_state, get_default_state


@pytest.fixture(autouse=True)
def setup_state_file(tmp_path, monkeypatch):
    test_state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "STATE_FILE", test_state_file)


def test_default_state():
    state = get_default_state("2026-10-05")
    assert state["date"] == "2026-10-05"
    assert state["warned_date"] is None
    assert state["done_date"] is None
    assert state["attempts"] == 0


def test_save_and_load_state(monkeypatch):
    monkeypatch.setattr(config, "get_today_wib_str", lambda: "2026-10-05")
    state = load_state()
    assert state["date"] == "2026-10-05"

    state["warned_date"] = "2026-10-05"
    state["attempts"] = 1
    changed = save_state(state)
    assert changed is True

    # Calling save again with same content returns False (no change)
    assert save_state(state) is False

    loaded = load_state()
    assert loaded["warned_date"] == "2026-10-05"
    assert loaded["attempts"] == 1


def test_date_rollover_reset(monkeypatch):
    # Set today as 2026-10-05
    monkeypatch.setattr(config, "get_today_wib_str", lambda: "2026-10-05")
    state = load_state()
    state["done_date"] = "2026-10-05"
    state["warned_date"] = "2026-10-05"
    state["attempts"] = 2
    save_state(state)

    # Next day 2026-10-06: should auto reset
    monkeypatch.setattr(config, "get_today_wib_str", lambda: "2026-10-06")
    new_day_state = load_state()
    assert new_day_state["date"] == "2026-10-06"
    assert new_day_state["done_date"] is None
    assert new_day_state["warned_date"] is None
    assert new_day_state["attempts"] == 0


def test_no_sensitive_data_saved(monkeypatch):
    monkeypatch.setattr(config, "get_today_wib_str", lambda: "2026-10-05")
    dirty_state = {
        "date": "2026-10-05",
        "warned_date": "2026-10-05",
        "done_date": None,
        "attempts": 0,
        "password": "secret_password_123",
        "token": "secret_jwt_token",
        "report_content": "Laporan harian magang...",
        "points": ["Point 1", "Point 2"],
    }
    save_state(dirty_state)

    with open(config.STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Verify disallowed keys were discarded
    assert "password" not in data
    assert "token" not in data
    assert "report_content" not in data
    assert "points" not in data
    assert set(data.keys()) == {"date", "warned_date", "done_date", "attempts"}
