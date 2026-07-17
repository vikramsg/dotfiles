# ocint Roadmap

## 1. Repository-owned workflow contract

Adopt a repository-owned `WORKFLOW.md` based on the
[Symphony workflow specification](https://github.com/openai/symphony/blob/main/SPEC.md#5-workflow-specification-repository-contract).
Follow its optional YAML front matter, Markdown prompt body, file parsing, and
strict prompt-rendering semantics.

This scope retains GitHub as the tracker, OpenCode as the agent, and the
existing ocint daemon lifecycle. It does not adopt Symphony's Linear, Codex,
or orchestration requirements.

## 2. Make opencode be configurable

Right now it is constant and loaded from repo but we want to make it configurable and load it from ~/.config...
