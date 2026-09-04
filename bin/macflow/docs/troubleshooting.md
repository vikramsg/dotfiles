# Troubleshooting

## Global shortcuts do not work

If a menu action works but its global shortcut does not, macOS may be blocking
Macflow's keyboard event tap with Secure Input. For example, **Show Screenshot
Shelf** may work from the menu bar while `cmd + shift + h` does nothing.

Secure Input protects password entry by preventing other applications from
observing keyboard events. It can remain enabled after a password field closes,
an application moves to the background, or the Mac wakes. Password managers,
browsers with login forms, and terminal applications are common sources.

Run Macflow's diagnostics first:

```bash
macflow doctor
```

The command checks the running service, macOS permissions, global shortcut
listener, and Secure Input. When Secure Input is blocking shortcuts it reports:

```text
✗ secure input enabled
  help: Global shortcuts are blocked by macOS.
        Close password prompts and restart likely password-manager/browser apps.
```

To clear it:

1. Close any active password or authentication prompt.
2. Completely quit and reopen likely applications, starting with password
   managers such as Bitwarden. Install available updates before reopening them.
3. Quit browsers containing open login forms and terminal applications that use
   Secure Keyboard Entry if the problem remains.
4. Lock and unlock the Mac.
5. If Secure Input is still enabled, log out and back in or restart macOS.

Do not terminate `loginwindow`; doing so forcibly ends the login session.

After Secure Input clears, Macflow shortcuts should resume without rebuilding
or reinstalling Macflow. Run the doctor again to confirm every check passes:

```bash
macflow doctor
```
