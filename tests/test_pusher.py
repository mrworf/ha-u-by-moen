"""Tests for the supervised Pusher protocol implementation."""

import asyncio
import json

import pytest

from custom_components.u_by_moen.pusher import (
    MoenPusherNotReady,
    PusherSubscription,
    _PusherConnection,
)


class FakeApi:
    """Minimal API double for private-channel authorization."""

    def __init__(self) -> None:
        self.auth_calls = []

    async def get_pusher_auth(self, channel, socket_id, serial_number, version):
        self.auth_calls.append((channel, socket_id, serial_number, version))
        return "signed-auth"


class FakeWebSocket:
    """Capture outbound Pusher frames."""

    closed = False

    def __init__(self) -> None:
        self.messages = []

    async def send_json(self, message) -> None:
        self.messages.append(message)

    async def close(self) -> None:
        self.closed = True


def make_connection():
    api = FakeApi()
    connection = _PusherConnection(
        api,
        object(),
        "app-key",
        "cluster",
        asyncio.create_task,
    )
    websocket = FakeWebSocket()
    connection._ws = websocket
    return connection, api, websocket


@pytest.mark.asyncio
async def test_connection_subscribes_and_requests_report() -> None:
    connection, api, websocket = make_connection()
    received = []

    async def callback(event, data):
        received.append((event, data))

    subscription = PusherSubscription("SERIAL", "private-channel", 2, callback)
    connection.add_subscription(subscription)

    event, timeout = await connection._handle_message(
        json.dumps(
            {
                "event": "pusher:connection_established",
                "data": json.dumps({"socket_id": "1.2", "activity_timeout": 45}),
            }
        )
    )

    assert event == "pusher:connection_established"
    assert timeout == 45
    assert api.auth_calls == [("private-channel", "1.2", "SERIAL", 2)]
    assert websocket.messages == [
        {
            "event": "pusher:subscribe",
            "data": {"channel": "private-channel", "auth": "signed-auth"},
        }
    ]

    await connection._handle_message(
        json.dumps(
            {
                "event": "pusher_internal:subscription_succeeded",
                "channel": "private-channel",
                "data": "{}",
            }
        )
    )

    assert subscription.ready.is_set()
    report = websocket.messages[-1]
    assert report["event"] == "client-command"
    assert report["channel"] == "private-channel"
    assert json.loads(report["data"])["method"] == "do_shower_report"
    assert received == [("pusher_internal:subscription_succeeded", {})]


@pytest.mark.asyncio
async def test_server_ping_gets_pong_and_state_is_decoded() -> None:
    connection, _, websocket = make_connection()
    received = []

    async def callback(event, data):
        received.append((event, data))

    subscription = PusherSubscription("SERIAL", "private-channel", 2, callback)
    subscription.ready.set()
    connection.add_subscription(subscription)

    await connection._handle_message(json.dumps({"event": "pusher:ping"}))
    await connection._handle_message(
        json.dumps(
            {
                "event": "client-state-reported",
                "channel": "private-channel",
                "data": json.dumps({"type": "state_change", "data": {}}),
            }
        )
    )

    assert websocket.messages == [{"event": "pusher:pong"}]
    assert received == [("client-state-reported", {"type": "state_change", "data": {}})]


@pytest.mark.asyncio
async def test_malformed_message_is_ignored_and_disconnected_send_fails() -> None:
    connection, _, _ = make_connection()
    assert await connection._handle_message("not-json") == (None, None)

    connection._ws = None
    with pytest.raises(MoenPusherNotReady):
        await connection._send({"event": "client-test"})


@pytest.mark.asyncio
async def test_client_event_outer_data_is_a_json_string() -> None:
    connection, _, websocket = make_connection()

    async def callback(_event, _data):
        pass

    subscription = PusherSubscription("SERIAL", "private-channel", 2, callback)
    subscription.ready.set()
    connection.add_subscription(subscription)
    payload = {"type": "control", "data": {"action": "shower_off"}}

    await connection.send_client_event("SERIAL", "client-state-desired", payload)

    message = websocket.messages[-1]
    assert message["event"] == "client-state-desired"
    assert isinstance(message["data"], str)
    assert json.loads(message["data"]) == payload
