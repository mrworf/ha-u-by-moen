"""HTTP API client for U by Moen."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_AUTHENTICATE, API_BASE_URL, API_SHOWER_DETAIL, API_SHOWERS

_LOGGER = logging.getLogger(__name__)


class MoenApiError(Exception):
    """Base exception for Moen API errors."""


class MoenAuthError(MoenApiError):
    """Exception for authentication errors."""


class MoenApiHttpError(MoenApiError):
    """HTTP error returned by the U by Moen API."""

    def __init__(self, path: str, status: int) -> None:
        super().__init__(f"U by Moen request to {path} returned HTTP {status}")
        self.status = status


class MoenApi:
    """HTTP API client for U by Moen devices."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession):
        self._email = email
        self._password = password
        self._session = session
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    @property
    def token(self) -> str | None:
        """Return the current user token without exposing it to logs."""
        return self._token

    async def authenticate(self) -> str:
        """Authenticate with the cloud API."""
        async with self._auth_lock:
            try:
                async with self._session.get(
                    f"{API_BASE_URL}{API_AUTHENTICATE}",
                    params={"email": self._email, "password": self._password},
                ) as response:
                    if response.status in (401, 403):
                        raise MoenAuthError("Invalid U by Moen credentials")
                    response.raise_for_status()
                    data = await response.json()
            except MoenAuthError:
                raise
            except (aiohttp.ClientError, ValueError) as err:
                raise MoenAuthError("Authentication failed") from err

            token = data.get("token")
            if not isinstance(token, str) or not token:
                raise MoenAuthError("Authentication response did not contain a token")
            self._token = token
            _LOGGER.debug("Authenticated with the U by Moen API")
            return token

    async def _ensure_token(self) -> str:
        if self._token is None:
            return await self.authenticate()
        return self._token

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
        allow_empty: bool = False,
    ) -> Any:
        """Make an authenticated JSON request, refreshing once after a 401."""
        token = await self._ensure_token()
        request_headers = dict(headers or {})
        if "User-Token" not in request_headers:
            request_headers["User-Token"] = token
        elif not request_headers["User-Token"]:
            request_headers.pop("User-Token")

        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                headers=request_headers,
                params=params,
                data=data,
                json=json_body,
            ) as response:
                if response.status == 401 and retry_auth:
                    self._token = None
                    refreshed_token = await self.authenticate()
                    retry_params = dict(params) if params is not None else None
                    retry_data = dict(data) if data is not None else None
                    if retry_params is not None and "user_token" in retry_params:
                        retry_params["user_token"] = refreshed_token
                    if retry_data is not None and "user_token" in retry_data:
                        retry_data["user_token"] = refreshed_token
                    return await self._request_json(
                        method,
                        path,
                        headers=headers,
                        params=retry_params,
                        data=retry_data,
                        json_body=json_body,
                        retry_auth=False,
                        allow_empty=allow_empty,
                    )
                if response.status in (401, 403):
                    raise MoenAuthError("U by Moen authorization failed")
                if response.status >= 400:
                    raise MoenApiHttpError(path, response.status)
                if response.status == 204 or allow_empty:
                    return None
                return await response.json()
        except (MoenAuthError, MoenApiHttpError):
            raise
        except (aiohttp.ClientError, ValueError) as err:
            raise MoenApiError(f"U by Moen request failed for {path}") from err

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get the account's showers."""
        devices = await self._request_json("GET", API_SHOWERS)
        if not isinstance(devices, list):
            raise MoenApiError("Showers response was not a list")
        return devices

    async def get_device_details(self, serial_number: str) -> dict[str, Any]:
        """Get detailed information for one shower."""
        details = await self._request_json(
            "GET", API_SHOWER_DETAIL.format(serial_number)
        )
        if not isinstance(details, dict):
            raise MoenApiError("Shower detail response was not an object")
        return details

    async def get_pusher_credentials(self, serial_number: str) -> dict[str, Any]:
        """Get device-scoped Pusher credentials, with legacy v3 fallback."""
        token = await self._ensure_token()
        try:
            credentials = await self._request_json(
                "GET",
                "/v2/credentials",
                headers={"User-Token": ""},
                params={"user_token": token, "serial_number": serial_number},
            )
            auth_version = 2
        except MoenApiHttpError as err:
            if err.status not in (404, 405):
                raise MoenApiError("Failed to get Pusher credentials") from err
            credentials = await self._request_json("GET", "/v3/credentials")
            auth_version = 3

        if not isinstance(credentials, dict):
            raise MoenApiError("Pusher credentials response was not an object")
        if not credentials.get("app_key") or not credentials.get("cluster"):
            raise MoenApiError("Pusher credentials were incomplete")
        return {**credentials, "auth_version": auth_version}

    async def get_pusher_auth(
        self,
        channel_name: str,
        socket_id: str,
        serial_number: str,
        auth_version: int,
    ) -> str:
        """Authorize a device's private Pusher channel."""
        token = await self._ensure_token()
        form: dict[str, Any] = {"channel_name": channel_name, "socket_id": socket_id}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if auth_version == 2:
            form.update({"user_token": token, "serial_number": serial_number})
            headers["User-Token"] = ""
            path = "/v2/pusher-auth"
        else:
            path = "/v3/pusher-auth"

        auth_data = await self._request_json("POST", path, headers=headers, data=form)
        auth = auth_data.get("auth") if isinstance(auth_data, dict) else None
        if not isinstance(auth, str) or not auth:
            raise MoenApiError("Pusher authorization response was incomplete")
        return auth

    async def ensure_mobile_pusher_capability(
        self, device_details: dict[str, Any]
    ) -> None:
        """Mirror the Android app's idempotent mobile Pusher capability setup."""
        capabilities = {
            item.get("name")
            for item in device_details.get("capabilities", [])
            if isinstance(item, dict)
        }
        if "pusher_hmi" not in capabilities or "mobile_supports_pusher" in capabilities:
            return
        shower_token = device_details.get("token")
        if not shower_token:
            return
        try:
            await self._request_json(
                "POST",
                "/v2/capabilities",
                headers={"Shower-Token": shower_token, "User-Token": ""},
                params={"name": "mobile_supports_pusher"},
                allow_empty=True,
            )
        except MoenApiError as err:
            _LOGGER.debug("Could not register mobile Pusher capability: %s", err)

    async def update_presets(
        self,
        serial_number: str,
        device_details: dict[str, Any],
        presets: list[dict[str, Any]],
    ) -> None:
        """Replace a shower's complete cloud preset list."""
        await self._request_json(
            "PATCH",
            f"/v4/showers/{serial_number}",
            json_body={
                "shower": {
                    "api_server": device_details.get("api_server"),
                    "active": True,
                    "name": device_details.get("name"),
                    "presets": presets,
                }
            },
            allow_empty=True,
        )

    async def delete_preset(self, serial_number: str, position: int) -> None:
        """Delete one cloud preset using its current position."""
        await self._request_json(
            "DELETE",
            f"/v2/showers/{serial_number}/presets/{position}",
            allow_empty=True,
        )
