# Pax

[Pax](https://pypi.org/project/pydantic-ai-pax/) is Pydantic AI's coding agent
for the terminal. This repository installs it on the Mac and on `vm-us`:

```sh
just pax
```

That runs `just mise`, which installs Pax from `mise/config.toml`, then turns off two built-in plugins and sets the default
model's reasoning effort to `high` (Pax's default for GPT-6 models is
`medium`):

- `herdr`: Pax reports its status to Herdr. It is off, so Pax never shows in
  Herdr's agents list.
- `notifications`: desktop alerts when a turn finishes.

`pax plugins list` shows both as disabled, and `/effort` in a session shows
`high`. Running `just pax` again changes nothing.

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
within a session, and `-m` picks one for a single run. If you change the
default, change `model` in `bin/pax/justfile` too, so its effort is set.

## Settings

Pax keeps its settings in `~/.config/pydantic-clai2/config.db`, a SQLite
database, not a file this repository can link. Change them with `/set` or
`/config` inside Pax.

## Updating

`mise/config.toml` asks for the latest Pax with `auto_update`, so mise updates
it on its own: when `pax` starts, or at a shell prompt, it installs a newer
release once one is at least a day old (mise's `minimum_release_age`). `mise
upgrade pypi:pydantic-ai-pax` checks now. Don't use Pax's own `/update now`: it
installs a copy outside mise.

`just pax` turns plugins off through Pax's settings code, so a new Pax can break
it. If it does, `just --justfile bin/pax/justfile test` shows where.
