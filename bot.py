import logging
from datetime import time
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    WARN_TIME,
    AUTO_SUBMIT_TIME,
    WARN_TIME_STR,
    AUTO_SUBMIT_TIME_STR,
    OFF_DAYS_STR,
    WIB_TZ,
    get_today_wib_str,
    is_user_allowed,
)
from crypto import ENCRYPTION_KEY
from storage import (
    get_user,
    save_user,
    delete_user,
    set_user_auto_submit,
    add_daily_point,
    get_daily_points,
    clear_daily_points,
    set_skip_date,
    record_submit_history,
)
from report import build_daily_report
from monev_auth import login_monev, MonevAuthError
from monev_api import get_home_status, submit_attendance_and_log
from jobs import warn_job, auto_submit_job, evening_reminder_job

# Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation States for /daftar
WAIT_EMAIL, WAIT_PASSWORD = range(2)


# ==========================================
# Decorator / Helper for Authorization
# ==========================================

def authorized_only(func):
    """Ensure user is whitelisted and registered (if required)."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.effective_message:
            return
        user_id = update.effective_user.id
        if not is_user_allowed(user_id):
            await update.effective_message.reply_text("⛔ Maaf, Anda tidak memiliki izin untuk menggunakan bot ini.")
            return
        return await func(update, context)
    return wrapper


# ==========================================
# Command Handlers
# ==========================================

@authorized_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "🤖 *Selamat Datang di Monev Attendance Bot!*\n\n"
        "Bot personal untuk otomatisasi presensi dan laporan harian magang di portal *Monev MagangHub Kemnaker*.\n\n"
        "📌 *Daftar Perintah:*\n"
        "• /daftar - Hubungkan akun Monev Kemnaker\n"
        "• /batal - Hapus akun & sesi Monev dari bot\n"
        "• /cek - Cek status presensi hari ini\n"
        "• `/poin <teks>` - Catat satu butir kegiatan hari ini\n"
        "• /lihatpoin - Lihat daftar poin kegiatan hari ini\n"
        "• /preview - Pratinjau draf laporan 3 bagian hari ini\n"
        "• /submit - Susun & kirim laporan ke Monev sekarang\n"
        "• `/auto on` | `/auto off` | `/auto` - Atur status auto-submit\n"
        "• /tunda - Batalkan auto-submit khusus untuk hari ini\n\n"
        f"⚙️ *Konfigurasi Jadwal:*\n"
        f"• Peringatan: *{WARN_TIME_STR} WIB*\n"
        f"• Auto-Submit: *{AUTO_SUBMIT_TIME_STR} WIB*\n"
        f"• Hari Libur: *{OFF_DAYS_STR}*"
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown")


# --- Conversation /daftar ---

@authorized_only
async def cmd_daftar_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "📝 *Pendaftaran Akun Monev MagangHub*\n\n"
        "Silakan masukkan *email* akun Kemnaker / MagangHub Anda:\n"
        "_(Ketik /cancel untuk membatalkan)_",
        parse_mode="Markdown",
    )
    return WAIT_EMAIL


async def handle_daftar_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.effective_message.text.strip()
    if "@" not in email:
        await update.effective_message.reply_text("Format email tidak valid. Silakan masukkan email yang benar:")
        return WAIT_EMAIL

    context.user_data["monev_email"] = email
    await update.effective_message.reply_text(
        f"Email tercatat: `{email}`\n\n"
        "Sekarang, masukkan *password* akun Monev Anda.\n\n"
        "🔒 *Keamanan:* Bot akan mencoba menghapus pesan password Anda secara otomatis setelah diterima. Kredensial akan disimpan dalam bentuk terenkripsi.",
        parse_mode="Markdown",
    )
    return WAIT_PASSWORD


async def handle_daftar_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.effective_message.text
    email = context.user_data.get("monev_email", "")
    user_id = update.effective_user.id

    # Best-effort delete password message from Telegram chat history
    try:
        await update.effective_message.delete()
    except Exception:
        pass

    status_msg = await update.effective_chat.send_message("⏳ Sedang memvalidasi login ke SSO Kemnaker...")

    try:
        # Validate login directly against SSO
        token = await login_monev(email, password)
        
        # Save user to encrypted store
        save_user(
            telegram_id=user_id,
            email=email,
            password=password,
            auto_submit_enabled=False,
            cached_token=token,
        )
        
        await status_msg.edit_text(
            "✅ *Pendaftaran Berhasil!*\n\n"
            f"Akun `{email}` berhasil diverifikasi dan terhubung ke Monev MagangHub.\n"
            "Kredensial tersimpan dalam bentuk terenkripsi secara lokal.\n\n"
            "💡 *Tips:* Ingat untuk menghapus pesan password Anda dari riwayat chat jika masih terlihat.\n"
            "Gunakan /cek untuk memeriksa status presensi hari ini, atau `/auto on` untuk menyalakan pengiriman otomatis.",
            parse_mode="Markdown",
        )
    except MonevAuthError as e:
        await status_msg.edit_text(
            f"❌ *Pendaftaran Gagal!*\n\n{str(e)}\n\n"
            "Pastikan email dan password sudah benar, lalu ulangi dengan perintah /daftar.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Unexpected error during /daftar: {e}")
        await status_msg.edit_text(
            "❌ Terjadi kesalahan saat proses pendaftaran. Pastikan konfigurasi ENCRYPTION_KEY sudah terisi dengan benar.",
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cmd_cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("❌ Proses pendaftaran dibatalkan.")
    return ConversationHandler.END


# --- End /daftar conversation ---


@authorized_only
async def cmd_batal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if delete_user(user_id):
        await update.effective_message.reply_text("🗑️ Akun Monev kamu berhasil dihapus dari sistem bot.")
    else:
        await update.effective_message.reply_text("Kamu belum terdaftar di bot ini. Gunakan /daftar untuk mendaftar.")


@authorized_only
async def cmd_cek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    wait_msg = await update.effective_message.reply_text("🔍 Sedang memeriksa status presensi ke Monev API...")
    try:
        status = await get_home_status(user_id)
        has_att = "✅ Sudah Presensi" if status["has_attendance"] else "❌ Belum Presensi"
        is_hol = "Ya" if status["is_holiday"] else "Tidak"
        is_off = "Ya" if status["is_scheduled_off_day"] else "Tidak"

        today_points = get_daily_points(user_id, status["date"])

        msg = (
            "📊 *Status Presensi Monev Hari Ini*\n\n"
            f"📅 Tanggal: `{status['date']}`\n"
            f"📌 Status: *{has_att}*\n"
            f"🏖️ Hari Libur Nasional: {is_hol}\n"
            f"🗓️ Hari Libur Terjadwal: {is_off}\n"
            f"📝 Poin Kegiatan Tercatat: {len(today_points)} butir\n"
        )
        await wait_msg.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error checking status for user {user_id}: {e}")
        await wait_msg.edit_text(f"❌ Gagal mengambil status presensi: {str(e)}")


@authorized_only
async def cmd_poin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        await update.effective_message.reply_text(
            "Format: `/poin <uraian kegiatan>`\n"
            "Contoh: `/poin Mengerjakan modul autentikasi JWT dan unit testing`",
            parse_mode="Markdown",
        )
        return

    today_str = get_today_wib_str()
    points = add_daily_point(user_id, text, today_str)

    msg = (
        f"✅ Poin kegiatan berhasil ditambahkan untuk hari ini (`{today_str}`).\n\n"
        f"📋 *Daftar Poin Saat Ini ({len(points)} butir):*\n"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(points))
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown")


@authorized_only
async def cmd_lihatpoin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    today_str = get_today_wib_str()
    points = get_daily_points(user_id, today_str)

    if not points:
        await update.effective_message.reply_text(
            f"Belum ada poin kegiatan yang dicatat untuk hari ini (`{today_str}`).\n"
            "Gunakan `/poin <kegiatan>` untuk menambahkan.",
            parse_mode="Markdown",
        )
        return

    msg = (
        f"📋 *Daftar Poin Kegiatan Hari Ini ({today_str}):*\n\n"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(points))
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown")


@authorized_only
async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    wait_msg = await update.effective_message.reply_text("⚙️ Sedang menyusun draf laporan...")
    today_str = get_today_wib_str()
    points = get_daily_points(user_id, today_str)

    try:
        report = await build_daily_report(points=points)
        msg = (
            "📋 *Pratinjau Draf Laporan Presensi*\n\n"
            f"📅 Tanggal: `{today_str}`\n"
            f"🏷️ Sumber: *{report['source']}*\n\n"
            f"📝 *Uraian Aktivitas* ({len(report['aktivitas'])} karakter):\n"
            f"{report['aktivitas']}\n\n"
            f"💡 *Pembelajaran* ({len(report['pembelajaran'])} karakter):\n"
            f"{report['pembelajaran']}\n\n"
            f"🚧 *Kendala* ({len(report['kendala'])} karakter):\n"
            f"{report['kendala']}\n\n"
            "_Ketik /submit jika ingin mengirim laporan ini sekarang._"
        )
        await wait_msg.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error previewing report for user {user_id}: {e}")
        await wait_msg.edit_text(f"❌ Gagal menyusun draf laporan: {str(e)}")


@authorized_only
async def cmd_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    today_str = get_today_wib_str()
    wait_msg = await update.effective_message.reply_text("🚀 Sedang menyusun laporan dan mengirim ke portal Monev...")

    try:
        points = get_daily_points(user_id, today_str)
        report = await build_daily_report(points=points)

        result = await submit_attendance_and_log(
            telegram_id=user_id,
            activity_log=report["aktivitas"],
            lesson_learned=report["pembelajaran"],
            obstacles=report["kendala"],
            date_str=today_str,
        )

        if result["success"]:
            clear_daily_points(user_id, today_str)
            record_submit_history(
                telegram_id=user_id,
                date_str=today_str,
                source=f"manual: {report['source']}",
                http_code=result["status_code"],
                result="success",
                detail="Submit manual berhasil.",
            )
            success_msg = (
                "✅ *Presensi Monev Berhasil Dikirim!*\n\n"
                f"📅 Tanggal: `{today_str}`\n"
                f"🏷️ Sumber: *{report['source']}*\n\n"
                f"📝 *Aktivitas:*\n{report['aktivitas']}\n\n"
                f"💡 *Pembelajaran:*\n{report['pembelajaran']}\n\n"
                f"🚧 *Kendala:*\n{report['kendala']}"
            )
            await wait_msg.edit_text(success_msg, parse_mode="Markdown")

        elif result["is_conflict"]:
            record_submit_history(
                telegram_id=user_id,
                date_str=today_str,
                source=f"manual: {report['source']}",
                http_code=409,
                result="conflict",
                detail="Sudah pernah disubmit sebelumnya.",
            )
            await wait_msg.edit_text(
                f"ℹ️ Presensi Monev untuk hari ini (`{today_str}`) sudah pernah tercatat di server (HTTP 409).",
                parse_mode="Markdown",
            )

        else:
            record_submit_history(
                telegram_id=user_id,
                date_str=today_str,
                source=f"manual: {report['source']}",
                http_code=result["status_code"],
                result="failed",
                detail=result["message"],
            )
            await wait_msg.edit_text(
                "❌ *Pengiriman Presensi Gagal!*\n\n"
                f"Kode Status: `HTTP {result['status_code']}`\n"
                f"Pesan: {result['message']}",
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.error(f"Error executing manual submit for user {user_id}: {e}")
        await wait_msg.edit_text(f"❌ Terjadi kesalahan saat pengiriman: {str(e)}")


@authorized_only
async def cmd_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    arg = context.args[0].lower() if context.args else ""

    if arg == "on":
        set_user_auto_submit(user_id, True)
        await update.effective_message.reply_text(
            f"✅ *Auto-Submit Berhasil Diaktifkan!*\n\n"
            f"• Peringatan akan dikirim pada: *{WARN_TIME_STR} WIB*\n"
            f"• Auto-Submit dieksekusi pada: *{AUTO_SUBMIT_TIME_STR} WIB*\n"
            f"• Hari Libur: *{OFF_DAYS_STR}*",
            parse_mode="Markdown",
        )
    elif arg == "off":
        set_user_auto_submit(user_id, False)
        await update.effective_message.reply_text("⏸️ *Auto-Submit Dinonaktifkan.*", parse_mode="Markdown")
    else:
        current_status = "🟢 AKTIF" if user.get("auto_submit_enabled") else "🔴 NONAKTIF"
        await update.effective_message.reply_text(
            f"⚙️ *Status Fitur Auto-Submit:* {current_status}\n\n"
            f"• Jadwal Peringatan: *{WARN_TIME_STR} WIB*\n"
            f"• Jadwal Auto-Submit: *{AUTO_SUBMIT_TIME_STR} WIB*\n"
            f"• Hari Libur: *{OFF_DAYS_STR}*\n\n"
            "Gunakan `/auto on` untuk mengaktifkan atau `/auto off` untuk menonaktifkan.",
            parse_mode="Markdown",
        )


@authorized_only
async def cmd_tunda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Kamu belum mendaftarkan akun Monev. Gunakan /daftar terlebih dahulu.")
        return

    today_str = get_today_wib_str()
    set_skip_date(user_id, today_str)

    await update.effective_message.reply_text(
        f"⏸️ Auto-submit untuk hari ini (`{today_str}`) berhasil *ditunda*.\n"
        "Bot tidak akan melakukan pengiriman otomatis hari ini. Kamu tetap bisa submit manual kapan saja dengan /submit.",
        parse_mode="Markdown",
    )


# ==========================================
# Main Bot Initialization
# ==========================================

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN belum diatur di file .env!")
        return

    if not ENCRYPTION_KEY:
        print("ERROR: ENCRYPTION_KEY belum diatur di file .env!")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler for /daftar
    daftar_conv = ConversationHandler(
        entry_points=[CommandHandler("daftar", cmd_daftar_start)],
        states={
            WAIT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_daftar_email)],
            WAIT_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_daftar_password)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel_conversation)],
    )

    # Register Handlers
    application.add_handler(daftar_conv)
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("batal", cmd_batal))
    application.add_handler(CommandHandler("cek", cmd_cek))
    application.add_handler(CommandHandler("poin", cmd_poin))
    application.add_handler(CommandHandler("lihatpoin", cmd_lihatpoin))
    application.add_handler(CommandHandler("preview", cmd_preview))
    application.add_handler(CommandHandler("submit", cmd_submit))
    application.add_handler(CommandHandler("auto", cmd_auto))
    application.add_handler(CommandHandler("tunda", cmd_tunda))

    # Register Scheduled Jobs
    job_queue = application.job_queue
    if job_queue:
        # Warning job at WARN_TIME
        job_queue.run_daily(warn_job, time=WARN_TIME)
        # Auto submit job at AUTO_SUBMIT_TIME
        job_queue.run_daily(auto_submit_job, time=AUTO_SUBMIT_TIME)
        # Evening reminder job at 19:00 WIB
        job_queue.run_daily(evening_reminder_job, time=time(19, 0, tzinfo=WIB_TZ))
        logger.info("Semua background jobs (Warn, Auto-Submit, Evening) berhasil didaftarkan.")
    else:
        logger.warning("JobQueue tidak tersedia. Pastikan python-telegram-bot[job-queue] terinstal.")

    logger.info("Monev Attendance Bot siap berjalan (polling mode)...")
    application.run_polling()


if __name__ == "__main__":
    main()
