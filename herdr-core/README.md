# herdr-core

herdr-core (`hc`) runs the [Herdr app](../herdr-app/README.md)'s terminals,
one core per machine: this Mac and `vm-us`. The app's own settings live on the
Mac only, but each core reads its own `~/.config/herdr-core/config.toml`, so
run this on every machine:

```sh
just herdr-core
```

`config.toml` sets `shell` so new terminals start zsh instead of the login
shell, which is bash on the VM. It applies to terminals started afterwards;
open tabs keep their shell.
