import json
import logging
from pathlib import Path
from typing import TypedDict
import config

logger = logging.getLogger(__name__)

ALLOWED_STATE_KEYS = {"date", "warned_date", "done_date", "attempts"}


class ActionsState(TypedDict):
    date: str
    warned_date: str | None
    done_date: str | None
    attempts: int


def get_default_state(date_str: str | None = None) -> ActionsState:
    """Return a clean default state for the given date (default today WIB)."""
    target_date = date_str or config.get_today_wib_str()
    return {
        "date": target_date,
        "warned_date": None,
        "done_date": None,
        "attempts": 0,
    }


def load_state() -> ActionsState:
    """
    Load state.json from file.
    If file doesn't exist, is corrupted, or belongs to a previous date,
    returns a fresh state for today WIB.
    """
    today_str = config.get_today_wib_str()
    file_path = config.STATE_FILE

    if not file_path.exists():
        return get_default_state(today_str)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return get_default_state(today_str)

        # Filter to allowed keys only
        cleaned_state: ActionsState = {
            "date": str(data.get("date", today_str)),
            "warned_date": data.get("warned_date") if data.get("warned_date") else None,
            "done_date": data.get("done_date") if data.get("done_date") else None,
            "attempts": int(data.get("attempts", 0)) if str(data.get("attempts", 0)).isdigit() else 0,
        }

        # Date rollover check: reset state for new day
        if cleaned_state["date"] != today_str:
            return get_default_state(today_str)

        return cleaned_state
    except Exception as e:
        logger.warning(f"Gagal membaca state.json, mereset state: {e}")
        return get_default_state(today_str)


def save_state(state: dict) -> bool:
    """
    Save state.json to file (only non-sensitive keys).
    Returns True if contents changed on disk, False otherwise.
    """
    file_path = config.STATE_FILE
    today_str = config.get_today_wib_str()

    cleaned_state: ActionsState = {
        "date": str(state.get("date", today_str)),
        "warned_date": state.get("warned_date") if state.get("warned_date") else None,
        "done_date": state.get("done_date") if state.get("done_date") else None,
        "attempts": int(state.get("attempts", 0)),
    }

    # Compare with existing file
    existing_raw = ""
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_raw = f.read().strip()
        except Exception:
            existing_raw = ""

    new_raw = json.dumps(cleaned_state, indent=2, ensure_ascii=False)
    if existing_raw == new_raw:
        return False

    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(new_raw)
    temp_path.replace(file_path)
    return True
