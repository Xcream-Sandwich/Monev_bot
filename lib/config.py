"""
lib/config.py — Configuration for Vercel serverless mode.
Reads all settings from environment variables (Vercel Project Settings / .env for local dev).
No file paths — all storage is via Vercel KV (Upstash Redis).
"""
import os
from datetime import datetime, date, time
from zoneinfo import ZoneInfo

# =============================================
# Timezone
# =============================================
WIB_TZ = ZoneInfo("Asia/Jakarta")

# =============================================
# Telegram
# =============================================
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID_STR: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_CHAT_ID: int | None = (
    int(TELEGRAM_CHAT_ID_STR)
    if (TELEGRAM_CHAT_ID_STR.lstrip("-").isdigit())
    else None
)
TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

# =============================================
# Cron security
# =============================================
CRON_SECRET: str = os.getenv("CRON_SECRET", "").strip()

# =============================================
# Encryption
# =============================================
ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "").strip()

# =============================================
# Groq (optional LLM)
# =============================================
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()

# =============================================
# Vercel KV (Upstash Redis REST API)
# =============================================
KV_REST_API_URL: str = os.getenv("KV_REST_API_URL", "").strip()
KV_REST_API_TOKEN: str = os.getenv("KV_REST_API_TOKEN", "").strip()

# =============================================
# Schedules & Off Days
# =============================================
WARN_AFTER_STR: str = os.getenv("WARN_AFTER", "16:00").strip()
SUBMIT_AFTER_STR: str = os.getenv("SUBMIT_AFTER", "17:00").strip()
AUTO_SUBMIT: bool = os.getenv("AUTO_SUBMIT", "true").strip().lower() in ("true", "1", "yes")

OFF_DAYS_STR: str = os.getenv("OFF_DAYS", "Saturday,Sunday").strip()
OFF_DAYS: set[str] = {
    day.strip().capitalize()
    for day in OFF_DAYS_STR.split(",")
    if day.strip()
}

TEMPLATES_JSON: str = os.getenv("TEMPLATES_JSON", "").strip()


# =============================================
# Helpers
# =============================================

def parse_time_str(time_str: str, default: time) -> time:
    """Parse HH:MM string into a time object (WIB-aware)."""
    try:
        parts = time_str.split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, tzinfo=WIB_TZ)
    except Exception:
        return default


WARN_AFTER = parse_time_str(WARN_AFTER_STR, time(16, 0, tzinfo=WIB_TZ))
SUBMIT_AFTER = parse_time_str(SUBMIT_AFTER_STR, time(17, 0, tzinfo=WIB_TZ))


def get_now_wib() -> datetime:
    """Current datetime in WIB."""
    return datetime.now(WIB_TZ)


def get_today_wib_str() -> str:
    """Today's date as YYYY-MM-DD in WIB."""
    return get_now_wib().strftime("%Y-%m-%d")


def is_off_day(dt: datetime | date | None = None) -> bool:
    """True if the given date (default today WIB) is an OFF_DAY."""
    if dt is None:
        dt = get_now_wib()
    return dt.strftime("%A").capitalize() in OFF_DAYS
