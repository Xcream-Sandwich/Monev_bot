import pytest
import httpx
import config
from crypto import generate_key
from storage import save_user
from monev_auth import login_monev, MonevAuthError
from monev_api import get_home_status, submit_attendance_and_log

_orig_async_client = httpx.AsyncClient


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    dummy_key = generate_key()
    monkeypatch.setattr(config, "ENCRYPTION_KEY", dummy_key)
    monkeypatch.setattr(config, "USERS_STORE_FILE", tmp_path / "users_store.json")
    monkeypatch.setattr(config, "DAILY_POINTS_FILE", tmp_path / "daily_points.json")
    monkeypatch.setattr(config, "AUTO_STATE_FILE", tmp_path / "auto_state.json")
    monkeypatch.setattr(config, "SUBMIT_HISTORY_FILE", tmp_path / "submit_history.json")


@pytest.mark.asyncio
async def test_login_monev_flow_success(monkeypatch):
    """Test 4-step raw HTTP login with mock responses."""
    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            
            # Step 1: GET /api/v1/auth/login
            if "monev-api.maganghub.kemnaker.go.id/api/v1/auth/login" in url_str and "callback" not in url_str:
                return httpx.Response(
                    302,
                    headers={
                        "location": "https://account.kemnaker.go.id/auth/sso-login?client_id=monev",
                        "set-cookie": "monev_init_session=session123; Path=/",
                    },
                )
            
            # Step 2: GET SSO page
            if "account.kemnaker.go.id/auth/sso-login" in url_str:
                html_body = '<html><head><meta name="csrf-token" content="mock-csrf-token-12345"></head></html>'
                return httpx.Response(200, text=html_body, headers={"content-type": "text/html"})
            
            # Step 3: POST /auth/login
            if "account.kemnaker.go.id/auth/login" in url_str:
                return httpx.Response(
                    200,
                    json={"data": {"redirect_uri": "https://monev-api.maganghub.kemnaker.go.id/api/v1/auth/login/callback?code=mock_code&state=mock_state"}},
                )
            
            # Step 4: GET callback
            if "api/v1/auth/login/callback" in url_str:
                return httpx.Response(
                    200,
                    json={"data": {"access_token": "valid-jwt-token-maganghub"}},
                )
            
            return httpx.Response(404)

    def mock_client_factory(*args, **kwargs):
        kwargs["transport"] = MockTransport()
        return _orig_async_client(*args, **kwargs)

    monkeypatch.setattr("monev_auth.httpx.AsyncClient", mock_client_factory)

    token = await login_monev("user@test.com", "mypassword")
    assert token == "valid-jwt-token-maganghub"


@pytest.mark.asyncio
async def test_login_monev_step3_invalid_credentials(monkeypatch):
    """Test login failure on step 3."""
    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "monev-api.maganghub.kemnaker.go.id/api/v1/auth/login" in url_str and "callback" not in url_str:
                return httpx.Response(302, headers={"location": "https://account.kemnaker.go.id/auth/sso"})
            if "account.kemnaker.go.id/auth/sso" in url_str:
                return httpx.Response(200, text='<meta name="csrf-token" content="csrf">')
            if "account.kemnaker.go.id/auth/login" in url_str:
                return httpx.Response(422, json={"message": "Unauthenticated"})
            return httpx.Response(404)

    def mock_client_factory(*args, **kwargs):
        kwargs["transport"] = MockTransport()
        return _orig_async_client(*args, **kwargs)

    monkeypatch.setattr("monev_auth.httpx.AsyncClient", mock_client_factory)

    with pytest.raises(MonevAuthError) as exc_info:
        await login_monev("user@test.com", "wrongpass")
    
    assert "[Step 3]" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_home_status_and_submit(monkeypatch):
    user_id = 777
    save_user(user_id, "user@test.com", "pass123", cached_token="cached-token-123")

    class MockApiTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            auth_hdr = request.headers.get("Authorization", "")
            assert auth_hdr == "Bearer cached-token-123"

            if "/api/v1/users/me/home" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "date": "2026-09-28",
                            "has_attendance": False,
                            "is_holiday": False,
                            "is_scheduled_off_day": False,
                        }
                    },
                )
            if "/api/v1/attendances/with-daily-log" in url_str:
                return httpx.Response(201, json={"message": "Attendance created successfully"})
            return httpx.Response(404)

    def mock_api_client_factory(*args, **kwargs):
        kwargs["transport"] = MockApiTransport()
        return _orig_async_client(*args, **kwargs)

    monkeypatch.setattr("monev_api.httpx.AsyncClient", mock_api_client_factory)

    status = await get_home_status(user_id)
    assert status["has_attendance"] is False
    assert status["date"] == "2026-09-28"

    result = await submit_attendance_and_log(
        telegram_id=user_id,
        activity_log="A"*100,
        lesson_learned="B"*100,
        obstacles="C"*100,
        date_str="2026-09-28",
    )
    assert result["success"] is True
    assert result["status_code"] == 201
