---
name: terminal-browser
description: Open and drive Terminal Browser in this repo's Herdr setup on the Mac or vm-us, and verify that pages render in the terminal.
---

# Terminal Browser in Herdr

Use the `herdr` skill to identify the current workspace and the machine that
owns the terminal. Create a named test tab without stealing focus if the user
asked for one. Run `terminal-browser open <url>` in that tab's terminal, not
in the user's shell or from a tool without a TTY. In Herdr desktop, create
tabs and splits with `herdr-app`; the browser's built-in `--split` adapter
targets the older `herdr` CLI, not `herdr-app`/`hc`.

If Terminal Browser reports `Unsupported terminal` in a VM-backed Herdr tab,
the graphics probe can fail even though Herdr can render the page. Retry in
that same tab with `PIXEL_SKIP_GRAPHICS_CHECK=1 terminal-browser open <url>`,
then verify the page is visible. Do not set the override globally.

Run browser CLI commands on the same host as the browser (`hc exec --on vm-us`
from the Mac for a VM browser). Use the browser key and tab ID, especially
when running commands outside the browser's terminal:

```sh
terminal-browser ls --all --json
terminal-browser new-tab https://developer.mozilla.org/ --browser "$browser"
terminal-browser action --browser "$browser" --tab "$tab" -- snapshot -i
terminal-browser action --browser "$browser" --tab "$tab" -- eval 'document.title'
terminal-browser action --browser "$browser" done
```

Use element references from a fresh snapshot for actions such as `click @e1`
and `fill @e2 'text'`, or use a named locator such as
`find role link click --name 'Learn more'` if the reference is stale.
`--follow` brings the chosen browser tab to the front;
`done` clears the visible agent-control indicator after the last action. For
the installed action reference, pass `-- --help` after the browser selector.

When testing Herdr compatibility, confirm the page is visible in the app
with `herdr-app shot` on the Mac. A successful `snapshot` only proves the
browser loaded the page, not that its pixels reached the Herdr pane.
`terminal-browser open --ssh <host> <url>` is useful to reach a VM service
from a Mac browser, but does not test the VM's Terminal Browser install.
