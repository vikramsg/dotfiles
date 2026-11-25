# Pax

[Pax](https://pypi.org/project/pydantic-ai-pax/) is Pydantic AI's coding agent
for the terminal. This repository installs it on the Mac and on `vm-us`:

```sh
just pax
```

That runs `just mise`, which installs the version pinned in
`mise/config.toml`, then turns off two built-in plugins:

- `herdr`: Pax reports its status to Herdr. It is off, so Pax never shows in
  Herdr's agents list.
- `notifications`: desktop alerts when a turn finishes.

`pax plugins list` shows both as disabled. Running `just pax` again changes
nothing.

## Model and sign-in

Pax runs on the ChatGPT subscription. Sign in once on each machine:

```text
pax
/login openai-codex
```

On `vm-us` the browser can't reach Pax's callback: copy the URL from the
browser's address bar after it fails and paste it at Pax's prompt.

The default model is `openai-codex:gpt-6.2-sol`, set by `CLAI_MODEL` in
`zsh/.zshenv`. `pax config set` refuses to change the model from a shell, so
the default can't live in Pax's settings. `/model` still switches models
within a session, and `-m` picks one for a single run.

## Settings

Pax keeps its settings in `~/.config/pydantic-clai2/config.db`, a SQLite
database, not a file this repository can link. Change them with `/set` or
`/config` inside Pax.

## Updating

Bump the version in `mise/config.toml` and run `just pax`. Don't use Pax's own
`/update now`: it installs a copy outside mise. mise doesn't offer a release
until it is older than its `minimum_release_age`, so the newest version may
not appear for a day.
