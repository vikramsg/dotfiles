# Git Config

This directory contains the tracked, non-PII Git config for this dotfiles repo.

## Files

`git/config` is safe to commit. It is intended to be symlinked as the global Git config at `~/.gitconfig`.

`~/.config/git/identity.local` is private and must not be committed. It contains identity values such as `user.name` and `user.email`.

`git/identity.local.example` is a placeholder template only.

## Layout

The intended setup is:

```text
~/.gitconfig -> /path/to/dotfiles/git/config
```

Then `git/config` includes the private identity file:

```text
~/.config/git/identity.local
```

This keeps shared behavior in the repo while keeping PII out of the repo.

## Private Identity

Create `~/.config/git/identity.local` with local-only identity values:

```ini
[user]
	name = Your Name
	email = you@example.com
```

Do not put `[user] name` or `[user] email` in `git/config`.

## Install

Run the `git` just recipe from this repo to install the symlink.

The recipe refuses to overwrite an existing real `~/.gitconfig`. If `~/.gitconfig` already contains PII, move the private identity values into `~/.config/git/identity.local` first, then replace `~/.gitconfig` with the symlink.

Run the `git-doctor` just recipe to verify the setup. It checks whether identity values resolve, but it does not print them.

## Push Behavior

Git tracks two separate branch names:

The local branch name, for example `dspy`.

The upstream branch configured for that local branch, for example `origin/cli-v2-v2`.

When those names differ, and with Git's default `push.default=simple`, plain `git push` refuses in that situation because Git assumes pushing a local branch to a differently named upstream branch may be accidental.

This config sets:

```ini
[push]
	default = current
```

That makes plain `git push` push the current local branch to a remote branch with the same name. For example, local `dspy` pushes to `origin/dspy`.

This setting only changes push behavior. It does not rewrite stale upstream tracking. If a branch still tracks the wrong upstream, `git status`, `git pull`, and ahead/behind counts can still mention the old upstream until that branch's upstream is corrected.

This config also sets:

```ini
[branch]
	autoSetupMerge = simple
```

That avoids automatically configuring an upstream when the remote branch name does not match the new local branch name.
