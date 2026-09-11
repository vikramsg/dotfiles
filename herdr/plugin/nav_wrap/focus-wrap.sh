#!/usr/bin/env bash
#
# Shared focus-or-wrap helper for dotfiles.nav-wrap.
#
# Moves focus one pane in <direction>. When the source pane is already at that
# edge, it walks in the opposite direction to the far edge and leaves focus
# there, matching tmux's select-pane wrap-around. It reuses Herdr's own spatial
# movement, so grid layouts resolve exactly like native navigation.
#
# Usage: focus-wrap.sh <left|down|up|right> [source-pane-id]
# The source pane defaults to $HERDR_PANE_ID.

set -euo pipefail

dir="${1:?usage: focus-wrap.sh <left|down|up|right> [source-pane-id]}"
herdr="${HERDR_BIN_PATH:-herdr}"
pane="${2:-${HERDR_PANE_ID:-}}"

case "$dir" in
	left) opposite="right" ;;
	right) opposite="left" ;;
	up) opposite="down" ;;
	down) opposite="up" ;;
	*)
		printf 'focus-wrap.sh: unknown direction: %s\n' "$dir" >&2
		exit 2
		;;
esac

focus() {
	if [[ -n $pane ]]; then
		"$herdr" pane focus --direction "$1" --pane "$pane"
	else
		"$herdr" pane focus --direction "$1" --current
	fi
}

response="$(focus "$dir")"
if jq -e '.result.focus.changed' >/dev/null 2>&1 <<<"$response"; then
	exit 0
fi

# At the edge in $dir: walk the opposite direction to the far edge.
while true; do
	response="$(focus "$opposite")"
	if ! jq -e '.result.focus.changed' >/dev/null 2>&1 <<<"$response"; then
		break
	fi
	pane="$(jq -r '.result.focus.focused_pane_id // empty' <<<"$response")"
	[[ -n $pane ]] || break
done
