"""
api/cron/warn.py — Vercel Cron Job: Warning reminder before auto-submit.

Schedule (vercel.json): 09:00 UTC = 16:00 WIB (default WARN_AFTER)
Security: Verifies Authorization: Bearer <CRON_SECRET> header.

Logic:
1. Check CRON_SECRET.
2. Skip if OFF_DAYS or already done.
3. Login -> check Monev status.
4. If attendance present or holiday: mark done, send confirmation (once).
5. If not yet: send warning message with submit time and how to postpone; mark warned.
"""
import asyncio
import json
import sys
import os
import logging
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib import config, kv_store
from lib.monev_api import get_home_status
from lib.telegram_utils import notify_owner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _verify_cron_secret(headers) -> bool:
    auth = headers.get("Authorization", "")
    return (
        bool(config.CRON_SECRET)
        and auth == f"Bearer {config.CRON_SECRET}"
    )


async def run_warn() -> str:
    """Main warn cron logic. Returns a status string for logging."""
    today = config.get_today_wib_str()

    # Skip off days
    if config.is_off_day():
        return f"SKIP: off day ({today})"

    state = await kv_store.get_state(today)

    # Skip if already done
    if state.get("done"):
        return f"SKIP: done ({today})"

    # Check Monev status
    try:
        status = await get_home_status()
    except Exception as e:
        # No credentials or network error
        logger.warning("Warn cron: gagal cek status Monev: %s", type(e).__name__)
        await notify_owner(
            f"⚠️ <b>Warn Cron</b> — Gagal cek status Monev ({today})\n"
            f"Error: {type(e).__name__}\n"
            "Pastikan akun sudah terdaftar via /daftar."
        )
        return f"ERROR: {type(e).__name__}"

    if status["has_attendance"]:
        await kv_store.patch_state(today, done=True)
        await notify_owner(f"✅ Presensi {today} sudah tercatat di Monev. Auto-submit dilewati.")
        return f"DONE: already attended ({today})"

    if status["is_holiday"] or status["is_scheduled_off_day"]:
        await kv_store.patch_state(today, done=True)
        await notify_owner(f"📅 Hari ini ({today}) libur menurut Monev. Auto-submit dilewati.")
        return f"DONE: holiday ({today})"

    # Not yet attended — send warning
    points = await kv_store.get_points(today)
    src = "poin" if points else "template"
    submit_time = config.SUBMIT_AFTER_STR

    await notify_owner(
        f"⏰ <b>Peringatan Presensi</b> — {today}\n\n"
        f"Presensi Monev belum tercatat.\n"
        f"Sumber laporan: {src} ({len(points)} poin)\n"
        f"Auto-submit dijadwalkan jam {submit_time} WIB.\n\n"
        f"Kirim /submit untuk submit sekarang.\n"
        f"Kirim /tunda untuk menunda auto-submit hari ini."
    )
    await kv_store.patch_state(today, warned=True)
    return f"WARNED ({today})"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _verify_cron_secret(self.headers):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        try:
            result = asyncio.run(run_warn())
            logger.info("warn cron: %s", result)
        except Exception as e:
            logger.error("warn cron error: %s", type(e).__name__)
            result = f"ERROR: {type(e).__name__}"

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "result": result}).encode())

    def log_message(self, format, *args):
        pass
