# Slice 01: Rewrite and Validate the End-User README

## Goal and Observable Outcome

Users can understand how to install, operate, configure, automate, and
troubleshoot the integration while seeing an accurate distinction between
live-tested controls/sensors and the untested-on-hardware preset editor.

## Scope and Non-Scope

Rewrite `README.md` to cover current capabilities, validation status,
installation, preset management, entities, examples, synchronization,
limitations, and troubleshooting. Preserve project attribution and legal
sections. Do not change executable code, translations, manifests, release
metadata, or APK artifacts.

## Dependencies and Ordering

The documentation describes behavior already delivered in commits `ebd9d39`,
`8467a6c`, `a0d6297`, and `dd261c6`. No runtime dependency or migration is
introduced.

## Entry Point and End-to-End Behavior

The README starts with supported hardware/account scope and a validation-status
callout. It then guides users through installation and configuration, normal
controls, experimental preset management, created entities, automation and
dashboard examples, synchronization behavior, limitations, and recovery steps.

## State, Authorization, and Error Handling

No application state or permissions change. Documentation explains that the
integration requires authenticated Moen cloud and Pusher access, that preset
write/controller synchronization remains unverified on live hardware, and that
logs shared for support must redact credentials and tokens.

## Implementation Surface

- `README.md`
- This governing plan and slice plan

## Validation

Positive review:

- Confirm the README explicitly identifies shower controls and sensor updates
  as live-tested.
- Confirm it documents all current entity types and preset fields.
- Confirm examples use current Home Assistant action syntax.

Negative review:

- Confirm it makes no claim that preset create/edit/delete/move or controller
  synchronization has been live-tested.
- Confirm it does not claim local-LAN support or guaranteed cloud availability.
- Confirm source files and the pre-existing `apks/` path are unchanged.

Run structural Markdown/YAML checks where locally available, inspect links and
code fences, run `git diff --check`, and review the final diff. This is a pure
documentation slice, so executable tests are not required.

## Acceptance Criteria

- The README is concise, internally consistent, and useful to an installing
  Home Assistant user.
- Live verification is scoped only to controls and timely sensor updates.
- Preset management is clearly labeled experimental pending live-device tests.
- Existing project ownership, contribution, license, credit, and disclaimer
  information remains present.

## Commit Boundary

Commit the README and both documentation-plan artifacts together as one
documentation-only slice after validation.
