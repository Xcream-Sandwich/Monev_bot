import pytest
import logging
import asyncio
from datetime import datetime, time
import config
from state import load_state
from runner import execute_submit_flow, run_actions


async def mock_async_return(val):
    return val


@pytest.mark.asyncio
async def test_no_sensitive_data_in_runner_logs(caplog, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(config, "MONEV_EMAIL", "myemail@kemnaker.go.id")
    monkeypatch.setattr(config, "MONEV_PASSWORD", "SuperSecretPassword123!@#")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123456:SecretBotToken")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", 99887766)
    monkeypatch.setattr(config, "get_today_wib_str", lambda: "2026-10-05")

    caplog.set_level(logging.DEBUG)

    sensitive_point = "SecretProjectX_InternalFeatureImplementation"
    state = load_state()
    inbox = {"points": [sensitive_point], "has_submit_cmd": True, "has_preview_cmd": False, "has_status_cmd": False, "is_postponed": False}

    monkeypatch.setattr("runner.login_monev", lambda e, p: mock_async_return("secret_jwt_access_token_999"))
    monkeypatch.setattr("runner.get_home_status_with_token", lambda t: mock_async_return({"has_attendance": False, "is_holiday": False, "is_scheduled_off_day": False}))
    monkeypatch.setattr(
        "runner.submit_attendance_with_token",
        lambda *args, **kwargs: mock_async_return({"success": True, "is_conflict": False, "status_code": 201, "message": "Success"})
    )
    monkeypatch.setattr("runner.send_telegram_msg", lambda text, **kwargs: mock_async_return(True))

    await execute_submit_flow(state=state, inbox=inbox)

    all_logs = " ".join(caplog.text.split())
    # Ensure sensitive items are NEVER logged
    assert "SuperSecretPassword123!@#" not in all_logs
    assert "secret_jwt_access_token_999" not in all_logs
    assert sensitive_point not in all_logs
    assert "SecretBotToken" not in all_logs
