# Slice 02: Preset Inventory and Detail Sensors

## Goal and Outcome

Each shower exposes an immediately usable preset count and ordered summary, and
each configured preset exposes its name and complete settings as a Home
Assistant sensor while retaining its activation button.

## Scope

- One preset-count sensor per shower.
- One detailed sensor per preset position.
- Dynamic sensor addition, update, and removal after preset changes.
- Home Assistant unit conversion for displayed target temperatures.
- Documentation and final full validation.

Preset mutation and activation behavior are not changed in this slice.

## Dependencies and Ordering

Depends on slice 01's authoritative refresh and dynamic preset reconciliation
signals. It must preserve existing active-preset and other sensor unique IDs.

## Entry Point and State

The count sensor always exists for a discovered shower. Its numeric state is
the number of presets and its `presets` attribute is an ordered list of
`position` and `title`. Each current position has one detail sensor whose state
is the title.

Detail attributes are position, greeting, target temperature/unit, complete
ordered outlets, all ready behavior booleans, and all timer fields. Target
temperature is converted from stored Fahrenheit to Home Assistant's configured
unit for presentation only.

## Entity Lifecycle

- Count unique ID: `{serial}_preset_count`.
- Detail unique ID: `{serial}_preset_{position}_details`.
- Add detail entities for new positions, update in place after edits/moves, and
  remove the entity-registry entry for deleted positions.
- Position remains slot identity, so moving a preset intentionally changes the
  title/settings represented by that position's button and sensor.

## Authorization and Failures

Sensors are read-only and require no authorization beyond the loaded config
entry. Missing/malformed optional fields become `None` or safe defaults without
breaking entity updates. A missing preset makes its detail entity unavailable
until reconciliation removes it.

## Implementation Surfaces

- Sensor platform and shared dynamic reconciliation helper/interface.
- Sensor and lifecycle tests, README, strings/translations if needed.

## Tests and Validation

- Count state and ordered summary attributes.
- Every detail field, outlet metadata, Fahrenheit/Celsius conversion, and
  malformed optional data.
- Dynamic add/update/delete and entity-registry cleanup.
- Preservation of existing sensor and activation-button IDs.
- Complete pytest, Ruff, compilation, JSON validation, and diff checks.

## Acceptance Criteria

- Automations can read preset count, names, positions, and every configurable
  setting from entities.
- Entity state updates immediately after options-flow or external refresh.
- No duplicate full preset list is placed on the count sensor.
- Full offline validation passes without live device communication.

## Commit Boundary

Commit sensors, reconciliation tests, final documentation, and this slice's
completion changes together after full validation passes.
