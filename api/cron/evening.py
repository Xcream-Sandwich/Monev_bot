"""
api/cron/evening.py — Vercel Cron Job: Evening status reminder (19:00 WIB / 12:00 UTC).

Schedule (vercel.json): 12:00 UTC = 19:00 WIB
Security: Verifies Authorization: Bearer <CRON_SECRET>.

Logic:
- If off day or done: send brief confirmation (once) and exit.
- If not done: remind user to submit manually with status info.
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
    return bool(config.CRON_SECRET) and auth == f"Bearer {config.CRON_SECRET}"


async def run_evening() -> str:
    today = config.get_today_wib_str()

    if config.is_off_day():
        return f"SKIP: off day ({today})"

    state = await kv_store.get_state(today)

    if state.get("done"):
        await notify_owner(f"✅ Pengingat malam: Presensi {today} sudah tercatat. Selamat beristirahat!")
        return f"CONFIRMED done ({today})"

    # Check actual Monev status
    try:
        status = await get_home_status()
    except Exception as e:
        logger.warning("evening cron: gagal cek status: %s", type(e).__name__)
        await notify_owner(
            f"⚠️ <b>Pengingat Malam</b> — {today}\n"
            "Gagal cek status Monev. Pastikan akun terdaftar.\n"
            "Gunakan /submit untuk submit manual."
        )
        return f"ERROR: {type(e).__name__}"

    if status["has_attendance"]:
        await kv_store.patch_state(today, done=True)
        await notify_owner(f"✅ Pengingat malam: Presensi {today} sudah tercatat. Selamat beristirahat!")
        return f"DONE: attended ({today})"

    if status["is_holiday"] or status["is_scheduled_off_day"]:
        await kv_store.patch_state(today, done=True)
        await notify_owner(f"📅 Pengingat malam: Hari ini ({today}) libur. Tidak perlu absen.")
        return f"DONE: holiday ({today})"

    points = await kv_store.get_points(today)
    src = "poin" if points else "template"
    await notify_owner(
        f"🌙 <b>Pengingat Malam</b> — {today}\n\n"
        f"Presensi Monev belum tercatat!\n"
        f"Poin tersimpan: {len(points)} ({src})\n\n"
        "Gunakan /submit untuk kirim laporan sekarang."
    )
    return f"REMINDED ({today})"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _verify_cron_secret(self.headers):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        try:
            result = asyncio.run(run_evening())
            logger.info("evening cron: %s", result)
        except Exception as e:
            logger.error("evening cron error: %s", type(e).__name__)
            result = f"ERROR: {type(e).__name__}"

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "result": result}).encode())

    def log_message(self, format, *args):
        pass
