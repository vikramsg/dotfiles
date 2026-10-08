# Fresh sidebar launcher

`sidebar.py open` is invoked by the `dotfiles.fresh-sidebar.open` Herdr action.
It opens one Fresh sidebar per invoking tab, or focuses that tab's existing
sidebar. Its project root comes from the invoking terminal's foreground working
directory. The sidebar occupies the right 40% of the full tab.

The launcher exports the existing split tree, holds all but its first terminal
in unfocused temporary tabs, opens Fresh beside the remaining terminal, and
rebuilds the original tree on the left using live terminal moves. Holding tabs
close as their terminals move back. No terminal is restarted, and the original
split ratios are retained. Quitting Fresh closes its sidebar terminal, naturally
promoting the unchanged left-hand tree back to the whole tab.

Opening is serialized through the plugin state directory's `open.lock`.
Fresh waits until docking finishes before starting its interactive UI. No event
hooks open editors or follow directory changes automatically.

Run launcher behavior tests with:

```sh
python3 -m unittest discover -s bin/fresh_sidebar/tests -v
```
