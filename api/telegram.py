"""
api/telegram.py — Vercel Serverless Function: Telegram Webhook Handler.

Security:
- Verifies X-Telegram-Bot-Api-Secret-Token header against TELEGRAM_WEBHOOK_SECRET.
- Ignores messages from any sender other than TELEGRAM_CHAT_ID (no response leak).
- Deletes Telegram messages containing passwords after processing.
- Never logs passwords, tokens, cookies, or report content.

Commands handled:
  /start, /daftar, /batal, /cek, /poin <text>, /lihatpoin,
  /preview, /submit, /auto on|off, /tunda
"""
import asyncio
import json
import sys
import os
import logging
from http.server import BaseHTTPRequestHandler

# Ensure lib/ is importable from api/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import config, kv_store
from lib.crypto import encrypt_str
from lib.monev_auth import login_monev, MonevAuthError
from lib.monev_api import get_home_status, submit_attendance
from lib.report import build_daily_report
from lib.telegram_utils import send_message, delete_message, notify_owner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_authorized_sender(from_id: int | str | None) -> bool:
    """Return True only if sender matches configured TELEGRAM_CHAT_ID."""
    if not config.TELEGRAM_CHAT_ID or from_id is None:
        return False
    return str(from_id) == str(config.TELEGRAM_CHAT_ID)


async def _handle_update(update: dict) -> None:
    """Route a Telegram Update object to the correct command handler."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    from_id = message.get("from", {}).get("id")
    msg_id = message.get("message_id")
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()

    # Security: silently ignore messages from anyone other than configured owner
    if not _is_authorized_sender(from_id):
        return

    if not text:
        return

    # Route command
    if text.startswith("/start"):
        await _cmd_start(chat_id)
    elif text.startswith("/daftar"):
        await _cmd_daftar(chat_id)
    elif text.startswith("/batal"):
        await _cmd_batal(chat_id)
    elif text.startswith("/cek"):
        await _cmd_cek(chat_id)
    elif text.startswith("/poin"):
        await _cmd_poin(chat_id, text)
    elif text.startswith("/lihatpoin"):
        await _cmd_lihatpoin(chat_id)
    elif text.startswith("/preview"):
        await _cmd_preview(chat_id)
    elif text.startswith("/submit"):
        await _cmd_submit(chat_id)
    elif text.startswith("/auto"):
        await _cmd_auto(chat_id, text)
    elif text.startswith("/tunda"):
        await _cmd_tunda(chat_id)
    else:
        # Could be a registration flow response (email or password step)
        await _handle_reg_flow(chat_id, msg_id, text)


# =============================================
# Command Handlers
# =============================================

async def _cmd_start(chat_id):
    await send_message(chat_id,
        "Halo! Saya bot presensi Monev MagangHub.\n\n"
        "Perintah yang tersedia:\n"
        "/daftar — Daftarkan akun Monev\n"
        "/cek — Cek status presensi hari ini\n"
        "/poin &lt;teks&gt; — Tambahkan poin aktivitas\n"
        "/lihatpoin — Lihat poin yang sudah ditambahkan\n"
        "/preview — Pratinjau laporan yang akan dikirim\n"
        "/submit — Kirim laporan sekarang\n"
        "/auto on|off — Aktifkan/nonaktifkan auto-submit\n"
        "/tunda — Tunda auto-submit hari ini\n"
        "/batal — Batalkan proses pendaftaran"
    )


async def _cmd_daftar(chat_id):
    await kv_store.set_reg_state("await_email")
    await send_message(chat_id,
        "Silakan masukkan <b>email</b> akun Monev Anda.\n"
        "(Kirim /batal untuk membatalkan)"
    )


async def _cmd_batal(chat_id):
    await kv_store.clear_reg_state()
    await send_message(chat_id, "Proses dibatalkan.")


async def _cmd_cek(chat_id):
    creds = await kv_store.get_credentials()
    if not creds:
        await send_message(chat_id, "Belum terdaftar. Gunakan /daftar terlebih dahulu.")
        return
    try:
        status = await get_home_status()
        today = config.get_today_wib_str()
        if status["has_attendance"]:
            await send_message(chat_id, f"✅ Presensi <b>{today}</b> sudah tercatat di Monev.")
        elif status["is_holiday"] or status["is_scheduled_off_day"]:
            await send_message(chat_id, f"📅 Hari ini ({today}) adalah hari libur/off. Tidak perlu absen.")
        else:
            state = await kv_store.get_state(today)
            poin_count = len(await kv_store.get_points(today))
            src = "poin" if poin_count > 0 else "template"
            await send_message(chat_id,
                f"⏳ Presensi <b>{today}</b> belum tercatat.\n"
                f"Poin tersimpan: {poin_count}\n"
                f"Sumber laporan: {src}\n"
                f"Auto-submit: {'aktif' if state.get('auto_submit', config.AUTO_SUBMIT) else 'nonaktif'}\n"
                f"Tunda: {'ya' if state.get('postponed') else 'tidak'}"
            )
    except Exception as e:
        await send_message(chat_id, f"❌ Gagal cek status: {type(e).__name__}")


async def _cmd_poin(chat_id, text: str):
    # /poin <text>
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await send_message(chat_id, "Format: /poin &lt;teks aktivitas&gt;\nContoh: /poin Mengerjakan modul laporan")
        return
    point_text = parts[1].strip()
    today = config.get_today_wib_str()
    points = await kv_store.add_point(today, point_text)
    await send_message(chat_id,
        f"✅ Poin ditambahkan. Total poin hari ini: {len(points)}\n"
        f"Gunakan /lihatpoin untuk melihat semua poin."
    )


async def _cmd_lihatpoin(chat_id):
    today = config.get_today_wib_str()
    points = await kv_store.get_points(today)
    if not points:
        await send_message(chat_id, "Belum ada poin untuk hari ini. Gunakan /poin &lt;teks&gt; untuk menambahkan.")
        return
    lines = "\n".join(f"{i+1}. {p}" for i, p in enumerate(points))
    await send_message(chat_id, f"📋 Poin hari ini ({today}):\n{lines}")


async def _cmd_preview(chat_id):
    creds = await kv_store.get_credentials()
    if not creds:
        await send_message(chat_id, "Belum terdaftar. Gunakan /daftar terlebih dahulu.")
        return
    today = config.get_today_wib_str()
    points = await kv_store.get_points(today)
    report = await build_daily_report(points if points else None)
    await send_message(chat_id,
        f"📄 <b>Pratinjau Laporan ({report['source']})</b>\n\n"
        f"<b>Aktivitas:</b>\n{report['aktivitas']}\n\n"
        f"<b>Pembelajaran:</b>\n{report['pembelajaran']}\n\n"
        f"<b>Kendala:</b>\n{report['kendala']}"
    )


async def _cmd_submit(chat_id):
    creds = await kv_store.get_credentials()
    if not creds:
        await send_message(chat_id, "Belum terdaftar. Gunakan /daftar terlebih dahulu.")
        return
    today = config.get_today_wib_str()
    state = await kv_store.get_state(today)

    if state.get("done"):
        await send_message(chat_id, "✅ Presensi hari ini sudah tercatat. Tidak perlu submit ulang.")
        return

    await send_message(chat_id, "⏳ Menyusun dan mengirimkan laporan...")
    try:
        status = await get_home_status()
        if status["has_attendance"]:
            await kv_store.patch_state(today, done=True)
            await send_message(chat_id, "✅ Presensi sudah tercatat di Monev (dicek ulang).")
            return
        if status["is_holiday"] or status["is_scheduled_off_day"]:
            await kv_store.patch_state(today, done=True)
            await send_message(chat_id, "📅 Hari libur/off, tidak perlu absen.")
            return

        points = await kv_store.get_points(today)
        report = await build_daily_report(points if points else None)
        result = await submit_attendance(
            activity_log=report["aktivitas"],
            lesson_learned=report["pembelajaran"],
            obstacles=report["kendala"],
        )

        if result["success"] or result["is_conflict"]:
            await kv_store.patch_state(today, done=True)
            await kv_store.clear_points(today)
            emoji = "✅" if result["success"] else "ℹ️"
            await send_message(chat_id, f"{emoji} {result['message']}\nSumber: {report['source']}")
        else:
            await send_message(chat_id, f"❌ {result['message']}")
    except Exception as e:
        await send_message(chat_id, f"❌ Gagal submit: {type(e).__name__}")


async def _cmd_auto(chat_id, text: str):
    parts = text.split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await send_message(chat_id, "Penggunaan: /auto on atau /auto off")
        return
    enabled = parts[1].lower() == "on"
    # Store preference in credentials dict
    creds = await kv_store.get_credentials()
    if not creds:
        await send_message(chat_id, "Belum terdaftar. Gunakan /daftar terlebih dahulu.")
        return
    creds["auto_submit"] = enabled
    await kv_store.kv_set(kv_store.KEY_CREDENTIALS, creds)
    status_str = "diaktifkan" if enabled else "dinonaktifkan"
    await send_message(chat_id, f"✅ Auto-submit {status_str}.")


async def _cmd_tunda(chat_id):
    today = config.get_today_wib_str()
    await kv_store.patch_state(today, postponed=True)
    await send_message(chat_id,
        f"⏸ Auto-submit hari ini ({today}) ditunda.\n"
        "Gunakan /submit untuk mengirim laporan secara manual."
    )


async def _handle_reg_flow(chat_id, msg_id: int, text: str):
    """Handle multi-step /daftar flow: email -> password."""
    reg_state = await kv_store.get_reg_state()
    if not reg_state:
        return  # No registration in progress

    step = reg_state.get("step")

    if step == "await_email":
        email = text.strip()
        if "@" not in email:
            await send_message(chat_id, "❌ Format email tidak valid. Coba lagi.")
            return
        await kv_store.set_reg_state("await_password", email=email)
        await send_message(chat_id,
            f"Email: <code>{email}</code>\n\n"
            "Sekarang kirimkan <b>password</b> Monev Anda.\n"
            "⚠️ Pesan password akan otomatis dihapus setelah diproses."
        )

    elif step == "await_password":
        password = text.strip()
        email = reg_state.get("email", "")

        # Delete password message immediately
        await delete_message(chat_id, msg_id)

        if not email or not password:
            await send_message(chat_id, "❌ Sesi pendaftaran kedaluwarsa. Mulai ulang dengan /daftar.")
            await kv_store.clear_reg_state()
            return

        await send_message(chat_id, "⏳ Memvalidasi kredensial ke Monev...")
        try:
            # Validate credentials by actually logging in
            token = await login_monev(email, password)
        except MonevAuthError as e:
            await kv_store.clear_reg_state()
            await send_message(chat_id, f"❌ Login gagal: {e}\nGunakan /daftar untuk mencoba lagi.")
            return

        import time as time_module
        enc_password = encrypt_str(password)
        enc_token = encrypt_str(token)
        await kv_store.save_credentials(
            email=email,
            enc_password=enc_password,
            enc_token=enc_token,
            token_ts=int(time_module.time()),
            auto_submit=True,
        )
        await kv_store.clear_reg_state()
        await send_message(chat_id,
            f"✅ <b>Pendaftaran Berhasil!</b>\n\n"
            f"Akun <code>{email}</code> berhasil diverifikasi.\n"
            "Kredensial disimpan terenkripsi di Vercel KV.\n\n"
            "Gunakan /cek untuk cek status, atau /auto on untuk auto-submit."
        )


# =============================================
# Vercel Serverless Handler
# =============================================

class handler(BaseHTTPRequestHandler):
    """Vercel Python serverless handler for Telegram webhook."""

    def log_message(self, format, *args):
        """Suppress default BaseHTTPRequestHandler access logging."""
        pass

    def do_POST(self):
        # --- Security: verify webhook secret ---
        secret_header = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if config.TELEGRAM_WEBHOOK_SECRET and secret_header != config.TELEGRAM_WEBHOOK_SECRET:
            self._respond(403, "Forbidden")
            return

        # --- Read body ---
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            update = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, "Bad Request")
            return

        # --- Process update asynchronously ---
        try:
            asyncio.run(_handle_update(update))
        except Exception as e:
            logger.error("Error handling update: %s", type(e).__name__)

        self._respond(200, "OK")

    def do_GET(self):
        """Health check endpoint."""
        self._respond(200, "Monev Bot webhook is running.")

    def _respond(self, status: int, body: str):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
