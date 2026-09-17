"""Supervised Pusher transport for U by Moen."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .api import MoenApi, MoenApiError

_LOGGER = logging.getLogger(__name__)

EventCallback = Callable[[str, Any], Awaitable[None]]
TaskFactory = Callable[[Awaitable[None]], asyncio.Task[None]]


class MoenPusherError(Exception):
    """Base Pusher transport error."""


class MoenPusherNotReady(MoenPusherError):
    """Raised when a private channel is not subscribed."""


@dataclass(slots=True)
class PusherSubscription:
    """A desired private-channel subscription."""

    serial_number: str
    channel: str
    auth_version: int
    callback: EventCallback
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class _PusherConnection:
    """One supervised WebSocket for an app-key/cluster pair."""

    def __init__(
        self,
        api: MoenApi,
        session: aiohttp.ClientSession,
        app_key: str,
        cluster: str,
        create_task: TaskFactory,
    ) -> None:
        self._api = api
        self._session = session
        self._app_key = app_key
        self._cluster = cluster
        self._create_task = create_task
        self._subscriptions: dict[str, PusherSubscription] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._socket_id: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._send_lock = asyncio.Lock()
        self._report_id = 0

    def add_subscription(self, subscription: PusherSubscription) -> None:
        self._subscriptions[subscription.channel] = subscription

    def is_healthy(self, serial_number: str) -> bool:
        return any(
            sub.serial_number == serial_number and sub.ready.is_set()
            for sub in self._subscriptions.values()
        )

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = self._create_task(self._supervise())

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._mark_disconnected()

    def _mark_disconnected(self) -> None:
        self._socket_id = None
        for subscription in self._subscriptions.values():
            subscription.ready.clear()

    async def _supervise(self) -> None:
        attempt = 0
        while self._running:
            established = False
            try:
                await self._run_connection()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - supervisor must survive transport callbacks
                _LOGGER.warning("Pusher connection lost: %s", err)
            finally:
                established = self._socket_id is not None
                self._mark_disconnected()
                if self._ws is not None and not self._ws.closed:
                    await self._ws.close()
                self._ws = None

            if self._running:
                attempt = 1 if established else attempt + 1
                delay = min(30.0, float(attempt * attempt))
                delay += random.uniform(0, min(1.0, delay / 4))
                _LOGGER.debug(
                    "Retrying Pusher connection in %.1f seconds (attempt %d)",
                    delay,
                    attempt,
                )
                await asyncio.sleep(delay)

    async def _run_connection(self) -> None:
        url = f"wss://ws-{self._cluster}.pusher.com/app/{self._app_key}?protocol=7&client=python-client&version=1.0"
        _LOGGER.debug("Connecting to Pusher cluster %s", self._cluster)
        self._ws = await self._session.ws_connect(url)
        activity_timeout = 120.0
        last_activity = time.monotonic()
        ping_sent_at: float | None = None

        while self._running and not self._ws.closed:
            now = time.monotonic()
            timeout = max(
                0.1,
                (activity_timeout if ping_sent_at is None else 30.0)
                - (now - (last_activity if ping_sent_at is None else ping_sent_at)),
            )
            try:
                message = await self._ws.receive(timeout=timeout)
            except asyncio.TimeoutError:
                if ping_sent_at is not None:
                    raise MoenPusherError("Timed out waiting for Pusher pong")
                await self._send({"event": "pusher:ping"})
                ping_sent_at = time.monotonic()
                continue

            if message.type == aiohttp.WSMsgType.TEXT:
                last_activity = time.monotonic()
                # The Android client treats any inbound frame as proof of life.
                ping_sent_at = None
                _, negotiated_timeout = await self._handle_message(message.data)
                if negotiated_timeout is not None:
                    activity_timeout = negotiated_timeout
            elif message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                raise MoenPusherError("Pusher WebSocket closed")

    async def _handle_message(
        self, raw_message: str
    ) -> tuple[str | None, float | None]:
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError) as err:
            _LOGGER.debug("Ignoring malformed Pusher message: %s", err)
            return None, None
        if not isinstance(message, dict):
            return None, None

        event = message.get("event")
        data = message.get("data")
        negotiated_timeout: float | None = None
        if event == "pusher:connection_established":
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict) or not data.get("socket_id"):
                raise MoenPusherError("Pusher connection omitted socket_id")
            self._socket_id = str(data["socket_id"])
            if isinstance(data.get("activity_timeout"), (int, float)):
                negotiated_timeout = max(1.0, float(data["activity_timeout"]))
            _LOGGER.debug("Pusher connection established")
            for subscription in self._subscriptions.values():
                await self._subscribe(subscription)
        elif event == "pusher:ping":
            await self._send({"event": "pusher:pong"})
        elif event == "pusher:error":
            raise MoenPusherError("Pusher returned an error")
        elif event == "pusher_internal:subscription_succeeded":
            subscription = self._subscriptions.get(message.get("channel"))
            if subscription is not None:
                subscription.ready.set()
                _LOGGER.debug(
                    "Subscribed to Pusher updates for %s", subscription.serial_number
                )
                await self.request_report(subscription.serial_number)
                await subscription.callback(event, {})
        elif isinstance(event, str):
            subscription = self._subscriptions.get(message.get("channel"))
            if subscription is not None:
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        pass
                await subscription.callback(event, data)
        return event if isinstance(event, str) else None, negotiated_timeout

    async def _subscribe(self, subscription: PusherSubscription) -> None:
        if self._socket_id is None:
            raise MoenPusherNotReady("Pusher socket is not established")
        auth = await self._api.get_pusher_auth(
            subscription.channel,
            self._socket_id,
            subscription.serial_number,
            subscription.auth_version,
        )
        await self._send(
            {
                "event": "pusher:subscribe",
                "data": {"channel": subscription.channel, "auth": auth},
            }
        )

    async def _send(self, message: dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed:
            raise MoenPusherNotReady("Pusher WebSocket is disconnected")
        async with self._send_lock:
            await self._ws.send_json(message)

    def _find_subscription(self, serial_number: str) -> PusherSubscription:
        for subscription in self._subscriptions.values():
            if subscription.serial_number == serial_number:
                return subscription
        raise MoenPusherNotReady(f"No Pusher channel for {serial_number}")

    async def request_report(self, serial_number: str) -> None:
        subscription = self._find_subscription(serial_number)
        if not subscription.ready.is_set():
            raise MoenPusherNotReady("Pusher channel is not subscribed")
        self._report_id = (self._report_id + 1) % 1000
        payload = {
            "jsonrpc": "2.0",
            "method": "do_shower_report",
            "id": self._report_id,
        }
        await self._send(
            {
                "event": "client-command",
                "channel": subscription.channel,
                "data": json.dumps(payload, separators=(",", ":")),
            }
        )

    async def send_client_event(
        self,
        serial_number: str,
        event: str,
        payload: dict[str, Any],
        timeout: float = 10.0,
    ) -> None:
        subscription = self._find_subscription(serial_number)
        try:
            await asyncio.wait_for(subscription.ready.wait(), timeout=timeout)
        except asyncio.TimeoutError as err:
            raise MoenPusherNotReady("Pusher channel did not become ready") from err
        await self._send(
            {
                "event": event,
                "channel": subscription.channel,
                "data": json.dumps(payload, separators=(",", ":")),
            }
        )


class MoenPusherTransport:
    """Manage Pusher connections and device subscriptions for one account."""

    def __init__(
        self,
        api: MoenApi,
        session: aiohttp.ClientSession,
        create_task: TaskFactory | None = None,
    ) -> None:
        self._api = api
        self._session = session
        self._create_task = create_task or asyncio.create_task
        self._connections: dict[tuple[str, str], _PusherConnection] = {}
        self._serial_connections: dict[str, _PusherConnection] = {}

    async def register_device(
        self, device_details: dict[str, Any], callback: EventCallback
    ) -> None:
        serial_number = device_details.get("serial_number")
        if not isinstance(serial_number, str) or not serial_number:
            raise MoenApiError("Device detail omitted serial_number")
        credentials = await self._api.get_pusher_credentials(serial_number)
        channel_id = credentials.get("channel") or device_details.get("channel")
        if not isinstance(channel_id, str) or not channel_id:
            raise MoenApiError("Pusher credentials omitted channel")
        channel = (
            channel_id if channel_id.startswith("private-") else f"private-{channel_id}"
        )
        key = (str(credentials["app_key"]), str(credentials["cluster"]))
        connection = self._connections.get(key)
        if connection is None:
            connection = _PusherConnection(
                self._api, self._session, key[0], key[1], self._create_task
            )
            self._connections[key] = connection
        connection.add_subscription(
            PusherSubscription(
                serial_number,
                channel,
                int(credentials.get("auth_version", 3)),
                callback,
            )
        )
        self._serial_connections[serial_number] = connection

    def start(self) -> None:
        for connection in self._connections.values():
            connection.start()

    async def stop(self) -> None:
        await asyncio.gather(
            *(connection.stop() for connection in self._connections.values()),
            return_exceptions=True,
        )

    def is_healthy(self, serial_number: str) -> bool:
        connection = self._serial_connections.get(serial_number)
        return connection is not None and connection.is_healthy(serial_number)

    async def request_report(self, serial_number: str) -> None:
        connection = self._serial_connections.get(serial_number)
        if connection is None:
            raise MoenPusherNotReady(f"No Pusher connection for {serial_number}")
        await connection.request_report(serial_number)

    async def send_client_event(
        self, serial_number: str, event: str, payload: dict[str, Any]
    ) -> None:
        connection = self._serial_connections.get(serial_number)
        if connection is None:
            raise MoenPusherNotReady(f"No Pusher connection for {serial_number}")
        await connection.send_client_event(serial_number, event, payload)
