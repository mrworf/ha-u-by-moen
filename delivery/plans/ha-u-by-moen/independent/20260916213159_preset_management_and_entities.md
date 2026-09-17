# Preset Management, Controls, and Sensors

## Summary

Add a native Home Assistant options flow for complete per-device preset
management. Preserve individual preset activation buttons and add a preset
count sensor plus one detailed sensor per preset. All validation is offline;
settings synchronization must never activate a preset or start water.

## Settled Behavior

- Single-device accounts open preset management directly; multi-device
  accounts select a shower first.
- Users can create, edit, delete, and move presets repeatedly before finishing.
- Forms expose title, greeting, temperature, outlets, ready behaviors, and all
  timer settings.
- Temperature labels use Home Assistant units while API values remain exact
  whole-degree Fahrenheit values.
- A shower retains at least two presets and supports at most ten.
- Positions 1-2 are identified as physical-controller presets.
- REST is authoritative; the first two presets are synchronized to the
  controller using APK-compatible Pusher messages.
- Existing per-position buttons remain the activation controls.
- A count sensor exposes an ordered position/title summary, and each preset has
  a detail sensor whose state is its title and whose attributes contain all
  settings.

## Delivery Slices

1. [Slice 01: Preset management and dynamic controls](20260916213159_preset_management_and_entities_slice_01.md)
2. [Slice 02: Preset inventory and detail sensors](20260916213159_preset_management_and_entities_slice_02.md)

## Global Acceptance

- Exact APK-derived PATCH, DELETE, and Pusher preset shapes are covered by
  offline tests.
- Stale forms cannot silently overwrite a newer preset list.
- Cloud success is retained if controller synchronization fails, with a clear
  pending-sync result and reconnect/startup retry.
- Settings work never sends power, outlet, temperature-control, or
  preset-activation events.
- Dynamic entities remain consistent with the authoritative preset list.
- Ruff, compilation, the complete offline suite, and available HACS/Home
  Assistant static validation pass.
