"""
api/cron/submit.py — Vercel Cron Job: Auto-submit attendance.

Schedule (vercel.json): 10:00 UTC = 17:00 WIB (default SUBMIT_AFTER)
Security: Verifies Authorization: Bearer <CRON_SECRET> header.

Logic:
1. Verify CRON_SECRET.
2. Skip if OFF_DAYS, postponed, done, or attempts >= 3.
3. Re-check Monev status.
4. If not attended: build report from KV points or template -> submit.
5. 200/201 -> mark done, clear points, notify success.
6. 409 -> mark done, notify duplicate.
7. Other -> increment attempts, notify error, do NOT mark done.
"""
import asyncio
import json
import sys
import os
import logging
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib import config, kv_store
from lib.monev_api import get_home_status, submit_attendance
from lib.report import build_daily_report
from lib.telegram_utils import notify_owner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _verify_cron_secret(headers) -> bool:
    auth = headers.get("Authorization", "")
    return bool(config.CRON_SECRET) and auth == f"Bearer {config.CRON_SECRET}"


async def run_submit() -> str:
    """Main auto-submit cron logic. Returns a status string."""
    today = config.get_today_wib_str()

    if config.is_off_day():
        return f"SKIP: off day ({today})"

    state = await kv_store.get_state(today)

    if state.get("done"):
        return f"SKIP: already done ({today})"
    if state.get("postponed"):
        await notify_owner(
            f"⏸ Auto-submit {today} ditunda oleh pengguna (/tunda). Gunakan /submit untuk submit manual."
        )
        return f"SKIP: postponed ({today})"
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        await notify_owner(
            f"⛔ Auto-submit {today} berhenti — sudah {MAX_ATTEMPTS}x percobaan gagal. "
            "Gunakan /submit untuk submit manual."
        )
        return f"SKIP: max attempts ({today})"

    # Check auto_submit preference
    creds = await kv_store.get_credentials()
    if creds and not creds.get("auto_submit", config.AUTO_SUBMIT):
        return f"SKIP: auto_submit disabled ({today})"

    # Check current status
    try:
        status = await get_home_status()
    except Exception as e:
        logger.warning("submit cron: gagal cek status: %s", type(e).__name__)
        await kv_store.patch_state(today, attempts=state.get("attempts", 0) + 1)
        await notify_owner(
            f"❌ Auto-submit {today} — Gagal cek status Monev: {type(e).__name__}\n"
            "Akan dicoba ulang jika masih ada jadwal cron, atau gunakan /submit."
        )
        return f"ERROR: status check failed ({today})"

    if status["has_attendance"]:
        await kv_store.patch_state(today, done=True)
        await notify_owner(f"✅ Presensi {today} sudah tercatat di Monev. Auto-submit dilewati.")
        return f"DONE: already attended ({today})"

    if status["is_holiday"] or status["is_scheduled_off_day"]:
        await kv_store.patch_state(today, done=True)
        await notify_owner(f"📅 Hari ini ({today}) libur menurut Monev. Auto-submit dilewati.")
        return f"DONE: holiday ({today})"

    # Build and submit report
    try:
        points = await kv_store.get_points(today)
        report = await build_daily_report(points if points else None)
        result = await submit_attendance(
            activity_log=report["aktivitas"],
            lesson_learned=report["pembelajaran"],
            obstacles=report["kendala"],
        )
    except Exception as e:
        logger.warning("submit cron: gagal susun/kirim laporan: %s", type(e).__name__)
        new_attempts = state.get("attempts", 0) + 1
        await kv_store.patch_state(today, attempts=new_attempts)
        await notify_owner(
            f"❌ Auto-submit {today} gagal (percobaan {new_attempts}/{MAX_ATTEMPTS})\n"
            f"Error: {type(e).__name__}\n"
            "Gunakan /submit untuk mencoba manual."
        )
        return f"ERROR: submit exception ({today})"

    if result["success"]:
        await kv_store.patch_state(today, done=True)
        await kv_store.clear_points(today)
        await notify_owner(
            f"✅ Auto-submit berhasil! ({today})\n"
            f"Sumber: {report['source']}\n"
            f"{result['message']}"
        )
        return f"SUCCESS ({today})"
    elif result["is_conflict"]:
        await kv_store.patch_state(today, done=True)
        await kv_store.clear_points(today)
        await notify_owner(f"ℹ️ Presensi {today} sudah ada di Monev (HTTP 409). Ditandai selesai.")
        return f"CONFLICT (409) ({today})"
    else:
        new_attempts = state.get("attempts", 0) + 1
        await kv_store.patch_state(today, attempts=new_attempts)
        await notify_owner(
            f"❌ Auto-submit {today} gagal (percobaan {new_attempts}/{MAX_ATTEMPTS})\n"
            f"{result['message']}\n"
            "Gunakan /submit untuk mencoba manual."
        )
        return f"FAIL: {result['status_code']} ({today})"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _verify_cron_secret(self.headers):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        try:
            result = asyncio.run(run_submit())
            logger.info("submit cron: %s", result)
        except Exception as e:
            logger.error("submit cron error: %s", type(e).__name__)
            result = f"ERROR: {type(e).__name__}"

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "result": result}).encode())

    def log_message(self, format, *args):
        pass
