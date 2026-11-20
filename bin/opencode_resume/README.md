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

herdr-core lists OpenCode's session in a terminal's `records` only while OpenCode works on a turn and clears it once OpenCode is idle, so on disk nothing says which session an idle OpenCode has open. The `lch-opencode-resume` service (`opencode-resume watch`) keeps that record itself, in `$XDG_STATE_HOME/opencode-resume/sessions.json`:

- It follows `hc events` for the session each OpenCode reports, since a turn can end in under a second, and every 5 seconds reads the live terminals with `hc ls` and `hc get`.
- Per terminal running OpenCode, it saves the machine's boot id, the shell's pid, the session, OpenCode's folder and the command it was started with. An OpenCode started with `--session <id>` is known from its arguments.
- A shell counts as restored when its pid or the boot id changed: pids start over after a reboot, so a restored shell can get the old one's pid. The boot id is `/proc/sys/kernel/random/boot_id` on Linux and `kern.boottime` on macOS.

| Terminal on the next look                  | Saved session                         |
| ------------------------------------------ | ------------------------------------- |
| Same shell and boot, OpenCode gone         | Forgotten: OpenCode was quit          |
| New shell pid or boot (restored)           | Kept, waiting for `resume`            |
| Finished or gone                           | Forgotten                             |
| Running a new OpenCode, session not known  | Forgotten: the new OpenCode replaces it |

`resume` types `cd '<folder>' && <command> --session <id>` into each restored terminal with `hc send`. It skips a terminal that is running something other than a shell, a folder that no longer exists or can't be typed safely (a quote or control character), and a session already open in another terminal.

Only this machine's terminals are handled; `hc ls` also lists other machines' (`vm-us/t3`), which their own service and `resume` handle.

## Limits

- An OpenCode that never worked on a turn since it opened (and wasn't started with `--session`) has no session to save.
- Only the program is kept, not OpenCode's other arguments.
- When OpenCode reports more than one session at once there is no way to tell which one the TUI shows; the one already saved is kept if it is among them, otherwise nothing new is learned from that report.
