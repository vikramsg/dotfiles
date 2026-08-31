# Macflow

## Purpose

Macflow is a configurable macOS application for personal workflows.

It combines system capabilities, tools, and services into focused interfaces
and automations. Its goal is to make workflows easy to discover, understand,
configure, and operate without requiring the user to remember their underlying
commands or implementation details.

## Principles

- Design around the user's workflow.
- Expose meaningful state and actions through the UI.
- Compose existing tools rather than duplicating their behavior.
- Keep behavior and configuration owned by the appropriate component.
- Add reusable capabilities when multiple workflows need them.

## Commands

Run from the repository root:

```bash
just --justfile bin/macflow/justfile test
just --justfile bin/macflow/justfile build
```
