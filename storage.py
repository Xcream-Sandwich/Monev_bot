import json
import time
from pathlib import Path
from typing import Any
import config
from crypto import encrypt_str, decrypt_str


def _read_json(file_path: Path, default: Any = None) -> Any:
    """Read and parse JSON from file, or return default."""
    if default is None:
        default = {}
    if not file_path.exists():
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(file_path: Path, data: Any) -> None:
    """Safely write JSON data to file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp_path.replace(file_path)


# ==========================================
# User Management
# ==========================================

def get_user(telegram_id: int | str) -> dict | None:
    """Get stored user data by telegram_id."""
    data = _read_json(config.USERS_STORE_FILE, {})
    return data.get(str(telegram_id))


def get_all_users() -> dict[str, dict]:
    """Get all registered users."""
    return _read_json(config.USERS_STORE_FILE, {})


def save_user(
    telegram_id: int | str,
    email: str,
    password: str,
    auto_submit_enabled: bool = False,
    cached_token: str | None = None,
) -> None:
    """Save or update user credentials with encryption."""
    tid = str(telegram_id)
    data = _read_json(config.USERS_STORE_FILE, {})
    
    enc_password = encrypt_str(password)
    enc_token = encrypt_str(cached_token) if cached_token else ""
    token_ts = int(time.time()) if cached_token else 0

    existing = data.get(tid, {})
    data[tid] = {
        "email": email.strip(),
        "encrypted_password": enc_password,
        "auto_submit_enabled": auto_submit_enabled or existing.get("auto_submit_enabled", False),
        "cached_token": enc_token if cached_token else existing.get("cached_token", ""),
        "token_timestamp": token_ts if cached_token else existing.get("token_timestamp", 0),
    }
    _write_json(config.USERS_STORE_FILE, data)


def delete_user(telegram_id: int | str) -> bool:
    """Delete a user and their associated session."""
    tid = str(telegram_id)
    data = _read_json(config.USERS_STORE_FILE, {})
    if tid in data:
        del data[tid]
        _write_json(config.USERS_STORE_FILE, data)
        return True
    return False


def set_user_auto_submit(telegram_id: int | str, enabled: bool) -> bool:
    """Enable or disable auto-submit for a user."""
    tid = str(telegram_id)
    data = _read_json(config.USERS_STORE_FILE, {})
    if tid not in data:
        return False
    data[tid]["auto_submit_enabled"] = enabled
    _write_json(config.USERS_STORE_FILE, data)
    return True


def get_user_credentials(telegram_id: int | str) -> tuple[str, str] | None:
    """Return decrypted (email, password) for a user, or None if not found."""
    user = get_user(telegram_id)
    if not user:
        return None
    try:
        email = user["email"]
        password = decrypt_str(user["encrypted_password"])
        return email, password
    except Exception:
        return None


def save_cached_token(telegram_id: int | str, token: str) -> None:
    """Save encrypted token and update timestamp."""
    tid = str(telegram_id)
    data = _read_json(config.USERS_STORE_FILE, {})
    if tid in data:
        data[tid]["cached_token"] = encrypt_str(token)
        data[tid]["token_timestamp"] = int(time.time())
        _write_json(config.USERS_STORE_FILE, data)


def get_cached_token(telegram_id: int | str) -> str | None:
    """Get decrypted cached token if available."""
    user = get_user(telegram_id)
    if not user or not user.get("cached_token"):
        return None
    try:
        return decrypt_str(user["cached_token"])
    except Exception:
        return None


# ==========================================
# Daily Points Management
# ==========================================

def add_daily_point(telegram_id: int | str, point_text: str, date_str: str | None = None) -> list[str]:
    """Add a point for the given date (default today WIB). Return updated list."""
    tid = str(telegram_id)
    ds = date_str or config.get_today_wib_str()
    data = _read_json(config.DAILY_POINTS_FILE, {})
    if tid not in data:
        data[tid] = {}
    if ds not in data[tid]:
        data[tid][ds] = []
    
    clean_point = point_text.strip()
    if clean_point:
        data[tid][ds].append(clean_point)
    _write_json(config.DAILY_POINTS_FILE, data)
    return data[tid][ds]


def get_daily_points(telegram_id: int | str, date_str: str | None = None) -> list[str]:
    """Get list of points for the given date (default today WIB)."""
    tid = str(telegram_id)
    ds = date_str or config.get_today_wib_str()
    data = _read_json(config.DAILY_POINTS_FILE, {})
    return data.get(tid, {}).get(ds, [])


def clear_daily_points(telegram_id: int | str, date_str: str | None = None) -> None:
    """Clear points for the given date (default today WIB)."""
    tid = str(telegram_id)
    ds = date_str or config.get_today_wib_str()
    data = _read_json(config.DAILY_POINTS_FILE, {})
    if tid in data and ds in data[tid]:
        del data[tid][ds]
        _write_json(config.DAILY_POINTS_FILE, data)


# ==========================================
# Auto State & Evening State Management
# ==========================================

def set_skip_date(telegram_id: int | str, date_str: str) -> None:
    """Mark a date as skipped (/tunda) for auto-submit."""
    tid = str(telegram_id)
    data = _read_json(config.AUTO_STATE_FILE, {})
    if tid not in data:
        data[tid] = {}
    data[tid]["skip_date"] = date_str
    _write_json(config.AUTO_STATE_FILE, data)


def get_skip_date(telegram_id: int | str) -> str | None:
    tid = str(telegram_id)
    data = _read_json(config.AUTO_STATE_FILE, {})
    return data.get(tid, {}).get("skip_date")


def set_auto_done_date(telegram_id: int | str, date_str: str) -> None:
    """Mark auto-submit as done for a date."""
    tid = str(telegram_id)
    data = _read_json(config.AUTO_STATE_FILE, {})
    if tid not in data:
        data[tid] = {}
    data[tid]["auto_done_date"] = date_str
    _write_json(config.AUTO_STATE_FILE, data)


def get_auto_done_date(telegram_id: int | str) -> str | None:
    tid = str(telegram_id)
    data = _read_json(config.AUTO_STATE_FILE, {})
    return data.get(tid, {}).get("auto_done_date")


def set_evening_done_date(telegram_id: int | str, date_str: str) -> None:
    """Mark evening reminder as completed for a date."""
    tid = str(telegram_id)
    data = _read_json(config.EVENING_STATE_FILE, {})
    if tid not in data:
        data[tid] = {}
    data[tid]["evening_done_date"] = date_str
    _write_json(config.EVENING_STATE_FILE, data)


def get_evening_done_date(telegram_id: int | str) -> str | None:
    tid = str(telegram_id)
    data = _read_json(config.EVENING_STATE_FILE, {})
    return data.get(tid, {}).get("evening_done_date")


# ==========================================
# Submit History Management
# ==========================================

def record_submit_history(
    telegram_id: int | str,
    date_str: str,
    source: str,
    http_code: int,
    result: str,
    detail: str = "",
) -> None:
    """Record a submission attempt in history."""
    tid = str(telegram_id)
    history = _read_json(config.SUBMIT_HISTORY_FILE, [])
    record = {
        "telegram_id": int(tid) if tid.isdigit() else tid,
        "date": date_str,
        "timestamp": config.get_now_wib().isoformat(),
        "source": source,
        "http_code": http_code,
        "result": result,
        "detail": detail,
    }
    history.append(record)
    if len(history) > 200:
        history = history[-200:]
    _write_json(config.SUBMIT_HISTORY_FILE, history)


def get_submit_history(telegram_id: int | str, limit: int = 10) -> list[dict]:
    """Get latest submission history for a user."""
    tid = str(telegram_id)
    history = _read_json(config.SUBMIT_HISTORY_FILE, [])
    user_history = [
        item for item in history
        if str(item.get("telegram_id")) == tid
    ]
    return user_history[-limit:]


# ==========================================
# Templates Management
# ==========================================

def load_templates() -> dict:
    """Load templates.json or fallback to empty dict."""
    return _read_json(config.TEMPLATES_FILE, {})
