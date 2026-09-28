import logging
from telegram.ext import ContextTypes
from config import (
    get_today_wib_str,
    is_off_day,
    AUTO_SUBMIT_TIME_STR,
)
from storage import (
    get_all_users,
    get_daily_points,
    clear_daily_points,
    get_skip_date,
    get_auto_done_date,
    set_auto_done_date,
    get_evening_done_date,
    set_evening_done_date,
    record_submit_history,
)
from report import build_daily_report
from monev_api import get_home_status, submit_attendance_and_log

logger = logging.getLogger(__name__)


async def warn_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Warning job executed at WARN_TIME (default 16:00 WIB).
    Checks status and warns user if attendance is not yet submitted.
    """
    today_str = get_today_wib_str()
    if is_off_day():
        logger.info(f"[Warn Job] Hari ini {today_str} adalah hari libur (OFF_DAYS). Job dilewati.")
        return

    users = get_all_users()
    for user_id_str, user_data in users.items():
        try:
            telegram_id = int(user_id_str)
            if not user_data.get("auto_submit_enabled"):
                continue

            # Check if skipped or already done
            if get_skip_date(telegram_id) == today_str:
                logger.info(f"[Warn Job] User {telegram_id} telah menunda (/tunda) untuk hari ini.")
                continue

            if get_auto_done_date(telegram_id) == today_str:
                logger.info(f"[Warn Job] User {telegram_id} sudah menyelesaikan auto-submit hari ini.")
                continue

            # Check status on Monev API
            status = await get_home_status(telegram_id)
            if status["has_attendance"] or status["is_holiday"] or status["is_scheduled_off_day"]:
                set_auto_done_date(telegram_id, today_str)
                continue

            # User has not attended yet
            points = get_daily_points(telegram_id, today_str)
            if points:
                source_desc = f"Poin kegiatan hari ini ({len(points)} poin)"
            else:
                source_desc = "Template laporan (belum ada poin kegiatan)"

            msg = (
                "⚠️ *Peringatan Presensi Monev MagangHub*\n\n"
                f"Halo! Kamu belum melakukan presensi Monev untuk hari ini (`{today_str}`).\n"
                f"Sistem akan melakukan auto-submit pada pukul *{AUTO_SUBMIT_TIME_STR} WIB*.\n\n"
                f"📋 *Rencana Sumber Laporan:* {source_desc}\n\n"
                "• Ingin membatalkan auto-submit hari ini? Ketik /tunda\n"
                "• Ingin mengirim laporan sekarang? Ketik /submit\n"
                "• Ingin menambah poin kegiatan? Ketik `/poin <kegiatan>`"
            )
            await context.bot.send_message(chat_id=telegram_id, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"[Warn Job] Error memproses user {user_id_str}: {e}")


async def auto_submit_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Auto-submit job executed at AUTO_SUBMIT_TIME (default 17:00 WIB).
    Re-checks status, generates report, and submits to Monev API.
    """
    today_str = get_today_wib_str()
    if is_off_day():
        logger.info(f"[Auto-Submit Job] Hari ini {today_str} adalah hari libur (OFF_DAYS). Job dilewati.")
        return

    users = get_all_users()
    for user_id_str, user_data in users.items():
        try:
            telegram_id = int(user_id_str)
            if not user_data.get("auto_submit_enabled"):
                continue

            # Check if skipped or already done
            if get_skip_date(telegram_id) == today_str:
                logger.info(f"[Auto-Submit Job] User {telegram_id} menunda auto-submit untuk hari ini.")
                continue

            if get_auto_done_date(telegram_id) == today_str:
                logger.info(f"[Auto-Submit Job] User {telegram_id} sudah selesai auto-submit hari ini.")
                continue

            # Re-check status on Monev API
            status = await get_home_status(telegram_id)
            if status["has_attendance"] or status["is_holiday"] or status["is_scheduled_off_day"]:
                set_auto_done_date(telegram_id, today_str)
                continue

            # Build report
            points = get_daily_points(telegram_id, today_str)
            report = await build_daily_report(points=points)

            # Submit report
            result = await submit_attendance_and_log(
                telegram_id=telegram_id,
                activity_log=report["aktivitas"],
                lesson_learned=report["pembelajaran"],
                obstacles=report["kendala"],
                date_str=today_str,
            )

            if result["success"]:
                set_auto_done_date(telegram_id, today_str)
                clear_daily_points(telegram_id, today_str)
                record_submit_history(
                    telegram_id=telegram_id,
                    date_str=today_str,
                    source=f"auto: {report['source']}",
                    http_code=result["status_code"],
                    result="success",
                    detail="Auto-submit berhasil.",
                )
                success_msg = (
                    "✅ *Auto-Submit Presensi Monev Berhasil!*\n\n"
                    f"📅 Tanggal: `{today_str}`\n"
                    f"🏷️ Sumber: *{report['source']}*\n\n"
                    f"📝 *Aktivitas:*\n{report['aktivitas']}\n\n"
                    f"💡 *Pembelajaran:*\n{report['pembelajaran']}\n\n"
                    f"🚧 *Kendala:*\n{report['kendala']}"
                )
                await context.bot.send_message(chat_id=telegram_id, text=success_msg, parse_mode="Markdown")

            elif result["is_conflict"]:
                set_auto_done_date(telegram_id, today_str)
                record_submit_history(
                    telegram_id=telegram_id,
                    date_str=today_str,
                    source=f"auto: {report['source']}",
                    http_code=409,
                    result="conflict",
                    detail="Presensi sudah ada di server.",
                )
                conflict_msg = (
                    f"ℹ️ Presensi Monev hari ini (`{today_str}`) sudah tercatat di server (HTTP 409).\n"
                    "Auto-submit ditandai selesai."
                )
                await context.bot.send_message(chat_id=telegram_id, text=conflict_msg, parse_mode="Markdown")

            else:
                record_submit_history(
                    telegram_id=telegram_id,
                    date_str=today_str,
                    source=f"auto: {report['source']}",
                    http_code=result["status_code"],
                    result="failed",
                    detail=result["message"],
                )
                fail_msg = (
                    "❌ *Auto-Submit Presensi Monev Gagal!*\n\n"
                    f"Kode Status: `HTTP {result['status_code']}`\n"
                    f"Detail: {result['message']}\n\n"
                    "Silakan periksa koneksi dan coba submit manual dengan perintah /submit."
                )
                await context.bot.send_message(chat_id=telegram_id, text=fail_msg, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"[Auto-Submit Job] Gagal mengeksekusi auto-submit untuk user {user_id_str}: {e}")


async def evening_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Evening reminder job executed at 19:00 WIB.
    Checks attendance status, confirms if done or reminds user if still missing.
    """
    today_str = get_today_wib_str()
    if is_off_day():
        logger.info(f"[Evening Job] Hari ini {today_str} adalah hari libur (OFF_DAYS). Job dilewati.")
        return

    users = get_all_users()
    for user_id_str in users.keys():
        try:
            telegram_id = int(user_id_str)
            if get_evening_done_date(telegram_id) == today_str:
                continue

            status = await get_home_status(telegram_id)
            if status["has_attendance"] or status["is_holiday"] or status["is_scheduled_off_day"]:
                set_evening_done_date(telegram_id, today_str)
                confirm_msg = f"🌙 *Info Presensi Malam:* Presensi Monev hari ini (`{today_str}`) sudah lengkap / hari libur. Selamat beristirahat!"
                await context.bot.send_message(chat_id=telegram_id, text=confirm_msg, parse_mode="Markdown")
            else:
                reminder_msg = (
                    "🌙 *Pengingat Presensi Malam*\n\n"
                    f"Kamu belum mengisi presensi Monev untuk hari ini (`{today_str}`).\n"
                    "Jangan lupa mengisi sebelum pergantian hari dengan perintah /submit."
                )
                await context.bot.send_message(chat_id=telegram_id, text=reminder_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"[Evening Job] Error memproses reminder malam user {user_id_str}: {e}")
