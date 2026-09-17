"""Tests for APK-compatible Moen HTTP requests."""

import pytest

from custom_components.u_by_moen.api import MoenApi


class FakeResponse:
    """Async response context manager."""

    def __init__(self, status, payload=None) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError(f"Unexpected HTTP {self.status}")

    async def json(self):
        return self.payload


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
