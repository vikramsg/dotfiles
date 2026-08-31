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

## Config

Note: Config does not belong inside `bin/macflow`. That is for the state agnostic tool.

Config belongs in `macflow/` which is for the local machine's configuration.

## Testing and Dcoumentation hygiene

- Tests and documentation are not implementation notes.
- Tests should not be change detection tests. They should test behaviour.
- Documentation should be short but extremely clear, preferably with examples.

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
