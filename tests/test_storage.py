import pytest
from pathlib import Path
import config
from storage import (
    save_user,
    get_user,
    delete_user,
    set_user_auto_submit,
    get_user_credentials,
    save_cached_token,
    get_cached_token,
    add_daily_point,
    get_daily_points,
    clear_daily_points,
    set_skip_date,
    get_skip_date,
    set_auto_done_date,
    get_auto_done_date,
    record_submit_history,
    get_submit_history,
)


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    # Set dummy encryption key
    from crypto import generate_key
    dummy_key = generate_key()
    monkeypatch.setattr(config, "ENCRYPTION_KEY", dummy_key)

    # Point storage files to temporary directory
    monkeypatch.setattr(config, "USERS_STORE_FILE", tmp_path / "users_store.json")
    monkeypatch.setattr(config, "DAILY_POINTS_FILE", tmp_path / "daily_points.json")
    monkeypatch.setattr(config, "AUTO_STATE_FILE", tmp_path / "auto_state.json")
    monkeypatch.setattr(config, "EVENING_STATE_FILE", tmp_path / "evening_state.json")
    monkeypatch.setattr(config, "SUBMIT_HISTORY_FILE", tmp_path / "submit_history.json")
    monkeypatch.setattr(config, "TEMPLATES_FILE", tmp_path / "templates.json")


def test_user_crud():
    user_id = 12345
    save_user(user_id, "test@example.com", "mypassword123", auto_submit_enabled=False)
    
    user = get_user(user_id)
    assert user is not None
    assert user["email"] == "test@example.com"
    assert user["auto_submit_enabled"] is False

    creds = get_user_credentials(user_id)
    assert creds == ("test@example.com", "mypassword123")

    # Update auto submit
    set_user_auto_submit(user_id, True)
    assert get_user(user_id)["auto_submit_enabled"] is True

    # Token caching
    save_cached_token(user_id, "jwt-test-token-xyz")
    assert get_cached_token(user_id) == "jwt-test-token-xyz"

    # Delete user
    assert delete_user(user_id) is True
    assert get_user(user_id) is None


def test_daily_points():
    user_id = 999
    date_str = "2026-09-28"

    assert get_daily_points(user_id, date_str) == []

    add_daily_point(user_id, "Membuat modul login", date_str)
    add_daily_point(user_id, "Review PR bersama mentor", date_str)

    points = get_daily_points(user_id, date_str)
    assert len(points) == 2
    assert points[0] == "Membuat modul login"

    clear_daily_points(user_id, date_str)
    assert get_daily_points(user_id, date_str) == []


def test_auto_state_and_history():
    user_id = 555
    date_str = "2026-09-28"

    set_skip_date(user_id, date_str)
    assert get_skip_date(user_id) == date_str

    set_auto_done_date(user_id, date_str)
    assert get_auto_done_date(user_id) == date_str

    record_submit_history(user_id, date_str, "poin (Lokal)", 200, "success", "Berhasil submit")
    history = get_submit_history(user_id)
    assert len(history) == 1
    assert history[0]["http_code"] == 200
    assert history[0]["result"] == "success"
