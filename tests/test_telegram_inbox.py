import pytest
import httpx
from datetime import datetime, timezone
import config
from telegram_inbox import get_inbox_updates, _parse_message_date_wib

_orig_async_client = httpx.AsyncClient


def test_parse_message_date_wib():
    # 2026-10-05 10:00:00 UTC = 2026-10-05 17:00:00 WIB
    dt = datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)
    ts = int(dt.timestamp())
    assert _parse_message_date_wib(ts) == "2026-10-05"

    # 2026-10-05 18:00:00 UTC = 2026-10-06 01:00:00 WIB (Next day in WIB)
    dt2 = datetime(2026, 10, 5, 18, 0, 0, tzinfo=timezone.utc)
    ts2 = int(dt2.timestamp())
    assert _parse_message_date_wib(ts2) == "2026-10-06"


@pytest.mark.asyncio
async def test_get_inbox_updates_filtering_and_parsing(monkeypatch):
    # Setup mock updates
    target_chat_id = 123456789
    other_chat_id = 999999999
    
    # Message timestamps (2026-10-05 WIB)
    # 10:00 UTC = 17:00 WIB (today)
    ts_today_1 = int(datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    ts_today_2 = int(datetime(2026, 10, 5, 10, 5, 0, tzinfo=timezone.utc).timestamp())
    ts_today_3 = int(datetime(2026, 10, 5, 10, 10, 0, tzinfo=timezone.utc).timestamp())
    ts_today_4 = int(datetime(2026, 10, 5, 10, 15, 0, tzinfo=timezone.utc).timestamp())
    # Yesterday 2026-10-04
    ts_yesterday = int(datetime(2026, 10, 4, 10, 0, 0, tzinfo=timezone.utc).timestamp())

    mock_updates = [
        # 1. Point from yesterday (should be ignored)
        {
            "update_id": 1,
            "message": {
                "date": ts_yesterday,
                "from": {"id": target_chat_id},
                "text": "/poin Poin kemarin",
            },
        },
        # 2. Point from someone else (should be ignored)
        {
            "update_id": 2,
            "message": {
                "date": ts_today_1,
                "from": {"id": other_chat_id},
                "text": "/poin Poin orang lain",
            },
        },
        # 3. Valid point 1 today
        {
            "update_id": 3,
            "message": {
                "date": ts_today_1,
                "from": {"id": target_chat_id},
                "text": "/poin Implementasi endpoint API login",
            },
        },
        # 4. Valid point 2 today
        {
            "update_id": 4,
            "message": {
                "date": ts_today_2,
                "from": {"id": target_chat_id},
                "text": "/poin Debugging unit test runner",
            },
        },
        # 5. /tunda command
        {
            "update_id": 5,
            "message": {
                "date": ts_today_3,
                "from": {"id": target_chat_id},
                "text": "/tunda",
            },
        },
        # 6. /lanjut command (sent after /tunda, so is_postponed should become False)
        {
            "update_id": 6,
            "message": {
                "date": ts_today_4,
                "from": {"id": target_chat_id},
                "text": "/lanjut",
            },
        },
    ]

    class MockTelegramTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            assert "offset" not in str(request.url)
            return httpx.Response(200, json={"ok": True, "result": mock_updates})

    def mock_factory(*args, **kwargs):
        kwargs["transport"] = MockTelegramTransport()
        return _orig_async_client(*args, **kwargs)

    monkeypatch.setattr("telegram_inbox.httpx.AsyncClient", mock_factory)

    inbox = await get_inbox_updates(
        bot_token="test_token",
        target_chat_id=target_chat_id,
        target_date_wib="2026-10-05",
    )

    assert len(inbox["points"]) == 2
    assert inbox["points"][0] == "Implementasi endpoint API login"
    assert inbox["points"][1] == "Debugging unit test runner"
    assert inbox["is_postponed"] is False  # /lanjut won over /tunda
    assert inbox["has_submit_cmd"] is False
    assert inbox["has_preview_cmd"] is False


@pytest.mark.asyncio
async def test_tunda_wins_over_lanjut(monkeypatch):
    target_chat_id = 100
    ts_1 = int(datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    ts_2 = int(datetime(2026, 10, 5, 10, 5, 0, tzinfo=timezone.utc).timestamp())

    mock_updates = [
        {"update_id": 1, "message": {"date": ts_1, "from": {"id": target_chat_id}, "text": "/lanjut"}},
        {"update_id": 2, "message": {"date": ts_2, "from": {"id": target_chat_id}, "text": "/tunda"}},
    ]

    class MockTelegramTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "result": mock_updates})

    monkeypatch.setattr(
        "telegram_inbox.httpx.AsyncClient",
        lambda *args, **kwargs: _orig_async_client(transport=MockTelegramTransport(), **kwargs)
    )

    inbox = await get_inbox_updates(bot_token="test", target_chat_id=target_chat_id, target_date_wib="2026-10-05")
    assert inbox["is_postponed"] is True
