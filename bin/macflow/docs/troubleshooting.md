# Troubleshooting

## Global shortcuts do not work

If a menu action works but its global shortcut does not, macOS may be blocking
Macflow's keyboard event tap with Secure Input. For example, **Show Screenshot
Shelf** may work from the menu bar while `cmd + shift + h` does nothing.

Secure Input protects password entry by preventing other applications from
observing keyboard events. It can remain enabled after a password field closes,
an application moves to the background, or the Mac wakes. Password managers,
browsers with login forms, and terminal applications are common sources.

Check whether Secure Input is enabled:

```bash
ioreg -l -d 1 -w 0 | grep kCGSSessionSecureInputPID
```

No output means Secure Input is disabled. Output containing a PID means it is
enabled. The reported process is not always the application responsible;
`loginwindow` is commonly reported when another application owns the request.

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
or reinstalling Macflow. If they do not, confirm Accessibility permission is
still granted:

```bash
macflow permissions
```

The response should contain `"accessibility" : true`.
