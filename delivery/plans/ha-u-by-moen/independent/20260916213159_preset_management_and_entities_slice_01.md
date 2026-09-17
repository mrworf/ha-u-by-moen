# Slice 01: Preset Management and Dynamic Controls

## Goal and Outcome

A user can open the integration's Configure flow for a shower, create, edit,
delete, or move presets, and immediately see the correct activation buttons.
Cloud changes are protected against ordinary concurrent edits and controller
presets 1-2 are synchronized without activating water.

## Scope

- Native multi-step options flow with device selection where necessary.
- Full Android-equivalent preset fields and validation.
- APK-derived REST PATCH/DELETE operations and state refresh.
- Stale-form detection and per-device mutation serialization.
- Pusher `type=preset` synchronization, verification, and retry state.
- Dynamic addition, update, and removal of preset activation buttons.
- Translations and focused documentation for management and controls.

Preset inventory/detail sensors are deferred to slice 02. Custom frontend code,
LAN control, notification delivery through Home Assistant, and live shower
commands are not in scope.

## Dependencies and Ordering

Depends on the existing authenticated HTTP API, supervised Pusher transport,
coordinator state merging, and activation command path. Slice 02 consumes the
dynamic preset reconciliation interface created here.

## Entry Point and Behavior

`Configure` opens directly to a shower's preset menu for one device or first
shows a device selector for multiple devices. The menu supports create, edit,
delete, move, and finish. Mutations return to the menu so several operations can
be completed in one session.

Every mutation refreshes device details, compares the current preset list to
the form baseline, validates input, writes the cloud API, refreshes authoritative
state, then synchronizes the first two presets to the controller. Cloud success
is never rolled back after a controller-sync failure; the flow reports that the
controller is pending and the coordinator retries after subscription/startup.

## Data and Validation

- Presets contain position, title, greeting, target temperature, ordered full
  outlet records, three ready booleans, and four timer fields.
- Title is trimmed and required; greeting is optional.
- Temperature choices are stored Fahrenheit integers from 60 through the
  device `max_temp`, labeled in Home Assistant's configured unit.
- At least one outlet is active, or exactly one in single-outlet mode.
- Timer length is 0-3599 seconds, represented as minutes/seconds 0-59.
- Presets remain contiguous, one-based, at least two, and at most ten.
- Delete requires confirmation. Move selects a preset and destination position.

## API and State Transitions

- Create/edit/move: `PATCH /v4/showers/{serial}` with a JSON `shower` object
  containing `api_server`, `active=true`, `name`, and the complete preset list.
- Delete: `DELETE /v2/showers/{serial}/presets/{position}`.
- Controller sync: `client-state-desired` with JSON-string data
  `{"type":"preset","data":[first,second]}` followed by a full report.
- REST refresh replaces the coordinator's complete device snapshot and notifies
  entity reconciliation listeners.
- No preset data is copied into config-entry options.

## Authorization and Failures

Existing config-entry credentials authorize all operations. HTTP 401 refreshes
authentication once. Validation and conflicts are shown in the form without a
write. REST failures leave local state unchanged. REST success plus Pusher
failure is a partial success, retained in coordinator state and marked pending
for retry.

## Implementation Surfaces

- HTTP API, coordinator, Pusher payload helpers, and config/options flow.
- Button platform dynamic reconciliation.
- Strings/translations, tests, and README.

## Tests and Validation

- Positive tests for all CRUD/move operations and exact REST/Pusher wire data.
- Negative tests for stale baselines, bounds, outlet constraints, minimum and
  maximum counts, auth errors, REST errors, and partial controller sync.
- Flow tests for one/multiple devices, menus, forms, confirmation, repeated
  operations, and translated error keys.
- Dynamic button add/update/delete tests with unchanged unique IDs.
- Run focused tests, complete pytest, Ruff, compilation, and diff checks.

## Acceptance Criteria

- All supported fields round-trip without losing outlet metadata.
- Concurrent external changes are detected before full-list PATCH writes.
- Positions 1-2 synchronize with the controller without water activation.
- New/deleted/moved presets are reflected by activation buttons immediately.
- No live device command is used for validation.

## Commit Boundary

Commit this slice plan, management implementation, controls reconciliation,
translations, documentation, and tests together after validation passes.
