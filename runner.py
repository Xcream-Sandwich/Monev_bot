import argparse
import asyncio
import logging
import sys
import config
from state import load_state, save_state
from telegram_inbox import get_inbox_updates, send_telegram_msg
from report import build_daily_report
from monev_auth import login_monev, MonevAuthError
from monev_api import (
    get_home_status_with_token,
    submit_attendance_with_token,
)

# Configure clean logging (NEVER log sensitive strings or payload contents)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("monev_runner")


async def execute_submit_flow(
    state: dict,
    inbox: dict,
    is_dry_run: bool = False,
    is_manual: bool = False,
) -> None:
    """Execute Monev submission with status check, report generation, and error handling."""
    today_str = config.get_today_wib_str()
    logger.info("Memulai alur submit presensi...")

    try:
        # Step: Login
        token = await login_monev(config.MONEV_EMAIL, config.MONEV_PASSWORD)
        logger.info("[Auth] Login SSO Berhasil.")

        # Step: Double check status on Monev
        status = await get_home_status_with_token(token)
        if status["has_attendance"] or status["is_holiday"] or status["is_scheduled_off_day"]:
            state["done_date"] = today_str
            save_state(state)
            logger.info("Presensi sudah tercatat di Monev / hari libur. Menandai selesai.")
            if is_manual:
                await send_telegram_msg(
                    f"ℹ️ Status Presensi Hari Ini (`{today_str}`): Sudah tercatat di server / hari libur."
                )
            return

        # Step: Build report
        report = await build_daily_report(points=inbox.get("points", []))

        # Handle Dry Run
        if is_dry_run:
            logger.info("[Dry Run] Mode simulasi aktif. Tidak mengirim POST submit.")
            dry_msg = (
                "🧪 *[DRY RUN] Simulasi Laporan Presensi Monev*\n\n"
                f"📅 Tanggal: `{today_str}`\n"
                f"🏷️ Sumber: *{report['source']}*\n\n"
                f"📝 *Aktivitas:*\n{report['aktivitas']}\n\n"
                f"💡 *Pembelajaran:*\n{report['pembelajaran']}\n\n"
                f"🚧 *Kendala:*\n{report['kendala']}\n\n"
                "_Catatan: Laporan di atas TIDAK dikirim ke server Monev karena mode DRY RUN aktif._"
            )
            await send_telegram_msg(dry_msg)
            return

        # Step: Submit to Monev API
        result = await submit_attendance_with_token(
            token=token,
            activity_log=report["aktivitas"],
            lesson_learned=report["pembelajaran"],
            obstacles=report["kendala"],
            date_str=today_str,
        )

        status_code = result["status_code"]

        if result["success"]:
            state["done_date"] = today_str
            save_state(state)
            logger.info(f"Submit berhasil (HTTP {status_code}).")
            
            success_msg = (
                "✅ *Presensi Monev Berhasil Terkirim!*\n\n"
                f"📅 Tanggal: `{today_str}`\n"
                f"🏷️ Sumber: *{report['source']}*\n\n"
                f"📝 *Aktivitas:*\n{report['aktivitas']}\n\n"
                f"💡 *Pembelajaran:*\n{report['pembelajaran']}\n\n"
                f"🚧 *Kendala:*\n{report['kendala']}"
            )
            await send_telegram_msg(success_msg)

        elif result["is_conflict"]:
            state["done_date"] = today_str
            save_state(state)
            logger.info("Presensi sudah pernah tercatat sebelumnya (HTTP 409).")
            await send_telegram_msg(
                f"ℹ️ Presensi Monev hari ini (`{today_str}`) sudah tercatat di server (HTTP 409). Ditandai selesai."
            )

        else:
            state["attempts"] = int(state.get("attempts", 0)) + 1
            save_state(state)
            logger.error(f"Submit gagal (HTTP {status_code}). Percobaan ke-{state['attempts']}/3.")
            
            fail_msg = (
                "❌ *Pengiriman Presensi Monev Gagal!*\n\n"
                f"Kode Status: `HTTP {status_code}`\n"
                f"Percobaan: {state['attempts']}/3\n"
                f"Detail: {result['message']}\n\n"
                "Sistem akan mencoba lagi pada jadwal berikutnya, atau kirim `/submit` dari Telegram."
            )
            await send_telegram_msg(fail_msg)

    except MonevAuthError as e:
        logger.error(f"Otentikasi Monev gagal: {e}")
        await send_telegram_msg(f"❌ *Otentikasi Monev Gagal:*\n{str(e)}")
    except Exception as e:
        logger.error(f"Terjadi kesalahan pada alur submit: {type(e).__name__}")
        await send_telegram_msg(f"❌ *Kesalahan Sistem saat Submit:*\n{type(e).__name__}")


async def run_actions(mode: str = "run", dry_run: bool = False) -> None:
    """Main execution controller for GitHub Actions."""
    now_wib = config.get_now_wib()
    today_str = config.get_today_wib_str()
    is_dry_run = dry_run or config.DRY_RUN

    logger.info(f"Menjalankan monev-bot runner [Mode: {mode}, DryRun: {is_dry_run}, Waktu WIB: {now_wib.strftime('%H:%M:%S')}]")

    # 1. Check Off Days (except for manual diagnostic modes)
    if config.is_off_day(now_wib) and mode not in ("check", "preview"):
        logger.info(f"Hari ini ({now_wib.strftime('%A')}) adalah hari libur (OFF_DAYS). Runner keluar.")
        return

    # 2. Load State
    state = load_state()

    # 3. If already marked done for today (except for manual preview/check/status)
    if state.get("done_date") == today_str and mode not in ("check", "preview", "status"):
        logger.info(f"Presensi untuk tanggal {today_str} sudah berstatus selesai (done_date). Runner keluar.")
        return

    # 4. Fetch Telegram Inbox Updates (without offset)
    inbox = await get_inbox_updates()

    # 5. Handle Mode: "check" (Manual Connection / Auth Diagnostic)
    if mode == "check":
        logger.info("Menjalankan mode diagnostik 'check'...")
        try:
            token = await login_monev(config.MONEV_EMAIL, config.MONEV_PASSWORD)
            logger.info("[Auth] [Step 1-4] OK. Login SSO berhasil.")
            status = await get_home_status_with_token(token)
            logger.info(f"[API] Status fetched: has_attendance={status['has_attendance']}")
            
            att_text = "✅ Sudah Presensi" if status["has_attendance"] else "❌ Belum Presensi"
            hol_text = "Ya" if status["is_holiday"] else "Tidak"
            off_text = "Ya" if status["is_scheduled_off_day"] else "Tidak"
            
            check_msg = (
                "🔍 *Hasil Uji Akun Monev (Mode Check)*\n\n"
                f"📅 Tanggal: `{status['date']}`\n"
                f"📌 Status Presensi: *{att_text}*\n"
                f"🏖️ Hari Libur Nasional: {hol_text}\n"
                f"🗓️ Hari Libur Terjadwal: {off_text}\n"
                f"📝 Poin Terbaca Hari Ini: {len(inbox['points'])} butir\n\n"
                "Koneksi dari GitHub Actions ke SSO Kemnaker dan Monev API berjalan normal!"
            )
            await send_telegram_msg(check_msg)
        except Exception as e:
            logger.error(f"Mode check gagal: {e}")
            await send_telegram_msg(f"❌ *Uji Koneksi Monev Gagal:*\n{str(e)}")
        return

    # 6. Handle Mode: "preview" OR Telegram Command /preview
    if mode == "preview" or inbox.get("has_preview_cmd"):
        logger.info("Menyusun pratinjau draf laporan...")
        report = await build_daily_report(points=inbox.get("points", []))
        prev_msg = (
            "📋 *Pratinjau Draf Laporan Presensi (GitHub Actions)*\n\n"
            f"📅 Tanggal: `{today_str}`\n"
            f"🏷️ Sumber: *{report['source']}*\n\n"
            f"📝 *Uraian Aktivitas* ({len(report['aktivitas'])} karakter):\n"
            f"{report['aktivitas']}\n\n"
            f"💡 *Pembelajaran* ({len(report['pembelajaran'])} karakter):\n"
            f"{report['pembelajaran']}\n\n"
            f"🚧 *Kendala* ({len(report['kendala'])} karakter):\n"
            f"{report['kendala']}\n\n"
            "_Kirim /submit dari Telegram jika ingin mengirim laporan sekarang._"
        )
        await send_telegram_msg(prev_msg)
        if mode == "preview":
            return

    # 7. Handle Telegram Command /status
    if inbox.get("has_status_cmd"):
        logger.info("Memproses permintaan /status...")
        try:
            token = await login_monev(config.MONEV_EMAIL, config.MONEV_PASSWORD)
            status = await get_home_status_with_token(token)
            att_text = "✅ Sudah Presensi" if status["has_attendance"] else "❌ Belum Presensi"
            
            source_desc = f"Poin kegiatan ({len(inbox['points'])} butir)" if inbox["points"] else "Template laporan"
            postponed_text = "Ya (/tunda)" if inbox["is_postponed"] else "Tidak"

            status_msg = (
                "📊 *Status Presensi & Rencana Auto-Submit*\n\n"
                f"📅 Tanggal: `{status['date']}`\n"
                f"📌 Status: *{att_text}*\n"
                f"⏸️ Ditunda: {postponed_text}\n"
                f"📋 Sumber Laporan: *{source_desc}*\n"
                f"⏰ Jadwal Submit: *Setelah {config.SUBMIT_AFTER_STR} WIB*\n"
                f"🔁 Percobaan Gagal Hari Ini: {state.get('attempts', 0)}/3"
            )
            await send_telegram_msg(status_msg)
        except Exception as e:
            logger.error(f"Gagal memproses /status: {e}")
            await send_telegram_msg(f"❌ Gagal mengambil status: {type(e).__name__}")

    # 8. Check attempts limit
    attempts = int(state.get("attempts", 0))
    if attempts >= 3 and mode != "submit" and not inbox.get("has_submit_cmd"):
        logger.warning(f"Batas maksimal 3 percobaan submit hari ini telah tercapai ({attempts}/3).")
        return

    # 9. Handle Immediate Submit (mode "submit" or Telegram /submit)
    if mode == "submit" or inbox.get("has_submit_cmd"):
        logger.info("Perintah /submit terdeteksi atau mode submit dipicu.")
        await execute_submit_flow(state=state, inbox=inbox, is_dry_run=is_dry_run, is_manual=True)
        return

    # 10. Time-Based Logic (Default Mode: "run")
    # A. Before WARN_AFTER
    if not config.is_time_reached(config.WARN_AFTER, now_wib):
        logger.info(f"Waktu saat ini ({now_wib.strftime('%H:%M')}) belum mencapai WARN_AFTER ({config.WARN_AFTER_STR}). Runner selesai.")
        return

    # B. At / After WARN_AFTER and not warned yet
    if config.is_time_reached(config.WARN_AFTER, now_wib) and state.get("warned_date") != today_str:
        logger.info("Mengecek status Monev untuk peringatan WARN_AFTER...")
        try:
            token = await login_monev(config.MONEV_EMAIL, config.MONEV_PASSWORD)
            status = await get_home_status_with_token(token)

            if status["has_attendance"] or status["is_holiday"] or status["is_scheduled_off_day"]:
                state["done_date"] = today_str
                save_state(state)
                logger.info("Presensi sudah selesai / hari libur. Tidak perlu peringatan.")
                await send_telegram_msg(f"🌙 Status Presensi Hari Ini (`{today_str}`): Sudah lengkap / hari libur. Selamat beristirahat!")
                return

            # Still not attended -> send warning
            source_desc = f"Poin kegiatan ({len(inbox['points'])} butir)" if inbox["points"] else "Template laporan (belum ada poin)"
            warn_msg = (
                "⚠️ *Peringatan Presensi Monev (GitHub Actions)*\n\n"
                f"Halo! Kamu belum melakukan presensi Monev hari ini (`{today_str}`).\n"
                f"Auto-submit akan dieksekusi setelah pukul *{config.SUBMIT_AFTER_STR} WIB*.\n\n"
                f"📋 *Rencana Sumber Laporan:* {source_desc}\n\n"
                "• Ingin membatalkan auto-submit hari ini? Kirim `/tunda`\n"
                "• Ingin mengaktifkan kembali jika sempat tunda? Kirim `/lanjut`\n"
                "• Ingin mengirim sekarang? Kirim `/submit`\n"
                "• Ingin menambah poin kegiatan? Kirim `/poin <kegiatan>`"
            )
            await send_telegram_msg(warn_msg)
            state["warned_date"] = today_str
            save_state(state)
            logger.info("Peringatan WARN_AFTER berhasil dikirim.")
        except Exception as e:
            logger.error(f"Gagal memproses pengecekan WARN_AFTER: {e}")

    # C. At / After SUBMIT_AFTER -> Auto Submit
    if config.is_time_reached(config.SUBMIT_AFTER, now_wib):
        if not config.AUTO_SUBMIT:
            logger.info("AUTO_SUBMIT dinonaktifkan (false) di konfigurasi.")
            return

        if inbox.get("is_postponed"):
            logger.info("Auto-submit ditunda (/tunda) oleh pengguna hari ini.")
            return

        if state.get("done_date") == today_str:
            logger.info("Presensi sudah berstatus selesai (done_date).")
            return

        logger.info(f"Waktu telah mencapai SUBMIT_AFTER ({config.SUBMIT_AFTER_STR}). Mengeksekusi auto-submit...")
        await execute_submit_flow(state=state, inbox=inbox, is_dry_run=is_dry_run, is_manual=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monev Attendance Bot - GitHub Actions Runner")
    parser.add_argument(
        "--mode",
        choices=["run", "check", "submit", "preview"],
        default="run",
        help="Mode eksekusi: run (default), check (uji login), submit (paksa submit), preview (lihat draf)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulasi submit tanpa memanggil API POST attendances",
    )
    args = parser.parse_args()

    asyncio.run(run_actions(mode=args.mode, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
