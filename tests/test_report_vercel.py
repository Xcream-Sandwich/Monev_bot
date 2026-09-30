"""
tests/test_report_vercel.py — Tests for lib/report.py (Vercel mode).
All external dependencies (KV, Groq) are mocked.
No network connections.
"""
import pytest
from unittest.mock import AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _setup_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("TEMPLATES_JSON", "")
    monkeypatch.setenv("KV_REST_API_URL", "")
    monkeypatch.setenv("KV_REST_API_TOKEN", "")
    monkeypatch.setenv("ENCRYPTION_KEY", "")


class TestPadToMinLength:
    def test_short_text_gets_padded(self):
        import importlib
        from lib import report
        importlib.reload(report)

        result = report.pad_to_min_length("Pendek", report.PADDING_AKTIVITAS, min_length=100)
        assert len(result) >= 100

    def test_already_long_text_unchanged(self):
        import importlib
        from lib import report
        importlib.reload(report)

        long_text = "A" * 150
        result = report.pad_to_min_length(long_text, report.PADDING_AKTIVITAS)
        assert result == long_text

    def test_empty_text_padded(self):
        import importlib
        from lib import report
        importlib.reload(report)

        result = report.pad_to_min_length("", report.PADDING_AKTIVITAS, min_length=100)
        assert len(result) >= 100


class TestValidateAndPadReport:
    def test_all_sections_meet_100_chars(self):
        import importlib
        from lib import report
        importlib.reload(report)

        raw = {"aktivitas": "Kerja", "pembelajaran": "Belajar", "kendala": "Aman"}
        result = report.validate_and_pad_report(raw, "test")
        assert len(result["aktivitas"]) >= 100
        assert len(result["pembelajaran"]) >= 100
        assert len(result["kendala"]) >= 100
        assert result["source"] == "test"

    def test_missing_sections_filled_with_padding(self):
        import importlib
        from lib import report
        importlib.reload(report)

        raw = {}  # All sections missing
        result = report.validate_and_pad_report(raw, "empty")
        assert len(result["aktivitas"]) >= 100
        assert len(result["pembelajaran"]) >= 100
        assert len(result["kendala"]) >= 100


class TestGenerateFromPointsLocal:
    def test_with_points(self):
        import importlib
        from lib import report
        importlib.reload(report)

        points = ["Mengerjakan fitur X", "Testing endpoint Y"]
        result = report.generate_from_points_local(points)
        assert "aktivitas" in result
        assert "Mengerjakan fitur X" in result["aktivitas"]
        assert "Testing endpoint Y" in result["aktivitas"]

    def test_empty_points_returns_fallback(self):
        import importlib
        from lib import report
        importlib.reload(report)

        result = report.generate_from_points_local([])
        assert result == report.BUILTIN_FALLBACK_TEMPLATE

    def test_whitespace_only_points_filtered(self):
        import importlib
        from lib import report
        importlib.reload(report)

        result = report.generate_from_points_local(["  ", "", "   "])
        assert result == report.BUILTIN_FALLBACK_TEMPLATE


class TestSelectTemplateFromStore:
    @pytest.mark.asyncio
    async def test_uses_templates_json_env(self, monkeypatch):
        """When TEMPLATES_JSON is set, uses it without calling KV."""
        _setup_env(monkeypatch)
        import importlib, json
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import report
        importlib.reload(report)

        templates = {
            "default": [{
                "aktivitas": "A" * 110,
                "pembelajaran": "B" * 110,
                "kendala": "C" * 110,
            }]
        }
        monkeypatch.setenv("TEMPLATES_JSON", json.dumps(templates))
        importlib.reload(lib_config)
        importlib.reload(report)

        with patch("lib.kv_store.get_templates", AsyncMock(return_value={})) as mock_kv:
            tmpl, source = await report.select_template_from_store(day_name="Monday")

        # KV should not be called because TEMPLATES_JSON is set
        mock_kv.assert_not_called()
        assert source == "template (default)"

    @pytest.mark.asyncio
    async def test_fallback_to_builtin_when_no_templates(self, monkeypatch):
        """Falls back to BUILTIN_FALLBACK_TEMPLATE when KV and env are both empty."""
        _setup_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import report
        importlib.reload(report)

        with patch("lib.kv_store.get_templates", AsyncMock(return_value={})):
            tmpl, source = await report.select_template_from_store(day_name="Wednesday")

        assert source == "template (bawaan)"
        assert tmpl == report.BUILTIN_FALLBACK_TEMPLATE


class TestBuildDailyReport:
    @pytest.mark.asyncio
    async def test_with_points_uses_local_generator(self, monkeypatch):
        """build_daily_report with points uses local generator (no Groq) when GROQ_API_KEY unset."""
        _setup_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import report
        importlib.reload(report)

        points = ["Implementasi fitur login", "Testing API endpoint"]
        result = await report.build_daily_report(points=points)

        assert len(result["aktivitas"]) >= 100
        assert len(result["pembelajaran"]) >= 100
        assert len(result["kendala"]) >= 100
        assert "Lokal" in result["source"]

    @pytest.mark.asyncio
    async def test_without_points_uses_template(self, monkeypatch):
        """build_daily_report without points falls back to template."""
        _setup_env(monkeypatch)
        import importlib
        from lib import config as lib_config
        importlib.reload(lib_config)
        from lib import report
        importlib.reload(report)

        with patch("lib.kv_store.get_templates", AsyncMock(return_value={})):
            result = await report.build_daily_report(points=None)

        assert "template" in result["source"]
        assert len(result["aktivitas"]) >= 100
