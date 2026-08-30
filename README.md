## Install instructions

First we need to install the basic stuff so we need instructions on that.

### just

```bash
sudo apt install just
```

### Utilities

All utilities required are part of the `Brewfile`.

```bash
just brew
```

Then do the following to setup dotfiles. 

```bash
just all
```

## Custom tools

Custom tools use a split layout:

- `bin/<tool>/` contains the implementation, package-local build definition and `justfile`, tests, and implementation docs.
- `<tool>/` at the repository root contains user-editable configuration and user-facing configuration docs.
- `lch/config.toml` declares persistent service lifecycle.
- The root `justfile` only links tool configuration and delegates build and installation to `bin/<tool>/justfile`.

## Troubleshooting

1. When initially installing on a machine, prefer first installing
    - `just brew`
    - `tmux`
    - `opencode2` - `npm install -g @opencode-ai/cli@beta`

## Why Zed

I routinely go between various options as my daily IDE/Agent orchestrator and I wanted to write down why I am currently sticking to Zed.
This is more so that if I do change I want to make sure I can figure out if its a net positive or not.

1. Image preview and drag and drop
  - I can see images in Zed
  - I can drag images onto the file manager.
2. Git diff 
  - The git diff viewer is way better than anything TUI based
  - I can edit, go to the file
3. Git shortcuts 
  - I have created git shortcuts that are almost LazyGit like
4. Fast
  - Zed is really fast so that I have no speed issues like VSCode
5. Terminal
  - The Zed terminal is modern and so I don't have to fight with it to get my prompts working
6. Vim
  - It has Vim mode so I don't have to relearn how to type
7. Magic
  - When I type it sometimes decide to make the editor area full screen. I love it.
8. Zero config
  - I essentially only setup some shortcuts and that's it.
  - Don't fight with LSP or Git Diff setup or whatever

### Why Not

1. The ssh experience is not nice. It loses state especially if there are multiple worktrees open and I have to start everyone of them
  - In Ghostty etc I can use `autossh` and am always connected.
  - That plus `tmux` means that I essentially never need to fiddle around with finding my sessions. 
2. Its not NeoVim
  - Ghostty is fast and nice but it does not feel as fast and as nice as NeoVim
3. There is no browser
  - Terminals can now have browsers. And so I have to always open another window to test in a browser
4. Port forwarding
  - Port forwarding is free in VSCode with a nice UI for it as well
  - Nothing else comes close to that experience not even on Ghostty/NeoVim etc.
5. `zed` CLI.
  - VSCode allows using the CLI even on remote VM's. Zed does not
