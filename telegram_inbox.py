import logging
from datetime import datetime, timezone
from typing import TypedDict
import httpx
import config

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class InboxData(TypedDict):
    points: list[str]
    has_submit_cmd: bool
    has_preview_cmd: bool
    has_status_cmd: bool
    is_postponed: bool


def _parse_message_date_wib(unix_ts: int) -> str:
    """Convert Telegram unix timestamp to YYYY-MM-DD in Asia/Jakarta timezone."""
    dt_utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    dt_wib = dt_utc.astimezone(config.WIB_TZ)
    return dt_wib.strftime("%Y-%m-%d")


async def get_inbox_updates(
    bot_token: str | None = None,
    target_chat_id: int | None = None,
    target_date_wib: str | None = None,
) -> InboxData:
    """
    Fetch Telegram updates WITHOUT offset.
    Filters messages for today WIB sent by target_chat_id.
    Parses points, commands, and tunda/lanjut state chronologically.
    """
    token = bot_token or config.TELEGRAM_BOT_TOKEN
    chat_id = target_chat_id if target_chat_id is not None else config.TELEGRAM_CHAT_ID
    today_wib = target_date_wib or config.get_today_wib_str()

    inbox: InboxData = {
        "points": [],
        "has_submit_cmd": False,
        "has_preview_cmd": False,
        "has_status_cmd": False,
        "is_postponed": False,
    }

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN belum diatur.")
        return inbox

    url = f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # IMPORTANT: No 'offset' param is sent so updates are preserved on Telegram
            resp = await client.get(url, params={"allowed_updates": ["message"]})
            if resp.status_code != 200:
                logger.error(f"Gagal mengambil getUpdates Telegram (HTTP {resp.status_code})")
                return inbox

            data = resp.json()
            if not data.get("ok"):
                logger.error(f"Respons getUpdates Telegram error: {data.get('description')}")
                return inbox

            updates = data.get("result", [])
            # Sort updates by message date or update_id to ensure chronological order
            sorted_updates = sorted(
                updates,
                key=lambda u: (
                    u.get("message", {}).get("date", 0),
                    u.get("update_id", 0),
                ),
            )

            for upd in sorted_updates:
                msg = upd.get("message")
                if not msg:
                    continue

                from_user = msg.get("from", {})
                sender_id = from_user.get("id")
                
                # Enforce chat_id whitelist: strictly ignore if sender is not TELEGRAM_CHAT_ID
                if chat_id is not None and sender_id != chat_id:
                    continue

                msg_ts = msg.get("date")
                if not msg_ts:
                    continue

                msg_date_str = _parse_message_date_wib(msg_ts)
                # Ignore messages not from today WIB
                if msg_date_str != today_wib:
                    continue

                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                # Parse Commands & Points
                if text.startswith("/poin"):
                    point_text = text[5:].strip()
                    if point_text:
                        inbox["points"].append(point_text)
                elif text == "/submit" or text.startswith("/submit "):
                    inbox["has_submit_cmd"] = True
                elif text == "/preview" or text.startswith("/preview "):
                    inbox["has_preview_cmd"] = True
                elif text == "/status" or text.startswith("/status "):
                    inbox["has_status_cmd"] = True
                elif text == "/tunda" or text.startswith("/tunda "):
                    inbox["is_postponed"] = True
                elif text == "/lanjut" or text.startswith("/lanjut "):
                    inbox["is_postponed"] = False

    except Exception as e:
        logger.error(f"Terjadi kesalahan saat membaca getUpdates Telegram: {e}")

    return inbox


async def send_telegram_msg(
    text: str,
    chat_id: int | None = None,
    bot_token: str | None = None,
    parse_mode: str = "Markdown",
) -> bool:
    """Send a message to the user via Telegram Bot API."""
    token = bot_token or config.TELEGRAM_BOT_TOKEN
    target_id = chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID

    if not token or not target_id:
        logger.warning("Tidak dapat mengirim pesan Telegram: TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum diatur.")
        return False

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": target_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            else:
                logger.error(f"Gagal mengirim pesan Telegram (HTTP {resp.status_code}): {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Exception saat mengirim pesan Telegram: {e}")
        return False


async def delete_webhook(bot_token: str | None = None) -> bool:
    """Delete any active webhook so getUpdates works properly."""
    token = bot_token or config.TELEGRAM_BOT_TOKEN
    if not token:
        return False
    url = f"{TELEGRAM_API_BASE}/bot{token}/deleteWebhook"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json={"drop_pending_updates": False})
            return resp.status_code == 200
    except Exception:
        return False
