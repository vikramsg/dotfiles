# Cursor models in OpenCode

This configuration uses
[`@rama_nigg/open-cursor`](https://github.com/Nomadcxx/opencode-cursor) to make
models available through a Cursor subscription appear as the `Cursor` provider
in OpenCode.

## Runtime architecture

The provider ID is `cursor-acp`, but the production integration does not use
Cursor's ACP transport. The name is an identifier retained by the upstream
project.

Requests follow this path:

```text
OpenCode
  -> OpenAI-compatible request
  -> local proxy at 127.0.0.1:32124
  -> cursor-agent process
  -> Cursor API
```

The `open-cursor` plugin starts the local proxy and translates between
OpenCode's OpenAI-compatible requests and the newline-delimited events emitted
by `cursor-agent`. The upstream project describes a direct
`OpenCode -> Cursor ACP` integration as a possible future replacement, not the
current production path.

## Installation

The CLI is installed globally with npm:

```bash
npm install -g @rama_nigg/open-cursor
open-cursor install
```

The installer uses Bun to install `@ai-sdk/openai-compatible` under the
OpenCode configuration directory. Bun is therefore declared in the repository
`Brewfile`.

The installer creates a symlink at:

```text
~/.config/opencode/plugin/cursor-acp.js
```

This singular `plugin/` path is external state managed by the upstream
installer. It is separate from this repository's `plugins/` directory and
should not be moved into the repository-managed plugin tree.

OpenCode discovers files in that directory automatically. Do not also add
`"cursor-acp"` to the `plugin` configuration array: OpenCode interprets that
string as a package reference and reports `Plugin entrypoint not found`.

## Authentication on the VM

Authentication belongs to the `cursor-agent` installation on the VM; the
Cursor desktop application's local login is not reused automatically.

Run:

```bash
cursor-agent login
```

The command creates a browser challenge and polls Cursor for completion. It
does not require forwarding a localhost OAuth callback port. In this setup,
the repository-managed `xdg-open` command sends the challenge URL through the
browser-opener tunnel to the Mac. For a manual flow, prevent automatic browser
opening and open the displayed URL on any authenticated device:

```bash
NO_OPEN_BROWSER=1 cursor-agent login
```

Verify the stored login with:

```bash
cursor-agent models
```

## Model discovery

`cursor-agent models` is the source of truth for models available to the
authenticated account. The Cursor desktop application may expose a different
list.

Synchronize the CLI list into OpenCode with:

```bash
open-cursor sync-models
```

The command parses `cursor-agent models` and writes entries under
`provider.cursor-acp.models` in `opencode.json`. OpenCode reads those static
entries to populate its model picker. A model appearing in the picker confirms
that it is configured; it does not by itself confirm that the runtime plugin
loaded successfully.

This repository intentionally curates the synchronized list by excluding
OpenAI, Claude, and Gemini model families. Running `open-cursor sync-models`
again will restore every model reported by `cursor-agent`, so review and
reapply that filtering before committing a refreshed configuration.

Automatic startup synchronization is disabled in `zsh/.zshrc` to prevent the
plugin from restoring those model families whenever OpenCode starts:

```bash
export CURSOR_ACP_MODEL_AUTO_REFRESH="false"
```

Run synchronization explicitly when the account's available models need to be
refreshed, then curate the resulting list again.

Use the upstream compact form when a grouped model and variant list is
preferred:

```bash
open-cursor sync-models --variants --compact
```

## Verification

Check installation, authentication, model discovery, and a real request:

```bash
open-cursor doctor --deep
opencode models | grep '^cursor-acp/'
opencode run "Reply with exactly: cursor bridge works" --model cursor-acp/auto
```

OpenCode plugin-load failures are recorded in:

```text
~/.local/share/opencode/log/opencode.log
```
