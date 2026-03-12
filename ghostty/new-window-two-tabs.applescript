tell application "Ghostty"
    activate

    set cfg1 to new surface configuration
    set command of cfg1 to "bash -lc 'printf \"\\033]0;tab1\\007\"; exec \"$SHELL\" -l'"

    set win to new window with configuration cfg1

    set cfg2 to new surface configuration
    set command of cfg2 to "bash -lc 'printf \"\\033]0;tab2\\007\"; exec \"$SHELL\" -l'"

    new tab in win with configuration cfg2

    activate window win
    select tab (tab 1 of win)
end tell
