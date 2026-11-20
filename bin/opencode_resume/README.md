# opencode-resume

Reopens OpenCode sessions in Herdr terminals after a reboot, a logout or a lost herdr-core. herdr-core restores each kept terminal at the same address, but as a plain shell in its last folder with a new shell process; the OpenCode that ran there is gone.

```sh
just opencode-resume                        # install the tool and its lch service
opencode-resume status                      # what resume would do
opencode-resume resume                      # type the resume command into each restored shell
just --justfile bin/opencode_resume/justfile test
just --justfile bin/opencode_resume/justfile check
```

In the Herdr app, `Cmd+Shift+R` runs `resume` on this computer and on every connected machine (the `opencode-resume` mod in `herdr-app/mods/`) and shows what came back in a toast. Each machine needs the tool and its service installed with `just opencode-resume`.

## How it works

herdr-core lists OpenCode's session in a terminal's `records` only while OpenCode works on a turn and clears it once OpenCode is idle, so on disk nothing says which session an idle OpenCode has open. The `lch-opencode-resume` service (`opencode-resume watch`) keeps that record itself, in `$XDG_STATE_HOME/opencode-resume/<HC_SESSION>/sessions.json` (`default` for the main window):

- It follows `hc events` for the session each OpenCode reports, since a turn can end in under a second, and every 5 seconds reads the live terminals with `hc ls` and `hc get`.
- Per terminal running OpenCode, it saves the machine's boot id, the shell's and OpenCode's pids, the session, OpenCode's folder and the command it was started with. While the same OpenCode process runs, the saved session stays current even when OpenCode is idle; a new OpenCode process started with `--session <id>` is known from its arguments.
- A shell counts as restored when its pid or the boot id changed: pids start over after a reboot, so a restored shell can get the old one's pid. The boot id is `/proc/sys/kernel/random/boot_id` on Linux and `kern.boottime` on macOS.

| Terminal on the next look                  | Saved session                         |
| ------------------------------------------ | ------------------------------------- |
| Same shell and boot, OpenCode gone         | Forgotten: OpenCode was quit          |
| New shell pid or boot (restored)           | Kept, waiting for `resume`            |
| Finished                                   | Forgotten                             |
| Not listed by `hc ls` (yet, after a boot)  | Kept                                  |
| A new OpenCode process, session not known  | Forgotten: the new OpenCode replaces it |

`resume` types `cd '<folder>' && <command> --session <id>` into each restored terminal with `hc send`. The folder and command are shell-quoted. It skips a terminal that is running something other than a shell, a folder that no longer exists, a folder or command with a control character (a newline would press Enter mid-command), and a session already open in another terminal. A session counts as open elsewhere when another terminal's OpenCode reports it, was started on it, or is the same process it was saved under. A terminal that can't be typed into is reported and the others still resume.

The service watches this machine's terminals in the main window's herdr-core session (`default`). A Herdr app profile runs in a session of its own (`HC_SESSION=<profile>`), with its own state file that only `HC_SESSION=<profile> opencode-resume watch` fills. `hc ls` also lists other machines' terminals (`vm-us/t3`), which each machine's own service and `resume` handle.

## Limits

- An OpenCode that never worked on a turn since it opened (and wasn't started with `--session`) has no session to save.
- Only the program is kept, not OpenCode's other arguments.
- A session switched to inside OpenCode (`/new`, `/sessions`) is learned on its first turn.
- When OpenCode reports more than one session at once there is no way to tell which one the TUI shows; the one already saved is kept if it is among them, otherwise nothing new is learned from that report.
