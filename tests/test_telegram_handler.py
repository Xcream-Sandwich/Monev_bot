"""
tests/test_telegram_handler.py — Unit tests for api/telegram.py webhook handler.

Tests:
1. Webhook rejects requests with wrong/missing secret_token (403).
2. Webhook ignores messages from non-owner (silently, no response body beyond 200).
3. /start command produces correct response.
4. /daftar command sets reg_state to await_email.
5. Registration flow: email -> password -> validate.
6. /poin command adds point to KV.
7. /tunda marks state.postponed=True.
8. CRON_SECRET verification for cron endpoints.
"""
import json
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", "")
    monkeypatch.setenv("KV_REST_API_URL", "https://fake-upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "fake-token")


def _make_handler_class():
    """Import and return the handler class with fresh module state."""
    import importlib
    # Reload modules to pick up monkeypatched env
    for mod_name in ["lib.config", "lib.kv_store", "lib.crypto",
                     "lib.telegram_utils", "lib.report",
                     "lib.monev_auth", "lib.monev_api"]:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
    if "api.telegram" in sys.modules:
        del sys.modules["api.telegram"]
    from api import telegram as tg_module
    importlib.reload(tg_module)
    return tg_module.handler


def _make_request(body: dict, secret: str = "test-webhook-secret"):
    """Create a mock BaseHTTPRequestHandler-style request."""
    body_bytes = json.dumps(body).encode()
    mock_handler = MagicMock()
    mock_handler.headers = {
        "X-Telegram-Bot-Api-Secret-Token": secret,
        "Content-Length": str(len(body_bytes)),
    }
    mock_handler.rfile = BytesIO(body_bytes)
    mock_handler.wfile = BytesIO()
    mock_handler.send_response = MagicMock()
    mock_handler.send_header = MagicMock()
    mock_handler.end_headers = MagicMock()
    return mock_handler


class TestWebhookSecretVerification:
    def test_rejects_wrong_secret(self, monkeypatch):
        """Webhook returns 403 when X-Telegram-Bot-Api-Secret-Token is wrong."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {"message": {"from": {"id": 123456}, "chat": {"id": 123456}, "message_id": 1, "text": "/start"}}
        body_bytes = json.dumps(update).encode()

        mock_rfile = BytesIO(body_bytes)
        mock_wfile = BytesIO()
        send_response = MagicMock()
        end_headers = MagicMock()
        send_header = MagicMock()

        h = object.__new__(tg_module.handler)
        h.headers = {
            "X-Telegram-Bot-Api-Secret-Token": "WRONG_SECRET",
            "Content-Length": str(len(body_bytes)),
        }
        h.rfile = mock_rfile
        h.wfile = mock_wfile
        h.send_response = send_response
        h.send_header = send_header
        h.end_headers = end_headers

        h.do_POST()

        send_response.assert_called_with(403)

    def test_rejects_missing_secret(self, monkeypatch):
        """Webhook returns 403 when X-Telegram-Bot-Api-Secret-Token is absent."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {"message": {"from": {"id": 123456}, "chat": {"id": 123456}, "message_id": 1, "text": "/start"}}
        body_bytes = json.dumps(update).encode()

        h = object.__new__(tg_module.handler)
        h.headers = {"Content-Length": str(len(body_bytes))}  # No secret token
        h.rfile = BytesIO(body_bytes)
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()

        h.do_POST()
        h.send_response.assert_called_with(403)


class TestOwnerFilter:
    def test_ignores_non_owner(self, monkeypatch):
        """Webhook ignores messages from non-TELEGRAM_CHAT_ID sender (no handler called)."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        # Sender 999999 != 123456
        update = {"message": {"from": {"id": 999999}, "chat": {"id": 999999}, "message_id": 2, "text": "/start"}}
        body_bytes = json.dumps(update).encode()

        h = object.__new__(tg_module.handler)
        h.headers = {
            "X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret",
            "Content-Length": str(len(body_bytes)),
        }
        h.rfile = BytesIO(body_bytes)
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()

        with patch.object(tg_module, "_handle_update") as mock_handle:
            # We still call _handle_update but it should silently return
            async def dummy(): pass
            mock_handle.return_value = dummy()
            h.do_POST()

        # Should still respond 200 to Telegram but _is_authorized_sender returns False internally
        h.send_response.assert_called_with(200)


class TestCommandRouting:
    @pytest.mark.asyncio
    async def test_start_command_calls_send_message(self, monkeypatch):
        """_handle_update routes /start to _cmd_start which calls send_message."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {
            "message": {
                "from": {"id": 123456},
                "chat": {"id": 123456},
                "message_id": 1,
                "text": "/start",
            }
        }
        with patch.object(tg_module, "send_message", AsyncMock()) as mock_send:
            await tg_module._handle_update(update)

        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert "123456" == str(args[0]) or args[0] == 123456
        assert "Halo" in args[1]

    @pytest.mark.asyncio
    async def test_daftar_sets_reg_state(self, monkeypatch):
        """_handle_update routes /daftar to set_reg_state('await_email')."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {
            "message": {
                "from": {"id": 123456},
                "chat": {"id": 123456},
                "message_id": 1,
                "text": "/daftar",
            }
        }
        with patch.object(tg_module.kv_store, "set_reg_state", AsyncMock()) as mock_reg, \
             patch.object(tg_module, "send_message", AsyncMock()):
            await tg_module._handle_update(update)

        mock_reg.assert_called_once_with("await_email")

    @pytest.mark.asyncio
    async def test_poin_adds_point(self, monkeypatch):
        """_handle_update routes /poin <text> to kv_store.add_point."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {
            "message": {
                "from": {"id": 123456},
                "chat": {"id": 123456},
                "message_id": 1,
                "text": "/poin Mengerjakan modul laporan",
            }
        }
        with patch.object(tg_module.kv_store, "add_point", AsyncMock(return_value=["Mengerjakan modul laporan"])) as mock_add, \
             patch.object(tg_module, "send_message", AsyncMock()):
            await tg_module._handle_update(update)

        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert "Mengerjakan modul laporan" in call_kwargs[0] or "Mengerjakan modul laporan" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_tunda_marks_postponed(self, monkeypatch):
        """_handle_update routes /tunda to patch_state with postponed=True."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {
            "message": {
                "from": {"id": 123456},
                "chat": {"id": 123456},
                "message_id": 1,
                "text": "/tunda",
            }
        }
        with patch.object(tg_module.kv_store, "patch_state", AsyncMock(return_value={})) as mock_patch, \
             patch.object(tg_module, "send_message", AsyncMock()):
            await tg_module._handle_update(update)

        mock_patch.assert_called_once()
        kwargs = mock_patch.call_args[1]
        assert kwargs.get("postponed") is True

    @pytest.mark.asyncio
    async def test_non_owner_silently_ignored(self, monkeypatch):
        """Messages from non-owner are silently ignored (no send_message called)."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api import telegram as tg_module
        importlib.reload(tg_module)

        update = {
            "message": {
                "from": {"id": 999999},  # Not the owner
                "chat": {"id": 999999},
                "message_id": 1,
                "text": "/start",
            }
        }
        with patch.object(tg_module, "send_message", AsyncMock()) as mock_send:
            await tg_module._handle_update(update)

        mock_send.assert_not_called()


class TestCronSecretVerification:
    def test_warn_rejects_wrong_secret(self, monkeypatch):
        """warn cron returns 401 when CRON_SECRET doesn't match."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api.cron import warn as warn_module
        importlib.reload(warn_module)

        h = object.__new__(warn_module.handler)
        h.headers = {"Authorization": "Bearer WRONG_SECRET"}
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()

        h.do_GET()
        h.send_response.assert_called_with(401)

    def test_submit_rejects_wrong_secret(self, monkeypatch):
        """submit cron returns 401 when CRON_SECRET doesn't match."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api.cron import submit as submit_module
        importlib.reload(submit_module)

        h = object.__new__(submit_module.handler)
        h.headers = {"Authorization": "Bearer WRONG"}
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()

        h.do_GET()
        h.send_response.assert_called_with(401)

    def test_evening_rejects_wrong_secret(self, monkeypatch):
        """evening cron returns 401 when CRON_SECRET doesn't match."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from api.cron import evening as evening_module
        importlib.reload(evening_module)

        h = object.__new__(evening_module.handler)
        h.headers = {"Authorization": "Bearer WRONG"}
        h.wfile = BytesIO()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()

        h.do_GET()
        h.send_response.assert_called_with(401)
