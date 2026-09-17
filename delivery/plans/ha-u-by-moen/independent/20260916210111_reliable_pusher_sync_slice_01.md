# Slice 01: Durable Passive Synchronization

## Goal and Outcome

Home Assistant can maintain a private Pusher subscription for every discovered
shower, survive idle periods and network loss, and recover current device state
without requiring a reload.

## Scope

- Split HTTP API concerns from a supervised Pusher transport.
- Obtain device-scoped credentials and private-channel authorization.
- Implement Pusher application heartbeat, reconnect, and resubscription.
- Send a read-only `do_shower_report` request after subscription/reconnection.
- Normalize and merge `state_change`, `shower_report`, and `boot` events.
- Use REST as bootstrap/fallback without replacing fresher push-owned fields.
- Integrate start/stop behavior with the Home Assistant config-entry lifecycle.

Control command behavior and entity refactoring are deferred to slice 02.
LAN control and preset configuration are not in scope.

## Dependencies and Ordering

This is the first slice. It depends only on the current cloud authentication and
device detail APIs. Slice 02 consumes its transport and coordinator interfaces.

## Entry Point and Behavior

Config-entry setup authenticates, performs the initial REST snapshot, registers
device subscriptions, and starts the Pusher supervisor. A subscription becomes
healthy only after `pusher_internal:subscription_succeeded`. The transport then
requests a full report. Incoming events update the coordinator. Idle or broken
connections are pinged, closed on pong timeout, reconnected with capped backoff,
reauthorized using the new socket ID, and resubscribed.

## State Transitions

- Disconnected -> connecting -> connected -> subscribed/healthy.
- Any socket/auth/subscription failure -> disconnected/retrying.
- Push events increment per-device freshness and merge only present fields.
- REST owns all fields before the first push snapshot and is full fallback while
  a channel is unhealthy; while healthy it may update only nonvolatile metadata.

## Authorization

Prefer APK-compatible v2 credentials/auth with `user_token` and
`serial_number`. Fall back to the existing v3 shape only for an unsupported v2
endpoint. Reauthenticate once on HTTP 401. Never log secrets or auth signatures.

## Validation and Recovery

- Reject malformed credential, connection, and event payloads without killing
  the supervisor.
- Reconnect indefinitely with capped exponential backoff and jitter.
- Cancel all receiver, heartbeat, and reconnect tasks on unload.
- Positive tests cover connect/subscribe/report/state update and heartbeat.
- Negative tests cover malformed events, auth failure, pong timeout, reconnect,
  reauthorization, stale REST, and unload during retry.

## Implementation Surfaces

- `custom_components/u_by_moen/api.py`
- New Pusher transport module under `custom_components/u_by_moen/`
- `custom_components/u_by_moen/coordinator.py` and config-entry setup
- New `tests/` fixtures and unit tests

## Required Validation

- Focused transport and coordinator tests.
- Python compilation for the integration and tests.
- Inspect logs/tests to confirm credentials and auth values are redacted.

## Acceptance Criteria

- The transport implements application ping/pong and reconnect/resubscribe.
- Every successful subscription issues a full-report request.
- State events update the correct device and preserve outlet metadata.
- `time_remaining` is stored under the correct key.
- A healthy push state is not regressed by stale REST polling.
- Unload leaves no active transport task.

## Commit Boundary

Commit this slice's plan, passive synchronization implementation, and focused
tests together after validation passes.
