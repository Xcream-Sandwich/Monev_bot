"""
lib/monev_auth.py — 4-step raw HTTP login to Monev MagangHub SSO.
This is the canonical login module for Vercel mode.
Credentials and tokens are stored/retrieved via lib.kv_store (Upstash Redis).
No passwords, tokens, or cookies are ever printed or logged.
"""
import logging
import re
import time as time_module
from urllib.parse import urljoin
import httpx
from lib import config
from lib.crypto import encrypt_str, decrypt_str
from lib import kv_store

logger = logging.getLogger(__name__)

MONEV_BASE_URL = "https://monev-api.maganghub.kemnaker.go.id"
SSO_BASE_URL = "https://account.kemnaker.go.id"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

HTTP_TIMEOUT = 20.0


class MonevAuthError(Exception):
    """Custom exception for Monev authentication errors."""
    pass


async def login_monev(email: str, password: str) -> str:
    """
    Execute 4-step raw HTTP login to Monev MagangHub SSO.
    Returns access_token on success, or raises MonevAuthError.
    Never leaks passwords, tokens, or raw cookies in error messages or logs.
    """
    if not email or not password:
        raise MonevAuthError("[Step 0] Email atau password Monev belum dikonfigurasi.")

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
        # [Step 1] Initiate login on Monev API
        try:
            step1_url = f"{MONEV_BASE_URL}/api/v1/auth/login"
            resp1 = await client.get(step1_url)

            sso_url = None
            if resp1.status_code in (301, 302, 303, 307, 308) and "location" in resp1.headers:
                sso_url = resp1.headers["location"]
            elif resp1.is_success or resp1.status_code in (200, 201):
                try:
                    data = resp1.json()
                    if isinstance(data, dict):
                        inner = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
                        sso_url = (
                            data.get("url") or data.get("sso_url")
                            or data.get("redirect_url") or data.get("redirect_uri")
                            or inner.get("url") or inner.get("sso_url")
                            or inner.get("redirect_url") or inner.get("redirect_uri")
                        )
                    elif isinstance(data, str) and data.strip().startswith("http"):
                        sso_url = data.strip()
                except Exception:
                    pass
                if not sso_url:
                    body_text = resp1.text.strip()
                    if body_text.startswith("http"):
                        sso_url = body_text
                if not sso_url and "location" in resp1.headers:
                    sso_url = resp1.headers["location"]

            if not sso_url:
                raise MonevAuthError(f"[Step 1] Gagal mendapatkan URL SSO dari Monev API (HTTP {resp1.status_code})")
            logger.debug("Step 1 OK – SSO URL obtained (HTTP %s)", resp1.status_code)
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 1] Kesalahan koneksi ke Monev API: {type(e).__name__}")

        initial_cookies = dict(client.cookies)

        # [Step 2] Fetch SSO page and extract CSRF token
        try:
            current_url = sso_url
            resp2 = None
            for _ in range(3):
                resp2 = await client.get(current_url)
                if resp2.status_code in (301, 302, 303, 307, 308) and "location" in resp2.headers:
                    current_url = urljoin(current_url, resp2.headers["location"])
                else:
                    break

            if resp2 is None or resp2.status_code >= 400:
                code = resp2.status_code if resp2 else "None"
                raise MonevAuthError(f"[Step 2] Gagal memuat halaman SSO Kemnaker (HTTP {code})")

            html_text = resp2.text
            csrf_match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
            if not csrf_match:
                csrf_match = re.search(r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
            if not csrf_match:
                raise MonevAuthError("[Step 2] Gagal mengekstrak CSRF token dari SSO Kemnaker")
            csrf_token = csrf_match.group(1)
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 2] Kesalahan koneksi ke SSO Kemnaker: {type(e).__name__}")

        # [Step 3] Post login credentials to SSO
        try:
            auth_headers = {
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "Referer": current_url,
                "Origin": SSO_BASE_URL,
            }
            payload = {"username": email, "password": password}
            resp3 = await client.post(f"{SSO_BASE_URL}/auth/login", json=payload, headers=auth_headers)

            if resp3.status_code in (401, 422) or resp3.status_code >= 400:
                raise MonevAuthError(f"[Step 3] Kredensial (email/password) Monev salah atau login ditolak (HTTP {resp3.status_code})")

            redirect_uri = None
            try:
                data3 = resp3.json()
                if isinstance(data3, dict):
                    inner3 = data3.get("data", {}) if isinstance(data3.get("data"), dict) else {}
                    redirect_uri = data3.get("redirect_uri") or inner3.get("redirect_uri")
            except Exception:
                pass

            if not redirect_uri and resp3.status_code in (301, 302, 303, 307, 308):
                redirect_uri = resp3.headers.get("location")

            if not redirect_uri or "code=" not in redirect_uri:
                resp_auth = await client.get(sso_url)
                if resp_auth.status_code in (301, 302, 303, 307, 308) and "location" in resp_auth.headers:
                    redirect_uri = resp_auth.headers["location"]
                elif "form" in resp_auth.text.lower() and "authorize" in resp_auth.text.lower():
                    resp_post_auth = await client.post(f"{SSO_BASE_URL}/auth", json={}, headers=auth_headers)
                    if resp_post_auth.status_code in (301, 302, 303, 307, 308):
                        redirect_uri = resp_post_auth.headers.get("location")
                    else:
                        try:
                            auth_json = resp_post_auth.json()
                            redirect_uri = auth_json.get("redirect_uri") or (auth_json.get("data", {}) or {}).get("redirect_uri")
                        except Exception:
                            pass

            if not redirect_uri or "code=" not in redirect_uri:
                raise MonevAuthError("[Step 3] Gagal mendapatkan URL otorisasi SSO (kode otorisasi tidak ditemukan)")
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 3] Kesalahan koneksi saat login SSO: {type(e).__name__}")

        # [Step 4] Exchange code for access_token
        try:
            client.cookies.update(initial_cookies)
            callback_url = redirect_uri
            if not callback_url.startswith("http"):
                callback_url = urljoin(MONEV_BASE_URL, redirect_uri)

            resp4 = await client.get(callback_url, headers={"Accept": "application/json"})
            if resp4.status_code >= 400:
                raise MonevAuthError(f"[Step 4] Gagal memanggil callback Monev API (HTTP {resp4.status_code})")

            token = None
            try:
                data4 = resp4.json()
                if isinstance(data4, dict):
                    inner4 = data4.get("data", {}) if isinstance(data4.get("data"), dict) else {}
                    token = (
                        data4.get("access_token") or data4.get("token")
                        or inner4.get("access_token") or inner4.get("token")
                    )
            except Exception:
                pass

            if not token:
                raise MonevAuthError("[Step 4] Gagal mengekstrak access_token dari respons callback Monev")
            return token
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 4] Kesalahan koneksi pada callback Monev: {type(e).__name__}")


async def get_valid_token(force_refresh: bool = False) -> str:
    """
    Get a valid Monev access token using credentials stored in KV.
    - Reads encrypted credentials from KV.
    - Returns cached token if available (unless force_refresh=True).
    - Performs login_monev() if no cached token, stores result back to KV.
    """
    creds = await kv_store.get_credentials()
    if not creds:
        raise ValueError("Pengguna belum terdaftar. Silakan gunakan perintah /daftar terlebih dahulu.")

    # Try cached token first
    if not force_refresh and creds.get("encrypted_token"):
        try:
            return decrypt_str(creds["encrypted_token"])
        except Exception:
            pass  # Invalid cached token, fall through to re-login

    # Decrypt credentials and authenticate
    try:
        email = creds["email"]
        password = decrypt_str(creds["encrypted_password"])
    except Exception:
        raise ValueError("Gagal mendekripsi kredensial. ENCRYPTION_KEY mungkin berubah.")

    token = await login_monev(email, password)

    # Store new token back to KV
    enc_token = encrypt_str(token)
    await kv_store.update_token(enc_token, int(time_module.time()))

    return token
