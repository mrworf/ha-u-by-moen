# Reliable Pusher Synchronization

Product ID: `ha-u-by-moen`

Parent commit: `9e020f8016e5e5ff5ff81bdb0f9ea67505cb8dd5`

## Goal

Keep the Home Assistant integration synchronized with U by Moen controllers by
matching the supplied Android 2.5.0 APK's cloud and Pusher protocol, while
retaining REST as bootstrap and fallback.

## Scope

- Supervised Pusher heartbeat, reconnect, reauthentication, and resubscription.
- Device-scoped v2 credentials/authentication with current v3 compatibility.
- Full shower-report recovery after subscription and reconnection.
- Correct partial state merging and protection from stale REST data.
- APK-compatible preset activation and shower control wire messages.
- Typed failures, bounded optimistic state, redacted diagnostics, tests, and
  documentation.

Preset creation/edit/delete/reorder and legacy LAN control are explicitly out
of scope. No live shower-mutating command will be sent during this delivery.

## Slices

1. [Slice 01: Durable passive synchronization](20260916210111_reliable_pusher_sync_slice_01.md)
2. [Slice 02: Reliable APK-compatible controls](20260916210111_reliable_pusher_sync_slice_02.md)

## Acceptance

- Automated tests prove the APK-derived HTTP and Pusher wire contracts.
- Idle connections remain healthy or reconnect and resubscribe automatically.
- Initial/reconnected subscriptions request a full shower report.
- Push state cannot be overwritten by an older REST snapshot while healthy.
- Existing entities and unique IDs remain compatible.
- All repository validation passes without staging the pre-existing `apks/`
  directory.
