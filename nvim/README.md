# Usage

## Install

Use linking as in [Config init](## Config init) section.
After linking, setup is automatic. 
Start `nvim` for the first time, and `lazy` should automatically setup. 

## Keybindings

### Neovim

- `Space + wh`: Move focus to the window on the left.
- `Space + wl`: Move focus to the window on the right.
- `Ctrl + h/j/k/l`: Move between Neovim splits, crossing into an adjacent Herdr
  pane at a split edge. Inside tmux, the existing `vim-tmux-navigator` behavior
  is preserved; outside either multiplexer, the keys move only between splits.

### Snacks Explorer

- The file tree opens on the right.
- `Space + e`: Toggle the file tree.
- `Space + E`: Reveal the current file in the file tree.
- `Enter` or `l`: Open the selected file and focus its editor window.
- `Y`: Copy the selected filename.
- `e`: Toggle the explorer width.
- `.`: Toggle hidden and ignored files.

### Snacks Picker

- `Space + Space`: Open search to find files. 
- `Space + /`: Search for word in current buffer.
- `Space + sg`: Grep for word in project.
- `Space + sf`: Find files in project.

### Git diffs

- `Space + gd`: Open CodeDiff's working-tree review. If there are no uncommitted changes, CodeDiff reports that there is nothing to show; it does not switch to branch review automatically.
- `Enter` in the file tree: Open the selected file and focus its diff.
- `B` in the review explorer or diff: Toggle between the working-tree review (`:CodeDiff`) and the `main`-to-working-tree comparison (`:CodeDiff main`).
- `gf`: Open the real file at the diff cursor in the previous tab; old-side lines are mapped to the working file and the destination is unfolded.
- `q`: Close the review and return to the editor.
- `]` / `[`: Move to the next/previous changed hunk; `Space jf` / `Space jF` moves between files.
- `X`: Discard the hunk under the cursor in a working-tree file diff, after confirmation.
- Reviews start in compact mode, showing changed hunks with three context lines. `gc` toggles compact mode; `t` toggles side-by-side and inline layouts.
- Double-click a file in the explorer or press `Enter` to open its diff.
- Pressing `Enter` focuses the diff pane rather than leaving focus in the explorer.
- The CodeDiff file explorer is on the right.

CodeDiff also provides PR review via `:CodeDiff pr <number>`. The previous Differ-specific persistent local review comments and custom PR-review mappings are removed; CodeDiff's native PR workflow is available, but those local notes are not migrated.

### Lazygit

- `Space + lg`: To open lazygit view
- `+` after `Enter` on a file to go to bigger diff view. 
- `Space`: To stage
- `c` to commit

### Mac issues

To bind keys with things like `Cmd`, we need to do a 2 step process. 
1. Go to `iterm2 -> Settings -> Keys -> Keybindings` and then attach each key combination you want with an escape sequence. 
2. Then go to Neovim, into insert mode, do `Ctrl + V, key combination` and note the output. 
3. Then go to `init.lua` and use that output for the shortcut you want.

Caution: Keybinding changes in `iTerm2` can have unintended consequences. 
IF anywhere in the keybinding menu, you have used `Esc`, it could mean needing to send `Esc` twice to be registered in `nvim`!


## Python

To use with Python and `uv` just do 
`uv run nvim .` from your root workspace folder. It should automatically find the correct `venv`. 

## Mason

Nvim LSP binaries are controlled by `Mason`.
Binaries are installed at `~/.local/share/nvim/mason/bin`.
To update binaries, try doing `:Mason` inside Neovim and doing `U`.

## Tests

Headless Neovim tests live in `nvim/tests`.

Install `uv` to run the review schema checks; the test helper declares its pinned
`jsonschema` dependency and runs through `uv`.

From the repo root, run them with:

```sh
cd nvim
nvim --headless -u init.lua "+lua require('tests.run').run()" +qa
```

## Remote issues

1. `ruff`

Zed cannot find `ruff` if it is setup as LSP but you are going to a remote session.
So first, make sure to duplicate the `settings.json` onto the remote session. 
Next, and this is annoying, make sure to start `zed` from a folder
where `ruff` is part of the `venv`. 
Otherwise, it mysteriously refuses to start `ruff` even though it maybe globally available. 

2. Clipboard / Copy-Paste

If copy-paste stops working on a remote VM (e.g., after SSH changes that break X11 forwarding), Neovim might try to use `xclip` and fail.
The config is set to use **OSC 52** by default when `$SSH_CONNECTION` or `$TMUX` is detected. This allows the terminal to handle the clipboard directly.

If you experience issues:
- Ensure your terminal emulator supports OSC 52.
- If inside `tmux`, ensure `set -g set-clipboard on` is in `tmux.conf`.
- Restart Neovim.

## Config init 

We are trying to do a simple single file `init.lua` setup. 
The starting points was [this](https://github.com/khuedoan/nvim-minimal/tree/master).
We have linked it to our base system using 

```sh
ln -s <full path to nvim git dir> ~/.config/nvim
```

## References

Go look at some of the settings [here](https://github.com/nvim-lua/kickstart.nvim/blob/master/init.lua) for inspiration. 

## Debugging

- `:checkhealth` is useful
- `:checkhealth vim.lsp` shows what is happening with LSP 

## LazyGit

1. LazyGit can open the GH PR page for a branch. Do the following
    - Push the branch
    - While focused on the branch view in LazyGit, press 'o' and it will open the PR page.

## ToDo

1. Make `Cmd + .` work to suggest imports.
    - Did this break esc?
    - Always need to press esc twice now
2. Make `Cmd + p` work to show recent files. 
3. Make all files open show up as tabs. 
