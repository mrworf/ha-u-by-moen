"""Tests for APK-compatible Moen HTTP requests."""

import json

import aiohttp
import pytest

from custom_components.u_by_moen.api import (
    MoenApi,
    MoenApiError,
    MoenApiHttpError,
    MoenAuthError,
)


class FakeResponse:
    """Async response context manager."""

    def __init__(self, status, payload=None, headers=None) -> None:
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError(f"Unexpected HTTP {self.status}")

    async def json(self):
        return self.payload

    async def text(self, **_kwargs):
        if self.payload is None:
            return ""
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


class FakeSession:
    """Queue responses and retain sanitized request structure for assertions."""

    def __init__(self, requests, auth=None) -> None:
        self.responses = list(requests)
        self.auth = list(auth or [])
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.auth.pop(0)


class FailingSession:
    """Raise a transport error without exposing its message downstream."""

    def request(self, *_args, **_kwargs):
        raise aiohttp.ClientConnectionError("private transport details")


@pytest.mark.asyncio
async def test_v2_credentials_and_auth_match_android_shape() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"app_key": "key", "cluster": "us2", "channel": "abc"},
            ),
            FakeResponse(200, {"auth": "signature"}),
        ]
    )
    api = MoenApi("user@example.com", "secret", session)
    api._token = "user-token"

    credentials = await api.get_pusher_credentials("SERIAL")
    signature = await api.get_pusher_auth("private-abc", "1.2", "SERIAL", 2)

    assert credentials["auth_version"] == 2
    assert signature == "signature"
    credential_call = session.calls[0][2]
    assert credential_call["params"] == {
        "user_token": "user-token",
        "serial_number": "SERIAL",
    }
    assert "User-Token" not in credential_call["headers"]
    auth_call = session.calls[1][2]
    assert auth_call["data"] == {
        "channel_name": "private-abc",
        "socket_id": "1.2",
        "user_token": "user-token",
        "serial_number": "SERIAL",
    }


@pytest.mark.asyncio
async def test_401_refresh_replaces_user_token_in_query() -> None:
    session = FakeSession(
        [
            FakeResponse(401),
            FakeResponse(
                200,
                {"app_key": "key", "cluster": "us2", "channel": "abc"},
            ),
        ],
        auth=[FakeResponse(200, {"token": "new-token"})],
    )
    api = MoenApi("user@example.com", "secret", session)
    api._token = "expired-token"

    await api.get_pusher_credentials("SERIAL")

    assert session.calls[-1][2]["params"]["user_token"] == "new-token"


@pytest.mark.asyncio
async def test_capability_registration_accepts_empty_success() -> None:
    session = FakeSession([FakeResponse(200)])
    api = MoenApi("user@example.com", "secret", session)
    api._token = "user-token"

    await api.ensure_mobile_pusher_capability(
        {
            "token": "shower-token",
            "capabilities": [{"name": "pusher_hmi"}],
        }
    )

    call = session.calls[0][2]
    assert call["params"] == {"name": "mobile_supports_pusher"}
    assert call["headers"] == {"Shower-Token": "shower-token"}


@pytest.mark.asyncio
async def test_preset_update_and_delete_match_android_endpoints() -> None:
    session = FakeSession([FakeResponse(204), FakeResponse(204)])
    api = MoenApi("user@example.com", "secret", session)
    api._token = "user-token"
    presets = [{"position": 1, "title": "One"}]

    await api.update_presets(
        "SERIAL",
        {"api_server": "server", "name": "Main"},
        presets,
        "create",
    )
    await api.delete_preset("SERIAL", 3)

    patch = session.calls[0]
    assert patch[0] == "PATCH"
    assert patch[1].endswith("/v4/showers/SERIAL")
    assert patch[2]["json"] == {
        "shower": {
            "api_server": "server",
            "active": True,
            "name": "Main",
            "presets": [
                {
                    "outlets": [],
                    "position": 1,
                    "ready_pauses_water": False,
                    "ready_pushes_notification": False,
                    "ready_sounds_alert": True,
                    "target_temperature": 0,
                    "timer_enabled": False,
                    "timer_ends_shower": False,
                    "timer_length": 0,
                    "timer_sounds_alert": True,
                    "title": "One",
                }
            ],
            "ready_sounds_alert": False,
            "single_outlet_mode": False,
            "source": "android",
            "useCelsius": False,
        }
    }
    delete = session.calls[1]
    assert delete[0] == "DELETE"
    assert delete[1].endswith("/v2/showers/SERIAL/presets/3")


@pytest.mark.asyncio
async def test_http_error_retains_sanitized_response_context() -> None:
    response = {
        "error": "Preset payload rejected for user@example.com with Bearer abc123",
        "token": "user-token",
        "nested": {
            "password": "password-value",
            "authorization": "auth-value",
            "client_secret": "secret-value",
            "credentials": ["credential-value"],
        },
    }
    session = FakeSession(
        [
            FakeResponse(
                422,
                response,
                headers={"X-Request-ID": "request-123"},
            )
        ]
    )
    api = MoenApi("user@example.com", "secret", session)
    api._token = "user-token"

    with pytest.raises(MoenApiHttpError) as raised:
        await api.update_presets(
            "SERIAL",
            {"api_server": "server", "name": "Main"},
            [{"position": 1, "title": "Private title"}],
            "edit",
        )

    error = raised.value
    rendered = str(error)
    assert error.method == "PATCH"
    assert error.path == "/v4/showers/SERIAL"
    assert error.status == 422
    assert error.request_id == "request-123"
    assert "Preset payload rejected" in rendered
    assert "<redacted-email>" in rendered
    assert "Bearer <redacted>" in rendered
    assert rendered.count("<redacted>") >= 5
    for private_value in (
        "user@example.com",
        "abc123",
        "user-token",
        "password-value",
        "auth-value",
        "secret-value",
        "credential-value",
        "Private title",
    ):
        assert private_value not in rendered


@pytest.mark.asyncio
async def test_non_json_error_is_normalized_redacted_and_truncated() -> None:
    body = "password=hunter2\nAuthorization: Bearer secret-value " + "x" * 3000
    session = FakeSession([FakeResponse(500, body)])
    api = MoenApi("user@example.com", "secret", session)
    api._token = "user-token"

    with pytest.raises(MoenApiHttpError) as raised:
        await api.delete_preset("SERIAL", 3)

    error = raised.value
    assert error.method == "DELETE"
    assert error.status == 500
    assert "\n" not in error.response_body
    assert "<redacted>" in error.response_body
    assert error.response_body.endswith("...<truncated>")
    assert "hunter2" not in str(error)
    assert "secret-value" not in str(error)


@pytest.mark.asyncio
async def test_transport_error_identifies_request_without_private_message() -> None:
    api = MoenApi("user@example.com", "secret", FailingSession())
    api._token = "user-token"

    with pytest.raises(MoenApiError) as raised:
        await api.delete_preset("SERIAL", 3)

    rendered = str(raised.value)
    assert "DELETE /v2/showers/SERIAL/presets/3" in rendered
    assert "ClientConnectionError" in rendered
    assert "private transport details" not in rendered


@pytest.mark.asyncio
async def test_authorization_error_retains_only_sanitized_context() -> None:
    session = FakeSession(
        [
            FakeResponse(
                403,
                {"error": "denied", "authorization": "private-auth"},
            )
        ]
    )
    api = MoenApi("user@example.com", "secret", session)
    api._token = "user-token"

    with pytest.raises(MoenAuthError) as raised:
        await api.delete_preset("SERIAL", 3)

    rendered = str(raised.value)
    assert "DELETE /v2/showers/SERIAL/presets/3 returned HTTP 403" in rendered
    assert '"authorization":"<redacted>"' in rendered
    assert "private-auth" not in rendered
