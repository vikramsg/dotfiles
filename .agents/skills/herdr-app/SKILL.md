---
name: herdr-app
description: "Work on the Herdr desktop app's setup in this repo: herdr-app/ settings, keys, themes, mods and the main-copy layout. Use when adding, changing or end-to-end testing a mod or layout, or driving the app with herdr-app do / shot / status."
---

# Herdr app

The Herdr desktop app (`herdr-app`) is set up from `herdr-app/` in this repo; `herdr-app/README.md` describes what each file and mod does and how `just herdr-app` installs it. The app's API reference is `~/.config/herdr-app/AGENTS.md` and `~/.config/herdr-app/herdr.d.ts`.

## Test in another profile, never the user's window

The user works in the main window (`~/.config/herdr-app`, herdr-core session `default`). Opening tabs, spaces, overlays or panels there, switching its layout, or editing its `layouts/main-copy.json` takes over their screen and can move or close what they are working in. End-to-end tests of mods and layouts go in a separate profile: a window of its own with the same setup, whose spaces and terminals live in their own herdr-core session on this Mac and on the VM.

1. Create or refresh the profile; it copies the main home's third-party mods and `main-copy`, links the repo's settings, keys, themes and own mods, and points every machine at a session of the profile's name:

   ```sh
   just -f herdr-app/justfile profile agent-test
   ```

2. Open its window:

   ```sh
   open -n -a /Applications/Herdr.app --env HERDR_APP_HOME="$HOME/.config/herdr-app-agent-test" --env HC_SESSION=agent-test
   ```

3. Drive and inspect that window only, by giving every command the profile's home and session:

   ```sh
   export HERDR_APP_HOME="$HOME/.config/herdr-app-agent-test" HC_SESSION=agent-test
   herdr-app status
   herdr-app do space.new '{"name":"t","machine":"vm-us","folder":"/home/vikram_orbio_earth/personal/dotfiles"}'
   herdr-app shot /tmp/agent-test.png
   herdr-core ls --json
   ```

   Install a mod or change a layout under test in `$HERDR_APP_HOME` (`mods/`, `layouts/main-copy.json`), not in `~/.config/herdr-app`. Only once it works there, put it in the repo and the `just herdr-app` steps.

4. Clean up when done:

   ```sh
   for a in $(HC_SESSION=agent-test herdr-core ls --json --all | jq -r '.terminals[].address'); do HC_SESSION=agent-test herdr-core kill "$a"; done
   # quit the window (its process has HERDR_APP_HOME=~/.config/herdr-app-agent-test in its environment)
   HC_SESSION=agent-test herdr-core server stop
   ssh vm-us 'HC_SESSION=agent-test ~/.local/bin/herdr-core server stop; rm -rf ~/.local/state/herdr-core/agent-test'
   rm -rf ~/.config/herdr-app-agent-test ~/.local/state/herdr-core/agent-test
   ```

Mods in `herdr-app/mods/` are linked into every home, the main one included, so editing them changes the user's window as well; keep such edits small and reload them in the profile to test.

## Things that are easy to get wrong

- The app may not reload a mod whose folder is a symlink when its files change. Re-create the link (`rm` it, then `ln -s` it again) and run `herdr-app check <mod folder>`.
- Mods that ship icons, or that draw blank when linked, are copied, not linked (see the README).
- Installers such as gitview's replace the `keys.json` symlink with a plain file; `just herdr-app` copies it back into the repo and relinks it.
- `herdr-app status` lists errors, but a mod's toast is only visible in `herdr-app shot`.
- The app runs with a bare `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`): commands it runs need full paths or `zsh -lc`.
