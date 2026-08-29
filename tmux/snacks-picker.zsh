#!/usr/bin/env zsh

# Reuse Neovim in the active tmux window; otherwise open a focused picker window.
set -euo pipefail

if (( $# != 2 )); then
	print -u2 "usage: $0 <window-id> <cwd>"
	exit 2
fi

window_id="$1"
cwd="$2"

nvim_pane="$(tmux list-panes -t "$window_id" -F '#{pane_id} #{pane_current_command}' | awk '$2 == "nvim" { print $1; exit }')"

if [[ -n "$nvim_pane" ]]; then
	tmux select-pane -t "$nvim_pane"
	tmux send-keys -t "$nvim_pane" Space s f
	exit 0
fi

tmux new-window -n Files -c "$cwd" "exec nvim '+lua Snacks.picker.files()'"
