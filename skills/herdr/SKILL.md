---
name: herdr
description: "Work in the Herdr app and its herdr-core (`hc`) terminals, where agents here run on the Mac and the VM. Use to run commands or other agents in sibling terminals, read and drive a terminal app to reproduce a bug, show something in the person's window, test Herdr app changes in a separate profile, or open a new git worktree as a Herdr space from the VM."
---

# Herdr

The person works in the Herdr desktop app on the Mac. Its terminals are run by
herdr-core (`hc`): on the Mac for local spaces, and on the VM (`vm-us`) for
spaces there. Each terminal keeps running when the window closes.

- `hc` is on both machines. It starts, reads, talks to and waits on terminals.
- `herdr-app` is only on the Mac. It changes what the window shows.

Check that you are in an hc terminal:

```sh
test -n "${HC_TERMINAL_ID:-}"   # your own address, e.g. t7; it is not a pane ID
echo "$HC_SESSION"              # the session, which belongs to one window or profile
```

If the check fails, say so and ask before touching any Herdr session.

## Learn the installed tools

The installed manuals are the authority; read the part you need before using a
command you haven't used:

```sh
hc --skill              # running, reading, waiting on and talking to terminals and agents
hc <command> --help
herdr-app --skill       # (Mac) driving the window
herdr-app commands      # (Mac) every window command and its arguments
```

## Run commands and agents in other terminals

Use `hc`, from either machine:

```sh
hc run --bg --name tests --cwd "$PWD" -- just test
hc wait tests                      # never sleep or poll: wait on it
hc read tests --lines 120
hc kill tests; hc rm tests         # clean up what you started
```

Terminals you start are your children: they end when you end, unless started
with `--outlive-parent` or `--no-parent`. They stay out of the window unless
labelled `herdr.space=<id>` (and `herdr.tab=<id>` for a tab), as
`herdr-app --skill` describes. Don't label background work.

## Reproduce a terminal app bug

When an interactive app misbehaves, drive it yourself and read its screen
instead of asking what the person saw:

```sh
hc run --bg --name app-test --cwd "$PWD" -- <app>
hc keys app-test down enter        # key names: enter, esc, tab, up, ctrl+c, shift+z, a…
hc send app-test "some text"       # pastes the text, then Enter
hc read app-test --lines 0         # the visible screen
hc kill app-test; hc rm app-test
```

Characters such as `:` are not key names; type them with `hc send`. A
full-screen app takes `hc send` as a paste: in Neovim normal mode it inserts
the text, so send `:` commands while the app is in a mode that takes them.

When the last step would reach outside the machine (opening a browser,
pushing, posting), put a stub first on that terminal's `PATH` so the test
records what the app tried to run instead.

## Show or test things in the window (Mac)

New spaces and tabs are shown at once: only make them in the person's window
when asked, and pass `--focus false` to keep their place.

To test app behaviour, layouts or mods, never use the person's windows. Use a
profile of your own: a separate window and herdr-core session on the Mac and
the VM.

```sh
herdr-profile setup agent-test
open -g -n -a /Applications/Herdr.app --env HERDR_APP_HOME="$HOME/.config/herdr-app-agent-test" --env HC_SESSION=agent-test
export HERDR_APP_HOME="$HOME/.config/herdr-app-agent-test" HC_SESSION=agent-test
herdr-app do space.new '{"name":"t","machine":"vm-us"}'   # starts in that machine's home
herdr-app shot /tmp/agent-test.png    # then look at it
```

- `open -g` keeps the window in the background. `herdr-profile open` brings it
  to the front, and the person's typing then goes into the test window.
- A background window on another macOS Space doesn't redraw, and terminals
  only take a new pane size on a redraw. While a test depends on sizes, keep
  it drawing with `herdr-app shot` every 250 ms.
- Synthetic mouse and key events are dropped (no Accessibility permission).
  Drive the window with `herdr-app do`, and dialogs through their props.
- Clean up every test profile when done:

  ```sh
  for a in $(HC_SESSION=agent-test hc ls --json --all | jq -r '.terminals[].address'); do HC_SESSION=agent-test hc kill "$a"; done
  # quit the window: the Herdr process with HERDR_APP_HOME=~/.config/herdr-app-agent-test
  HC_SESSION=agent-test hc server stop
  ssh vm-us 'HC_SESSION=agent-test ~/.local/bin/hc server stop; rm -rf ~/.local/state/herdr-core/agent-test'
  herdr-profile remove agent-test
  rm -rf ~/.local/state/herdr-core/agent-test
  ```

## Open a new worktree as a space from the VM

In the window, `prefix+n` makes a worktree from a freshly fetched origin main
and opens it with OpenCode, a shell and reviewr. From a terminal on the VM,
with no window commands there, `scripts/new-worktree` in this skill's folder
does the same with `hc`:

```sh
<skill folder>/scripts/new-worktree <branch>                  # from inside the repository
<skill folder>/scripts/new-worktree <branch> --repo ~/projects/app --session friday
```

- The worktree goes to `~/.herdr/worktrees/<repo>/<branch>`, as `prefix+n`
  puts it. A new branch starts from origin's default branch, fetched now, with
  no upstream; a branch that exists is checked out as it is.
- The space has one tab: OpenCode (`opencode2`) on top at 70% of the height,
  the shell below. Both are started with `hc run --no-parent`, so they outlive
  the terminal that ran the script.
- It shows at once in the window on that session (default: `$HC_SESSION`, so
  the window this terminal is in). Reviewr is not started: `prefix+r` opens it
  in that tab.
- It prints the path, the start point and the two terminal addresses as JSON.

The script adds the space to the app's `herdr-app` document in herdr-core
(`hc connect`, `doc.get` / `doc.set`). That document is the app's own format,
not a public API. If its shape isn't the one the script knows, the script
stops, keeps the worktree and ends the two terminals it started. Then a Herdr
update has changed the format: compare `doc.get herdr-app` with the script
before changing it.

## Safety

- Use addresses from `hc ls` / `herdr-app ls`; never act on a guessed or
  focused pane that may be the person's.
- Don't kill, close or stop terminals, spaces, windows or sessions you didn't
  start. Never stop the person's herdr-core or quit their app.
- Ask before creating or restarting Herdr servers and sessions, except for
  test profiles of your own.
