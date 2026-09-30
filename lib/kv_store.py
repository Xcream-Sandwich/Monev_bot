"""
lib/kv_store.py — Vercel KV (Upstash Redis) wrapper using REST API via httpx.

All operations are async. Uses only httpx — no additional SDK needed.

Key schema (documented here, not enforced by this module):
  user:credentials          -> {email, encrypted_password, encrypted_token, token_ts, auto_submit}
  user:reg_state            -> {step: "await_email"|"await_password", email: str}  TTL=300s
  points:{YYYY-MM-DD}       -> JSON list of strings  TTL=604800s (7 days)
  state:{YYYY-MM-DD}        -> {warned, done, attempts, postponed}  TTL=259200s (3 days)
  templates                 -> JSON dict (permanent)
"""
import json
import logging
from typing import Any

import httpx
from lib import config

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.KV_REST_API_TOKEN}",
        "Content-Type": "application/json",
    }


async def kv_get(key: str) -> Any:
    """
    GET /get/<key> -> returns parsed value or None if key doesn't exist.
    Upstash REST response: {"result": <value_or_null>}
    """
    if not config.KV_REST_API_URL or not config.KV_REST_API_TOKEN:
        raise RuntimeError("KV_REST_API_URL / KV_REST_API_TOKEN belum dikonfigurasi.")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{config.KV_REST_API_URL}/get/{key}",
            headers=_headers(),
        )
        resp.raise_for_status()
        result = resp.json().get("result")
    if result is None:
        return None
    # Values stored as JSON strings
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return result


async def kv_set(key: str, value: Any, ex: int | None = None) -> None:
    """
    SET <key> <json_value> [EX <seconds>]
    Upstash REST: POST /set/<key>/<encoded_value>[?ex=<seconds>]
    We use the pipeline endpoint for simplicity with body.
    """
    if not config.KV_REST_API_URL or not config.KV_REST_API_TOKEN:
        raise RuntimeError("KV_REST_API_URL / KV_REST_API_TOKEN belum dikonfigurasi.")
    serialised = json.dumps(value, ensure_ascii=False)
    url = f"{config.KV_REST_API_URL}/set/{_url_encode_key(key)}/{_url_encode_key(serialised)}"
    params = {"ex": ex} if ex else {}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(url, headers=_headers(), params=params)
        resp.raise_for_status()


async def kv_delete(key: str) -> None:
    """DELETE /del/<key>"""
    if not config.KV_REST_API_URL or not config.KV_REST_API_TOKEN:
        raise RuntimeError("KV_REST_API_URL / KV_REST_API_TOKEN belum dikonfigurasi.")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{config.KV_REST_API_URL}/del/{key}",
            headers=_headers(),
        )
        resp.raise_for_status()


async def kv_expire(key: str, seconds: int) -> None:
    """EXPIRE <key> <seconds> via Upstash REST."""
    if not config.KV_REST_API_URL or not config.KV_REST_API_TOKEN:
        raise RuntimeError("KV_REST_API_URL / KV_REST_API_TOKEN belum dikonfigurasi.")
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{config.KV_REST_API_URL}/expire/{key}/{seconds}",
            headers=_headers(),
        )
        resp.raise_for_status()


def _url_encode_key(s: str) -> str:
    """URL-encode a string for use in Upstash REST path segments."""
    from urllib.parse import quote
    return quote(s, safe="")


# =============================================
# Higher-level helpers
# =============================================

KEY_CREDENTIALS = "user:credentials"
KEY_REG_STATE = "user:reg_state"
KEY_TEMPLATES = "templates"

TTL_POINTS = 7 * 24 * 3600    # 7 days
TTL_STATE = 3 * 24 * 3600     # 3 days
TTL_REG_STATE = 5 * 60        # 5 minutes


def _points_key(date_str: str) -> str:
    return f"points:{date_str}"


def _state_key(date_str: str) -> str:
    return f"state:{date_str}"


# --- Credentials ---

async def get_credentials() -> dict | None:
    """Return stored credentials dict or None."""
    return await kv_get(KEY_CREDENTIALS)


async def save_credentials(email: str, enc_password: str, enc_token: str = "", token_ts: int = 0, auto_submit: bool = True) -> None:
    """Persist encrypted credentials to KV."""
    await kv_set(KEY_CREDENTIALS, {
        "email": email,
        "encrypted_password": enc_password,
        "encrypted_token": enc_token,
        "token_ts": token_ts,
        "auto_submit": auto_submit,
    })


async def delete_token() -> None:
    """Remove cached token from credentials (force re-login on next request)."""
    creds = await get_credentials()
    if creds:
        creds["encrypted_token"] = ""
        creds["token_ts"] = 0
        await kv_set(KEY_CREDENTIALS, creds)


async def update_token(enc_token: str, token_ts: int) -> None:
    """Update only the cached token fields in credentials."""
    creds = await get_credentials()
    if creds:
        creds["encrypted_token"] = enc_token
        creds["token_ts"] = token_ts
        await kv_set(KEY_CREDENTIALS, creds)


# --- Registration state (multi-step /daftar) ---

async def get_reg_state() -> dict | None:
    """Return current registration flow state or None."""
    return await kv_get(KEY_REG_STATE)


async def set_reg_state(step: str, email: str = "") -> None:
    """Persist registration step with TTL=5 min."""
    await kv_set(KEY_REG_STATE, {"step": step, "email": email}, ex=TTL_REG_STATE)


async def clear_reg_state() -> None:
    await kv_delete(KEY_REG_STATE)


# --- Daily points ---

async def get_points(date_str: str) -> list[str]:
    val = await kv_get(_points_key(date_str))
    if isinstance(val, list):
        return val
    return []


async def add_point(date_str: str, point: str) -> list[str]:
    points = await get_points(date_str)
    clean = point.strip()
    if clean:
        points.append(clean)
    await kv_set(_points_key(date_str), points, ex=TTL_POINTS)
    return points


async def clear_points(date_str: str) -> None:
    await kv_delete(_points_key(date_str))


# --- Daily state ---

async def get_state(date_str: str) -> dict:
    val = await kv_get(_state_key(date_str))
    if isinstance(val, dict):
        return val
    return {"warned": False, "done": False, "attempts": 0, "postponed": False}


async def save_state(date_str: str, state: dict) -> None:
    await kv_set(_state_key(date_str), state, ex=TTL_STATE)


async def patch_state(date_str: str, **kwargs) -> dict:
    """Update individual fields of the daily state and persist."""
    state = await get_state(date_str)
    state.update(kwargs)
    await save_state(date_str, state)
    return state


# --- Templates ---

async def get_templates() -> dict:
    val = await kv_get(KEY_TEMPLATES)
    if isinstance(val, dict):
        return val
    return {}


async def save_templates(templates: dict) -> None:
    await kv_set(KEY_TEMPLATES, templates)
