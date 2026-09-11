#!/usr/bin/env bash
#
# Herdr action for dotfiles.nav-wrap: Ctrl+h/j/k/l.
#
# When Vim/Neovim is the foreground process, forward the chord into the pane so
# the editor moves between its own splits and crosses back out through the
# shared focus-wrap.sh helper at a split edge. Otherwise move or wrap Herdr
# pane focus directly.

set -euo pipefail

dir="${1:?usage: navigate.sh <left|down|up|right>}"
herdr="${HERDR_BIN_PATH:-herdr}"
pane="${HERDR_PANE_ID:-}"

case "$dir" in
	left) key="ctrl+h" ;;
	down) key="ctrl+j" ;;
	up) key="ctrl+k" ;;
	right) key="ctrl+l" ;;
	*)
		printf 'navigate.sh: unknown direction: %s\n' "$dir" >&2
		exit 2
		;;
esac

vim_re='^g?(view|l?n?vim?x?)(diff)?$'

if [[ -n $pane ]] && command -v jq >/dev/null 2>&1; then
	if "$herdr" pane process-info --pane "$pane" 2>/dev/null |
		jq -e --arg vim "$vim_re" \
			'.result.process_info.foreground_processes[]?.name
			 | ascii_downcase
			 | select(test($vim))' >/dev/null 2>&1; then
		exec "$herdr" pane send-keys "$pane" "$key"
	fi
fi

exec "$(dirname "$0")/focus-wrap.sh" "$dir" "$pane"
