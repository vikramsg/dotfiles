#!/bin/zsh

# Opens the Snacks file picker in an existing Neovim pane in the active Herdr
# tab. When no such pane exists, it creates a focused Files tab and starts a
# new Neovim picker there. Herdr invokes this from the prefix+f binding.
set -euo pipefail

herdr_bin="${HERDR_BIN_PATH:-herdr}"
socket_path="${HERDR_SOCKET_PATH:-$HOME/.config/herdr/herdr.sock}"

# Custom key commands receive these variables from Herdr. The CLI lookup keeps
# the script usable when invoked directly during local debugging.
current_pane="$($herdr_bin pane current --current)"
workspace_id="${HERDR_ACTIVE_WORKSPACE_ID:-$(jq -er '.result.pane.workspace_id' <<<"$current_pane")}"
tab_id="${HERDR_ACTIVE_TAB_ID:-$(jq -er '.result.pane.tab_id' <<<"$current_pane")}"
cwd="${HERDR_ACTIVE_PANE_CWD:-$(jq -er '.result.pane.cwd' <<<"$current_pane")}"

# Restrict detection to the active tab so another workspace's Neovim is never
# interrupted by this shortcut.
pane_ids=("${(@f)$("$herdr_bin" pane list --workspace "$workspace_id" | jq -r --arg tab_id "$tab_id" '.result.panes[] | select(.tab_id == $tab_id) | .pane_id')}")

# The Herdr CLI only focuses panes directionally. Its Unix-socket API accepts
# an exact pane ID, allowing the selected Neovim pane to receive keyboard input.
focus_pane() {
	local pane_id="$1"
	local request

	request="$(jq -cn --arg id "snacks-picker-$$" --arg pane_id "$pane_id" '{ id: $id, method: "pane.focus", params: { pane_id: $pane_id } }')"
	printf '%s\n' "$request" | nc -U "$socket_path" | jq -e '.result.type == "pane_info"' >/dev/null
}

for pane_id in "${pane_ids[@]}"; do
	process_info="$("$herdr_bin" pane process-info --pane "$pane_id")"
	if jq -e 'any(.result.process_info.foreground_processes[]?; (.name | sub("\\.exe$"; "") == "nvim"))' >/dev/null <<<"$process_info"; then
		focus_pane "$pane_id"
		# Neovim maps <Space>sf to Snacks.picker.files().
		"$herdr_bin" pane send-keys "$pane_id" space s f
		exit 0
	fi
done

# No Neovim pane is open in this tab: create a visible fallback picker tab.
response="$("$herdr_bin" tab create --workspace "$workspace_id" --cwd "$cwd" --label Files --focus)"
pane_id="$(jq -er '.result.root_pane.pane_id' <<<"$response")"
"$herdr_bin" pane run "$pane_id" "exec nvim '+lua Snacks.picker.files()'"
