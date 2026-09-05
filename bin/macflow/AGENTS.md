# Macflow

## Purpose

Macflow is a configurable macOS application for personal workflows.
It is inspired by Hammerspoon and aims to provide API's for easy automation of Mac actions and UI.

## Principles

- Design around the user's workflow.
- Expose meaningful state and actions through the UI.
- Compose existing tools rather than duplicating their behavior.
- Keep behavior and configuration owned by the appropriate component.
- Add reusable capabilities when multiple workflows need them.

### CLI design

The `macflow` CLI is strictly an HTTP client for the running Macflow
application.

- Define the command hierarchy, arguments, options, validation, and help with
  Swift Argument Parser. Do not parse `CommandLine.arguments` manually.
- CLI commands may parse arguments, locate connection configuration and
  credentials, issue HTTP requests, render responses, and set exit codes.
- CLI commands must not directly read or modify macOS runtime state.
- This prohibition includes read-only diagnostics, permission checks, and
  fallback behavior through AppKit, ApplicationServices, Carbon, CoreGraphics,
  ScreenCaptureKit, or other macOS system APIs.
- All macOS state and actions must be owned by the running signed application
  and exposed through a versioned `/v1/...` HTTP endpoint.
- If a CLI command needs runtime state that is not available through the HTTP
  API, add or extend an endpoint before implementing the command. Do not add a
  direct local fallback.
- Keep `GET /v1/health` limited to service liveness.
- Tests for CLI commands should verify the HTTP requests they issue and the
  behavior rendered from HTTP responses.

### Ground rules

1. Always make sure `macflow` can be configured using `XDG_HOME/.config/macflow/config.toml`
2. Always make sure all actions taken by `macflow` can be introspected using `macflow` commands.

## Config

Note: Config does not belong inside `bin/macflow`. That is for the state agnostic tool.

Config belongs in `macflow/` which is for the local machine's configuration.

## Testing and Dcoumentation hygiene

- Tests and documentation are not implementation notes.
- Tests should not be change detection tests. They should test behaviour.
- Documentation should be short but extremely clear, preferably with examples.

## Error handling

- Let errors propagate from low-level helpers with `throws`.
- Catch errors at the nearest boundary that can meaningfully recover, report the failure, or terminate the current action, such as application startup, a CLI command, or a user-action callback.
- Do not add repeated `do/catch` wrappers that perform the same reporting. Centralize that conversion in one clearly named helper.
- Return an optional or boolean after reporting only when the caller's sole response is to abort the current action. Keep errors typed and throwable when callers may handle them differently.
- Prefer linear control flow with `guard` after errors have been handled at the boundary.

## Tidy, First

- When proposing changes, first figure out if it can be implemented using existing code by refactoring.
- Adding new code should be done only if existing code cannot suffice.
- This binary is for an audience of 1. Do not add enterprise style code, fallback, over-defensive code.
- Always aim to make the codebase better with each PR.
- Only start implementation after the user has agreed to your proposal. 
    - When the user is using words like "Tell me", "What", "How" etc, it means they are asking for a discussion, not an implementation.

## PR description

- PR description should be concise and only note the main change.
- Do not put all the implementiton notes like what tests were run, how they were run etc.

## Commands

Run from the repository root:

```bash
just --justfile bin/macflow/justfile test
just --justfile bin/macflow/justfile build
```
