import os
from datetime import datetime, date, time
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Timezone constant (WIB)
WIB_TZ = ZoneInfo("Asia/Jakarta")

# Secrets and Tokens (Shared & Polling mode)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# GitHub Actions mode Credentials & Config
MONEV_EMAIL = os.getenv("MONEV_EMAIL", "").strip()
MONEV_PASSWORD = os.getenv("MONEV_PASSWORD", "").strip()
TELEGRAM_CHAT_ID_STR = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_CHAT_ID: int | None = int(TELEGRAM_CHAT_ID_STR) if (TELEGRAM_CHAT_ID_STR.isdigit() or (TELEGRAM_CHAT_ID_STR.startswith("-") and TELEGRAM_CHAT_ID_STR[1:].isdigit())) else None

# Schedules & Off Days (Polling mode)
WARN_TIME_STR = os.getenv("WARN_TIME", "16:00").strip()
AUTO_SUBMIT_TIME_STR = os.getenv("AUTO_SUBMIT_TIME", "17:00").strip()

# Schedules & Flags (GitHub Actions mode)
WARN_AFTER_STR = os.getenv("WARN_AFTER", "17:15").strip()
SUBMIT_AFTER_STR = os.getenv("SUBMIT_AFTER", "17:45").strip()
AUTO_SUBMIT = os.getenv("AUTO_SUBMIT", "true").strip().lower() in ("true", "1", "yes")
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() in ("true", "1", "yes")
TEMPLATES_JSON = os.getenv("TEMPLATES_JSON", "").strip()

OFF_DAYS_STR = os.getenv("OFF_DAYS", "Saturday,Sunday").strip()
ALLOWED_TELEGRAM_IDS_STR = os.getenv("ALLOWED_TELEGRAM_IDS", "").strip()

# Parse OFF_DAYS into set of title-cased day names (e.g. {'Saturday', 'Sunday'})
OFF_DAYS = {
    day.strip().capitalize()
    for day in OFF_DAYS_STR.split(",")
    if day.strip()
}

# Parse ALLOWED_TELEGRAM_IDS
ALLOWED_TELEGRAM_IDS: set[int] = set()
if ALLOWED_TELEGRAM_IDS_STR:
    for item in ALLOWED_TELEGRAM_IDS_STR.split(","):
        item = item.strip()
        if item.isdigit():
            ALLOWED_TELEGRAM_IDS.add(int(item))

# Storage File Paths
USERS_STORE_FILE = BASE_DIR / "users_store.json"
DAILY_POINTS_FILE = BASE_DIR / "daily_points.json"
AUTO_STATE_FILE = BASE_DIR / "auto_state.json"
EVENING_STATE_FILE = BASE_DIR / "evening_state.json"
SUBMIT_HISTORY_FILE = BASE_DIR / "submit_history.json"
TEMPLATES_FILE = BASE_DIR / "templates.json"
STATE_FILE = BASE_DIR / "state.json"


def parse_time_str(time_str: str, default: time = time(16, 0)) -> time:
    """Parse string HH:MM into time object with WIB timezone."""
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return time(hour=hour, minute=minute, tzinfo=WIB_TZ)
    except Exception:
        return default


WARN_TIME = parse_time_str(WARN_TIME_STR, default=time(16, 0, tzinfo=WIB_TZ))
AUTO_SUBMIT_TIME = parse_time_str(AUTO_SUBMIT_TIME_STR, default=time(17, 0, tzinfo=WIB_TZ))
WARN_AFTER = parse_time_str(WARN_AFTER_STR, default=time(17, 15, tzinfo=WIB_TZ))
SUBMIT_AFTER = parse_time_str(SUBMIT_AFTER_STR, default=time(17, 45, tzinfo=WIB_TZ))


def get_now_wib() -> datetime:
    """Return current datetime in Asia/Jakarta timezone."""
    return datetime.now(WIB_TZ)


def get_today_wib_str() -> str:
    """Return today's date formatted as YYYY-MM-DD in Asia/Jakarta timezone."""
    return get_now_wib().strftime("%Y-%m-%d")


def is_off_day(dt: datetime | date | None = None) -> bool:
    """Check if given date (or current date in WIB) falls on an OFF_DAYS."""
    if dt is None:
        dt = get_now_wib()
    day_name = dt.strftime("%A").capitalize()
    return day_name in OFF_DAYS


def is_user_allowed(telegram_id: int) -> bool:
    """Check if telegram_id is allowed by whitelist, if configured."""
    if not ALLOWED_TELEGRAM_IDS:
        return True
    return telegram_id in ALLOWED_TELEGRAM_IDS


def is_time_reached(target_time: time, current_dt: datetime | None = None) -> bool:
    """Check if current time (in WIB) has reached or passed target_time."""
    if current_dt is None:
        current_dt = get_now_wib()
    current_time = current_dt.timetz()
    return current_time >= target_time
