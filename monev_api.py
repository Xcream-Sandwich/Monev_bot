import logging
from typing import TypedDict
import httpx
import config
from monev_auth import get_valid_token, MONEV_BASE_URL, DEFAULT_HEADERS, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class HomeStatus(TypedDict):
    date: str
    has_attendance: bool
    is_holiday: bool
    is_scheduled_off_day: bool
    raw_data: dict


class SubmitResult(TypedDict):
    success: bool
    is_conflict: bool
    status_code: int
    message: str


# ==========================================
# Direct Token Functions (GitHub Actions Mode)
# ==========================================

async def get_home_status_with_token(token: str) -> HomeStatus:
    """Fetch user home/attendance status using a provided access token."""
    url = f"{MONEV_BASE_URL}/api/v1/users/me/home"
    headers = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(headers=headers, timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gagal mengambil status presensi Monev (HTTP {resp.status_code})")
        
        body = resp.json()
        data = body.get("data", body) if isinstance(body, dict) else {}
        
        date_val = data.get("date") or config.get_today_wib_str()
        has_attendance = bool(data.get("has_attendance", False))
        is_holiday = bool(data.get("is_holiday", False))
        is_scheduled_off_day = bool(data.get("is_scheduled_off_day", False))
        
        return {
            "date": str(date_val),
            "has_attendance": has_attendance,
            "is_holiday": is_holiday,
            "is_scheduled_off_day": is_scheduled_off_day,
            "raw_data": data if isinstance(data, dict) else {},
        }


async def submit_attendance_with_token(
    token: str,
    activity_log: str,
    lesson_learned: str,
    obstacles: str,
    date_str: str | None = None,
) -> SubmitResult:
    """Submit daily attendance and log using a provided access token."""
    target_date = date_str or config.get_today_wib_str()
    payload = {
        "date": target_date,
        "status": "PRESENT",
        "activity_log": activity_log,
        "lesson_learned": lesson_learned,
        "obstacles": obstacles,
    }
    url = f"{MONEV_BASE_URL}/api/v1/attendances/with-daily-log"
    headers = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(headers=headers, timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        status_code = resp.status_code
        
        if status_code in (200, 201):
            return {
                "success": True,
                "is_conflict": False,
                "status_code": status_code,
                "message": "Presensi dan laporan harian berhasil dikirim ke Monev.",
            }
        elif status_code == 409:
            return {
                "success": False,
                "is_conflict": True,
                "status_code": status_code,
                "message": "Presensi untuk tanggal ini sudah pernah tercatat di Monev (HTTP 409).",
            }
        else:
            err_detail = ""
            try:
                err_json = resp.json()
                err_detail = err_json.get("message") or str(err_json)
            except Exception:
                err_detail = resp.text[:200]
            
            return {
                "success": False,
                "is_conflict": False,
                "status_code": status_code,
                "message": f"Gagal mengirim presensi ke Monev (HTTP {status_code}): {err_detail}",
            }


# ==========================================
# Storage / Polling Mode Functions
# ==========================================

async def _authenticated_request(
    telegram_id: int | str,
    method: str,
    endpoint: str,
    json_data: dict | None = None,
) -> httpx.Response:
    """
    Execute authenticated request to Monev API with automatic token renewal on 401/403.
    """
    url = f"{MONEV_BASE_URL}{endpoint}"
    token = await get_valid_token(telegram_id=telegram_id, force_refresh=False)
    
    headers = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    
    async with httpx.AsyncClient(headers=headers, timeout=HTTP_TIMEOUT) as client:
        resp = await client.request(method, url, json=json_data)
        
        if resp.status_code in (401, 403):
            logger.info(f"Token expired (HTTP {resp.status_code}) for user {telegram_id}. Re-authenticating...")
            new_token = await get_valid_token(telegram_id=telegram_id, force_refresh=True)
            headers["Authorization"] = f"Bearer {new_token}"
            resp = await client.request(method, url, json=json_data)
        
        return resp


async def get_home_status(telegram_id: int | str) -> HomeStatus:
    """Fetch user home/attendance status from /api/v1/users/me/home."""
    resp = await _authenticated_request(telegram_id, "GET", "/api/v1/users/me/home")
    
    if resp.status_code >= 400:
        raise RuntimeError(f"Gagal mengambil status presensi Monev (HTTP {resp.status_code})")
    
    body = resp.json()
    data = body.get("data", body) if isinstance(body, dict) else {}
    
    date_val = data.get("date") or config.get_today_wib_str()
    has_attendance = bool(data.get("has_attendance", False))
    is_holiday = bool(data.get("is_holiday", False))
    is_scheduled_off_day = bool(data.get("is_scheduled_off_day", False))
    
    return {
        "date": str(date_val),
        "has_attendance": has_attendance,
        "is_holiday": is_holiday,
        "is_scheduled_off_day": is_scheduled_off_day,
        "raw_data": data if isinstance(data, dict) else {},
    }


async def submit_attendance_and_log(
    telegram_id: int | str,
    activity_log: str,
    lesson_learned: str,
    obstacles: str,
    date_str: str | None = None,
) -> SubmitResult:
    """Submit daily attendance and 3-part log to /api/v1/attendances/with-daily-log."""
    target_date = date_str or config.get_today_wib_str()
    payload = {
        "date": target_date,
        "status": "PRESENT",
        "activity_log": activity_log,
        "lesson_learned": lesson_learned,
        "obstacles": obstacles,
    }
    
    resp = await _authenticated_request(
        telegram_id,
        "POST",
        "/api/v1/attendances/with-daily-log",
        json_data=payload,
    )
    
    status_code = resp.status_code
    
    if status_code in (200, 201):
        return {
            "success": True,
            "is_conflict": False,
            "status_code": status_code,
            "message": "Presensi dan laporan harian berhasil dikirim ke Monev.",
        }
    elif status_code == 409:
        return {
            "success": False,
            "is_conflict": True,
            "status_code": status_code,
            "message": "Presensi untuk tanggal ini sudah pernah tercatat di Monev (HTTP 409).",
        }
    else:
        err_detail = ""
        try:
            err_json = resp.json()
            err_detail = err_json.get("message") or str(err_json)
        except Exception:
            err_detail = resp.text[:200]
        
        return {
            "success": False,
            "is_conflict": False,
            "status_code": status_code,
            "message": f"Gagal mengirim presensi ke Monev (HTTP {status_code}): {err_detail}",
        }
