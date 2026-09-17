# Slice 02: Reliable APK-Compatible Controls

## Goal and Outcome

Existing Home Assistant climate, switch, and preset-button actions emit the
same control messages as Android 2.5.0, surface failures, and reconcile their
optimistic state with confirmed device state.

## Scope

- Central coordinator command entry point.
- APK-compatible wire payloads for power, resume, preset activation,
  temperature, and outlets.
- Bounded optimistic state and report/REST confirmation fallback.
- Entity refactoring to remove duplicate detail fetches and payload building.
- Documentation, dependency cleanup, CI test execution, and full validation.

Preset configuration and live physical control testing are not in scope.

## Dependencies and Ordering

Requires slice 01's healthy-channel transport, full-report request, state merge,
and typed transport failures.

## Entry Point and Behavior

An entity calls the coordinator command API. The coordinator waits for a
subscribed channel, sends an APK-compatible JSON-string client event, applies a
bounded optimistic patch, and waits for a newer device event. If confirmation
does not arrive, it requests a shower report, then falls back to REST. Failure is
reported to Home Assistant and optimistic state is reverted.

## Data and Commands

- Power-on/resume: `shower_on` with `{}`.
- Power-off: `shower_off` with no `params` member.
- Presets 1-2: `shower_on` with integer `preset`.
- Presets above 2: `shower_set` with the complete preset definition.
- Temperature: integer `target_temperature`.
- Outlets: full ordered outlet records preserving icon metadata.
- Pusher outer `data` is always a JSON-encoded string.

## Authorization

Commands require a healthy authenticated private-channel subscription. There is
no Home Assistant authorization change; existing entity/service permissions
continue to apply.

## Validation and Recovery

- Reject unknown presets, invalid temperature, missing channels, and malformed
  outlet state without sending.
- Positive wire tests cover every command and both preset branches.
- Negative tests cover disconnected channels, send failures, confirmation
  timeout, report timeout, REST fallback, and optimistic rollback.
- No test may contact or mutate the live shower.

## Implementation Surfaces

- Coordinator and Pusher transport command interfaces
- Climate, switch, and button entities
- Tests, README, dependency metadata, and CI configuration if required

## Required Validation

- Focused command/entity tests.
- Complete unit suite.
- Python compilation.
- Hassfest/HACS-compatible static validation available locally.
- Passive live checks only when credentials/runtime are locally available; no
  power, preset, temperature, or outlet command is permitted.

## Acceptance Criteria

- Wire fixtures exactly match APK-derived messages.
- Command failures are visible to Home Assistant.
- Optimistic state cannot remain indefinitely.
- Existing entity unique IDs and configuration remain unchanged.
- README accurately describes real-time synchronization and limitations.
- Full available validation passes.

## Commit Boundary

Commit control behavior, tests, documentation, and dependency cleanup together
after full validation passes.
