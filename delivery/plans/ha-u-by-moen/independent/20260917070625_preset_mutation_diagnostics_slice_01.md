# Slice 01: Capture and Log Sanitized Preset Failures

## Goal and Observable Outcome

When a preset mutation returns the generic options-flow error, Home Assistant
logs identify the failed operation and safe Moen response details needed to
diagnose the protocol mismatch.

## Scope and Non-Scope

Enhance API exceptions, preset-operation logging, tests, and troubleshooting
documentation. Do not change request endpoints or bodies, expose server text in
the UI, add diagnostics entities/downloads, change version metadata, or execute
live device commands.

## Dependencies and Ordering

Build on the existing `MoenApiError` hierarchy and the options flow's shared
save path. HTTP capture must be safe and tested before the flow logs formatted
exceptions.

## Entry Point and End-to-End Behavior

A user submits create, edit, move, or delete. The coordinator performs its
existing preflight and mutation sequence. If any API request fails, the HTTP
layer captures safe diagnostic context; the options flow logs the operation,
device serial, and formatted error, then returns the unchanged generic UI
error. Successful mutations emit debug lifecycle markers without payload data.

## Data, Authorization, and Privacy

The HTTP exception retains method, path, status, an optional common server
request ID, and at most a fixed-size sanitized body. JSON keys associated with
tokens, passwords, authorization, credentials, email, and secrets are
recursively redacted. Non-JSON credential patterns are redacted and control
characters normalized. Request headers, query credentials, shower tokens, and
outgoing preset bodies are never logged.

## Errors and Recovery

HTTP errors preserve server context; transport and decoding failures include
method/path and the safe exception category. Logging must never mask or replace
the original `MoenApiError`. Existing conflict and validation errors keep their
specific UI behavior and are not logged as Moen service failures.

## Implementation Surfaces

- HTTP API error construction and sanitization.
- Options-flow and coordinator mutation-stage logging.
- API/options-flow unit tests and README troubleshooting.

## Tests and Validation

Positive tests:

- PATCH and DELETE errors retain method, path, status, request ID, and useful
  JSON or text details.
- Create/edit/move/delete API failures log their operation and device serial.
- Success debug messages identify mutation stages without request content.

Negative tests:

- Nested sensitive JSON keys and raw text credentials are redacted.
- Oversized bodies are truncated and control characters normalized.
- Tokens, passwords, authorization strings, email values, outgoing presets,
  and headers never appear in logs or formatted exceptions.
- The options flow still returns only `cannot_connect`.

Run focused API/options-flow tests, Ruff, the complete `pytest -q` suite,
compilation, JSON validation, and `git diff --check`.

## Acceptance Criteria

- A real failure log is sufficient to identify request stage, endpoint, HTTP
  status, and sanitized server explanation.
- UI and successful preset behavior remain unchanged.
- No secret-bearing request material is logged.
- No live Moen operation is performed during validation.

## Commit Boundary

Commit the plan, implementation, tests, and documentation together after all
offline validation passes.
