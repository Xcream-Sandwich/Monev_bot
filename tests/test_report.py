import pytest
import json
from report import (
    pad_to_min_length,
    validate_and_pad_report,
    generate_from_points_local,
    select_template_from_store,
    build_daily_report,
    MIN_SECTION_LEN,
    PADDING_AKTIVITAS,
    PADDING_PEMBELAJARAN,
    PADDING_KENDALA,
)
import config


def test_pad_to_min_length():
    short_text = "Mengerjakan bug fix."
    padded = pad_to_min_length(short_text, PADDING_AKTIVITAS, min_length=100)
    assert len(padded) >= 100
    assert padded.startswith(short_text)


def test_validate_and_pad_report():
    raw_report = {
        "aktivitas": "Coding fitur baru.",
        "pembelajaran": "Belajar Python.",
        "kendala": "Tidak ada.",
    }
    validated = validate_and_pad_report(raw_report, "test-source")
    assert len(validated["aktivitas"]) >= 100
    assert len(validated["pembelajaran"]) >= 100
    assert len(validated["kendala"]) >= 100
    assert validated["source"] == "test-source"


def test_generate_from_points_local():
    points = ["Refactoring API auth", "Memperbaiki unit test"]
    res = generate_from_points_local(points)
    assert "Refactoring API auth" in res["aktivitas"]
    assert "Memperbaiki unit test" in res["aktivitas"]
    assert "pembelajaran" in res
    assert "kendala" in res


@pytest.mark.asyncio
async def test_build_daily_report_with_points(monkeypatch):
    # Disable Groq to test local generator fallback
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    
    points = ["Mengembangkan fitur bot telegram", "Testing integrasi SSO"]
    report = await build_daily_report(points=points, day_name="Monday")
    
    assert report["source"] == "poin (Lokal)"
    assert len(report["aktivitas"]) >= MIN_SECTION_LEN
    assert len(report["pembelajaran"]) >= MIN_SECTION_LEN
    assert len(report["kendala"]) >= MIN_SECTION_LEN
    assert "Mengembangkan fitur bot telegram" in report["aktivitas"]


@pytest.mark.asyncio
async def test_build_daily_report_with_templates(tmp_path, monkeypatch):
    # Custom template JSON with Day and Default
    template_data = {
        "default": [
            {
                "aktivitas": "Aktivitas default harian pengerjaan backlog tugas magang secara terencana.",
                "pembelajaran": "Pembelajaran default terkait pemahaman arsitektur sistem dan database.",
                "kendala": "Kendala default dapat diselesaikan melalui koordinasi aktif tim pengembang.",
            }
        ],
        "Monday": [
            {
                "aktivitas": "Aktivitas khusus hari Senin: Sprint planning dan koordinasi awal pekan bersama mentor.",
                "pembelajaran": "Pembelajaran khusus hari Senin: Menentukan prioritas tugas dan estimasi pengerjaan.",
                "kendala": "Tidak ada kendala pada koordinasi hari Senin, seluruh rencana kerja tersusun rapi.",
            }
        ],
        "Tuesday": [
            # Incomplete template entry should be ignored
            {
                "aktivitas": "Incomplete entry",
                "pembelajaran": "Missing kendala",
            }
        ]
    }
    
    template_file = tmp_path / "templates.json"
    template_file.write_text(json.dumps(template_data), encoding="utf-8")
    monkeypatch.setattr(config, "TEMPLATES_FILE", template_file)

    # Monday should pick Monday template
    report_mon = await build_daily_report(points=[], day_name="Monday")
    assert report_mon["source"] == "template (Monday)"
    assert "Senin" in report_mon["aktivitas"]
    assert len(report_mon["aktivitas"]) >= MIN_SECTION_LEN

    # Wednesday (not in templates) should fallback to default
    report_wed = await build_daily_report(points=[], day_name="Wednesday")
    assert report_wed["source"] == "template (default)"
    assert "default" in report_wed["aktivitas"]
    assert len(report_wed["aktivitas"]) >= MIN_SECTION_LEN

    # Tuesday has only incomplete entry, should fallback to default
    report_tue = await build_daily_report(points=[], day_name="Tuesday")
    assert report_tue["source"] == "template (default)"

    # When templates.json is empty, fallback to built-in
    empty_file = tmp_path / "empty_templates.json"
    empty_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "TEMPLATES_FILE", empty_file)

    report_builtin = await build_daily_report(points=[], day_name="Thursday")
    assert report_builtin["source"] == "template (bawaan)"
    assert len(report_builtin["aktivitas"]) >= MIN_SECTION_LEN
