import pytest
import asyncio
from datetime import datetime, time
import config
from state import load_state, save_state
from runner import run_actions, execute_submit_flow


async def mock_async_return(val):
    return val


@pytest.fixture(autouse=True)
def setup_runner_test(tmp_path, monkeypatch):
    test_state = tmp_path / "state.json"
    monkeypatch.setattr(config, "STATE_FILE", test_state)
    monkeypatch.setattr(config, "MONEV_EMAIL", "magang@kemnaker.go.id")
    monkeypatch.setattr(config, "MONEV_PASSWORD", "secret123")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", 123456)
    monkeypatch.setattr(config, "WARN_AFTER", time(17, 15, tzinfo=config.WIB_TZ))
    monkeypatch.setattr(config, "SUBMIT_AFTER", time(17, 45, tzinfo=config.WIB_TZ))
    monkeypatch.setattr(config, "get_today_wib_str", lambda: "2026-10-05")


@pytest.mark.asyncio
async def test_runner_off_day_skips(monkeypatch):
    monkeypatch.setattr(config, "is_off_day", lambda dt=None: True)

    called_login = False
    async def mock_login(*args, **kwargs):
        nonlocal called_login
        called_login = True
        return "token"

    monkeypatch.setattr("runner.login_monev", mock_login)

    await run_actions(mode="run")
    assert called_login is False


@pytest.mark.asyncio
async def test_runner_done_date_skips(monkeypatch):
    monkeypatch.setattr(config, "is_off_day", lambda dt=None: False)
    state = load_state()
    state["done_date"] = "2026-10-05"
    save_state(state)

    called_login = False
    async def mock_login(*args, **kwargs):
        nonlocal called_login
        called_login = True
        return "token"

    monkeypatch.setattr("runner.login_monev", mock_login)

    await run_actions(mode="run")
    assert called_login is False


@pytest.mark.asyncio
async def test_runner_warn_after_not_attended(monkeypatch):
    # Time is 17:20 WIB (after 17:15 WARN_AFTER, before 17:45 SUBMIT_AFTER)
    now_dt = datetime(2026, 10, 5, 17, 20, 0, tzinfo=config.WIB_TZ)
    monkeypatch.setattr(config, "get_now_wib", lambda: now_dt)
    monkeypatch.setattr(config, "is_off_day", lambda dt=None: False)

    async def mock_inbox():
        return {"points": [], "has_submit_cmd": False, "has_preview_cmd": False, "has_status_cmd": False, "is_postponed": False}

    monkeypatch.setattr("runner.get_inbox_updates", mock_inbox)
    monkeypatch.setattr("runner.login_monev", lambda email, pwd: mock_async_return("valid_token"))
    
    monkeypatch.setattr(
        "runner.get_home_status_with_token",
        lambda token: mock_async_return({
            "date": "2026-10-05",
            "has_attendance": False,
            "is_holiday": False,
            "is_scheduled_off_day": False,
            "raw_data": {},
        })
    )

    telegram_messages = []
    async def mock_send(text, **kwargs):
        telegram_messages.append(text)
        return True

    monkeypatch.setattr("runner.send_telegram_msg", mock_send)

    await run_actions(mode="run")

    state = load_state()
    assert state["warned_date"] == "2026-10-05"
    assert state["done_date"] is None
    assert len(telegram_messages) == 1
    assert "Peringatan Presensi" in telegram_messages[0]


@pytest.mark.asyncio
async def test_runner_submit_after_executes_and_marks_done(monkeypatch):
    # Time is 17:50 WIB (after 17:45 SUBMIT_AFTER)
    now_dt = datetime(2026, 10, 5, 17, 50, 0, tzinfo=config.WIB_TZ)
    monkeypatch.setattr(config, "get_now_wib", lambda: now_dt)
    monkeypatch.setattr(config, "is_off_day", lambda dt=None: False)

    async def mock_inbox():
        return {"points": ["Mengerjakan modul A", "Testing fitur B"], "has_submit_cmd": False, "has_preview_cmd": False, "has_status_cmd": False, "is_postponed": False}

    monkeypatch.setattr("runner.get_inbox_updates", mock_inbox)
    monkeypatch.setattr("runner.login_monev", lambda email, pwd: mock_async_return("valid_token"))
    
    monkeypatch.setattr(
        "runner.get_home_status_with_token",
        lambda token: mock_async_return({
            "date": "2026-10-05",
            "has_attendance": False,
            "is_holiday": False,
            "is_scheduled_off_day": False,
            "raw_data": {},
        })
    )

    submit_called = False
    async def mock_submit(token, activity_log, lesson_learned, obstacles, date_str):
        nonlocal submit_called
        submit_called = True
        return {"success": True, "is_conflict": False, "status_code": 201, "message": "OK"}

    monkeypatch.setattr("runner.submit_attendance_with_token", mock_submit)
    monkeypatch.setattr("runner.send_telegram_msg", lambda text, **kwargs: mock_async_return(True))

    await run_actions(mode="run")

    state = load_state()
    assert state["done_date"] == "2026-10-05"
    assert submit_called is True


@pytest.mark.asyncio
async def test_runner_submit_after_with_tunda_skips(monkeypatch):
    now_dt = datetime(2026, 10, 5, 17, 50, 0, tzinfo=config.WIB_TZ)
    monkeypatch.setattr(config, "get_now_wib", lambda: now_dt)
    monkeypatch.setattr(config, "is_off_day", lambda dt=None: False)

    async def mock_inbox():
        return {"points": [], "has_submit_cmd": False, "has_preview_cmd": False, "has_status_cmd": False, "is_postponed": True}

    monkeypatch.setattr("runner.get_inbox_updates", mock_inbox)

    submit_called = False
    async def mock_submit(*args, **kwargs):
        nonlocal submit_called
        submit_called = True
        return {"success": True}

    monkeypatch.setattr("runner.submit_attendance_with_token", mock_submit)

    await run_actions(mode="run")

    state = load_state()
    assert state["done_date"] is None
    assert submit_called is False


@pytest.mark.asyncio
async def test_runner_http_409_conflict_marks_done(monkeypatch):
    state = load_state()
    inbox = {"points": []}

    monkeypatch.setattr("runner.login_monev", lambda e, p: mock_async_return("token"))
    monkeypatch.setattr("runner.get_home_status_with_token", lambda t: mock_async_return({"has_attendance": False, "is_holiday": False, "is_scheduled_off_day": False}))
    monkeypatch.setattr(
        "runner.submit_attendance_with_token",
        lambda *args, **kwargs: mock_async_return({"success": False, "is_conflict": True, "status_code": 409, "message": "Conflict"})
    )
    monkeypatch.setattr("runner.send_telegram_msg", lambda text, **kwargs: mock_async_return(True))

    await execute_submit_flow(state=state, inbox=inbox)
    assert state["done_date"] == "2026-10-05"


@pytest.mark.asyncio
async def test_runner_dry_run_does_not_call_api_submit(monkeypatch):
    state = load_state()
    inbox = {"points": ["Task 1"]}

    monkeypatch.setattr("runner.login_monev", lambda e, p: mock_async_return("token"))
    monkeypatch.setattr("runner.get_home_status_with_token", lambda t: mock_async_return({"has_attendance": False, "is_holiday": False, "is_scheduled_off_day": False}))
    
    submit_called = False
    async def mock_submit(*args, **kwargs):
        nonlocal submit_called
        submit_called = True
        return {"success": True, "status_code": 200, "message": "OK"}

    monkeypatch.setattr("runner.submit_attendance_with_token", mock_submit)
    monkeypatch.setattr("runner.send_telegram_msg", lambda text, **kwargs: mock_async_return(True))

    await execute_submit_flow(state=state, inbox=inbox, is_dry_run=True)
    assert submit_called is False
    assert state["done_date"] is None
