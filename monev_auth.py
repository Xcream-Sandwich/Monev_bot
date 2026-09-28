import logging
import re
from urllib.parse import urlparse, parse_qs, urljoin
import httpx
import config
from storage import (
    get_cached_token,
    save_cached_token,
    get_user_credentials,
)

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
        # ==========================================
        # [Step 1] Initiate login on Monev API
        # ==========================================
        try:
            step1_url = f"{MONEV_BASE_URL}/api/v1/auth/login"
            resp1 = await client.get(step1_url)
            
            sso_url = None
            if resp1.status_code in (301, 302, 303, 307, 308) and "location" in resp1.headers:
                sso_url = resp1.headers["location"]
            elif resp1.status_code == 200:
                try:
                    data = resp1.json()
                    sso_url = data.get("url") or (data.get("data", {}) if isinstance(data.get("data"), dict) else {}).get("url")
                except Exception:
                    pass
            
            if not sso_url:
                raise MonevAuthError(f"[Step 1] Gagal mendapatkan URL SSO dari Monev API (HTTP {resp1.status_code})")
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 1] Kesalahan koneksi ke Monev API: {type(e).__name__}")
        
        # Save initial cookies from Step 1
        initial_cookies = dict(client.cookies)

        # ==========================================
        # [Step 2] Fetch SSO page and extract CSRF token
        # ==========================================
        try:
            current_url = sso_url
            resp2 = None
            # Follow redirects manually up to 3 times while accumulating cookies
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
                # Try finding in input tag
                csrf_match = re.search(r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
            
            if not csrf_match:
                raise MonevAuthError("[Step 2] Gagal mengekstrak CSRF token dari SSO Kemnaker")
            
            csrf_token = csrf_match.group(1)
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 2] Kesalahan koneksi ke SSO Kemnaker: {type(e).__name__}")

        # ==========================================
        # [Step 3] Post login credentials to SSO
        # ==========================================
        try:
            auth_headers = {
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "Referer": current_url,
                "Origin": SSO_BASE_URL,
            }
            payload = {
                "username": email,
                "password": password,
            }
            resp3 = await client.post(f"{SSO_BASE_URL}/auth/login", json=payload, headers=auth_headers)
            
            if resp3.status_code in (401, 422) or resp3.status_code >= 400:
                raise MonevAuthError(f"[Step 3] Kredensial (email/password) Monev salah atau login ditolak (HTTP {resp3.status_code})")
            
            redirect_uri = None
            try:
                data3 = resp3.json()
                if isinstance(data3, dict):
                    redirect_uri = data3.get("redirect_uri") or (data3.get("data", {}) if isinstance(data3.get("data"), dict) else {}).get("redirect_uri")
            except Exception:
                pass
            
            if not redirect_uri and resp3.status_code in (301, 302, 303, 307, 308):
                redirect_uri = resp3.headers.get("location")

            # If redirect_uri is missing or doesn't contain code=, handle SSO authorize
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
                            redirect_uri = auth_json.get("redirect_uri") or auth_json.get("data", {}).get("redirect_uri")
                        except Exception:
                            pass

            if not redirect_uri or "code=" not in redirect_uri:
                raise MonevAuthError("[Step 3] Gagal mendapatkan URL otorisasi SSO (kode otorisasi tidak ditemukan)")
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 3] Kesalahan koneksi saat login SSO: {type(e).__name__}")

        # ==========================================
        # [Step 4] Exchange code for access_token on callback
        # ==========================================
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
                    token = (
                        data4.get("access_token")
                        or data4.get("token")
                        or (data4.get("data", {}) if isinstance(data4.get("data"), dict) else {}).get("access_token")
                        or (data4.get("data", {}) if isinstance(data4.get("data"), dict) else {}).get("token")
                    )
            except Exception:
                pass
            
            if not token:
                raise MonevAuthError("[Step 4] Gagal mengekstrak access_token dari respons callback Monev")
            
            return token
        except httpx.RequestError as e:
            raise MonevAuthError(f"[Step 4] Kesalahan koneksi pada callback Monev: {type(e).__name__}")


async def get_valid_token(
    telegram_id: int | str | None = None,
    email: str | None = None,
    password: str | None = None,
    force_refresh: bool = False,
) -> str:
    """
    Get a valid access token.
    If telegram_id is provided, check user cache from storage.
    If email and password are provided (or in config for Actions mode), authenticate directly.
    """
    if telegram_id:
        tid = str(telegram_id)
        if not force_refresh:
            cached = get_cached_token(tid)
            if cached:
                return cached
        
        creds = get_user_credentials(tid)
        if not creds:
            raise ValueError("Pengguna belum terdaftar. Silakan gunakan perintah /daftar terlebih dahulu.")
        
        u_email, u_password = creds
        token = await login_monev(u_email, u_password)
        save_cached_token(tid, token)
        return token

    # Fallback to direct credentials (e.g., GitHub Actions mode)
    target_email = email or config.MONEV_EMAIL
    target_password = password or config.MONEV_PASSWORD
    if not target_email or not target_password:
        raise ValueError("Kredensial MONEV_EMAIL atau MONEV_PASSWORD belum diatur.")
    
    return await login_monev(target_email, target_password)
