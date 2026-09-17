# Safe Preset-Mutation Diagnostics

## Summary

Add actionable Home Assistant logging for failed preset create, edit, move, and
delete operations while retaining the generic options-flow error. Capture the
Moen HTTP method, endpoint, status, correlation identifier, and a bounded,
sanitized response body without logging credentials or outgoing preset data.

This delivery adds diagnostics only. It does not change Moen endpoints,
payloads, mutation semantics, entity behavior, or release metadata.

## Settled Behavior

- Preset failures are logged with their operation and device context.
- HTTP error responses are parsed when possible, recursively redacted, and
  truncated before storage or logging.
- Non-JSON responses and transport/decoding errors retain safe request context.
- The UI continues to show the translated `cannot_connect` message only.
- Safe debug lifecycle markers distinguish cloud write, refresh, and controller
  synchronization stages.
- README troubleshooting explains how to collect the new diagnostics.

## Delivery Slice

1. [Slice 01: Capture and log sanitized preset failures](20260917070625_preset_mutation_diagnostics_slice_01.md)

## Acceptance

- Failed PATCH and DELETE responses produce useful, operation-specific logs.
- Token, password, authorization, credential, email, and secret values never
  appear in captured logs or formatted exceptions.
- Successful protocol behavior and options-flow errors remain compatible.
- All validation is offline; no live preset mutation is sent.

## Transaction

- Parent commit: `7832e3d19cddfdd6b61d907580ae25193ee3a384`
- Payload commit: `8df315cba9b806e8e8bfdf3711b2ac2b4cfd89a9`
