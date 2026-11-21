# herdr-profile

Sets up, opens and removes Herdr app profiles. What a profile is and how to use it is in `herdr-app/README.md`.

```sh
just herdr-profile                             # install into ~/.local/bin
just --justfile bin/herdr_profile/justfile test
just --justfile bin/herdr_profile/justfile check
```

It is installed editable: `cli.py` finds the repository's `herdr-app/` (settings, keys, themes and our own mods) from its own path, so a copied install would link profiles to the wrong place.

- `profiles.py` does the work: links and copies into the profile's home, rewrites its `main-copy` layout, and adds machines to its herdr-core session with `herdr-core machine add`.
- `cli.py` is the typer command line and reads `~/.config` once.

The tests run the file setup and removal against temporary folders with real `rsync`. Machine setup and `open` call `herdr-core` and the app, so they are checked by hand in a test profile.
