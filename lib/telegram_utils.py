"""
lib/telegram_utils.py — Thin helpers for calling Telegram Bot API via httpx.
No sensitive data (tokens, passwords) is ever included in log output.
"""
import logging
import httpx
from lib import config

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0


def _tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


async def send_message(chat_id: int | str, text: str, parse_mode: str = "HTML") -> dict:
    """Send a text message to a Telegram chat."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            _tg_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )
        return resp.json()


async def delete_message(chat_id: int | str, message_id: int) -> None:
    """Delete a message from a Telegram chat (e.g., message containing password)."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(
                _tg_url("deleteMessage"),
                json={"chat_id": chat_id, "message_id": message_id},
            )
    except Exception as e:
        logger.warning("Gagal menghapus pesan Telegram: %s", type(e).__name__)


async def notify_owner(text: str) -> None:
    """Send notification to the configured bot owner (TELEGRAM_CHAT_ID)."""
    if not config.TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID tidak dikonfigurasi, notifikasi dilewati.")
        return
    await send_message(config.TELEGRAM_CHAT_ID, text)
