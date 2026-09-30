"""
tests/test_kv_store.py — Unit tests for lib/kv_store.py using mocked HTTP.
All Upstash REST API calls are intercepted with pytest-httpx or manual AsyncMock.
No real network connections are made.
"""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_env(monkeypatch):
    monkeypatch.setenv("KV_REST_API_URL", "https://fake-upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "fake-token")
    monkeypatch.setenv("ENCRYPTION_KEY", "")


@pytest.fixture(autouse=True)
def _reset_lib_config(monkeypatch):
    """Reload lib.config after env changes."""
    _make_env(monkeypatch)


def _mock_response(data):
    """Create a mock httpx.Response."""
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


class TestKvGet:
    @pytest.mark.asyncio
    async def test_returns_parsed_json(self, monkeypatch):
        """kv_get returns parsed JSON value from Upstash response."""
        _make_env(monkeypatch)
        # Reload config so env vars are picked up
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        raw_value = json.dumps(["point1", "point2"])
        mock_resp = _mock_response({"result": raw_value})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await kv_store.kv_get("points:2025-01-01")

        assert result == ["point1", "point2"]

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_key(self, monkeypatch):
        """kv_get returns None when Upstash result is null."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        mock_resp = _mock_response({"result": None})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await kv_store.kv_get("nonexistent")

        assert result is None


class TestKvHighLevelHelpers:
    @pytest.mark.asyncio
    async def test_get_points_empty_default(self, monkeypatch):
        """get_points returns empty list when key doesn't exist."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        with patch.object(kv_store, "kv_get", AsyncMock(return_value=None)):
            result = await kv_store.get_points("2025-01-01")
        assert result == []

    @pytest.mark.asyncio
    async def test_add_point_appends(self, monkeypatch):
        """add_point appends to existing list and calls kv_set."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        existing = ["existing point"]
        with patch.object(kv_store, "kv_get", AsyncMock(return_value=existing)), \
             patch.object(kv_store, "kv_set", AsyncMock()) as mock_set:
            result = await kv_store.add_point("2025-01-01", "new point")

        assert "new point" in result
        assert "existing point" in result
        assert len(result) == 2
        mock_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_state_default(self, monkeypatch):
        """get_state returns default state dict when key doesn't exist."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        with patch.object(kv_store, "kv_get", AsyncMock(return_value=None)):
            state = await kv_store.get_state("2025-01-01")

        assert state["warned"] is False
        assert state["done"] is False
        assert state["attempts"] == 0
        assert state["postponed"] is False

    @pytest.mark.asyncio
    async def test_patch_state_updates_field(self, monkeypatch):
        """patch_state merges kwargs into existing state."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        existing = {"warned": False, "done": False, "attempts": 1, "postponed": False}
        with patch.object(kv_store, "kv_get", AsyncMock(return_value=existing)), \
             patch.object(kv_store, "kv_set", AsyncMock()):
            result = await kv_store.patch_state("2025-01-01", done=True, attempts=2)

        assert result["done"] is True
        assert result["attempts"] == 2
        assert result["warned"] is False  # unchanged

    @pytest.mark.asyncio
    async def test_set_reg_state_with_ttl(self, monkeypatch):
        """set_reg_state calls kv_set with TTL_REG_STATE=300."""
        _make_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import kv_store
        importlib.reload(kv_store)

        with patch.object(kv_store, "kv_set", AsyncMock()) as mock_set:
            await kv_store.set_reg_state("await_email", email="test@example.com")

        mock_set.assert_called_once_with(
            kv_store.KEY_REG_STATE,
            {"step": "await_email", "email": "test@example.com"},
            ex=kv_store.TTL_REG_STATE
        )
