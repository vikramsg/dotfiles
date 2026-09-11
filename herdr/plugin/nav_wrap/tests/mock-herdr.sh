#!/usr/bin/env bash
#
# Test double for the herdr CLI. It implements only the calls focus-wrap.sh and
# navigate.sh make, driven by environment fixtures:
#
#   MOCK_STATE_DIR    required; logs calls and holds the transitions file
#   MOCK_FOREGROUND   process name returned by `pane process-info` (default bash)
#
# The transitions file ($MOCK_STATE_DIR/transitions) has one line per move:
#   <direction> <source> <target>
# A missing line means no neighbour at that edge.

set -euo pipefail

state_dir="${MOCK_STATE_DIR:?MOCK_STATE_DIR is required}"
calls="$state_dir/calls"

log_call() {
	printf '%s\n' "$*" >>"$calls"
}

json_focus() {
	local changed="$1" source="$2" target="$3"
	if [[ $changed == true ]]; then
		printf '{"result":{"type":"pane_focus_direction","focus":{"changed":true,"source_pane_id":"%s","focused_pane_id":"%s","layout":{}}}}\n' "$source" "$target"
	else
		printf '{"result":{"type":"pane_focus_direction","focus":{"changed":false,"reason":"no_neighbor","source_pane_id":"%s","focused_pane_id":"%s","layout":{}}}}\n' "$source" "$source"
	fi
}

if [[ ${1:-} != pane ]]; then
	printf 'mock-herdr: unsupported command: %s\n' "$*" >&2
	exit 2
fi
shift

case "${1:-}" in
	focus)
		shift
		direction="" source=""
		while (($#)); do
			case "$1" in
				--direction)
					direction="$2"
					shift 2
					;;
				--pane)
					source="$2"
					shift 2
					;;
				--current)
					source="${HERDR_PANE_ID:-current}"
					shift
					;;
				*) shift ;;
			esac
		done
		target="$(awk -v d="$direction" -v s="$source" '$1 == d && $2 == s { print $3; found = 1 } END { if (!found) print "" }' "$state_dir/transitions" 2>/dev/null || true)"
		if [[ -n $target ]]; then
			log_call "focus $direction $source -> $target"
			json_focus true "$source" "$target"
		else
			log_call "focus $direction $source -> none"
			json_focus false "$source" ""
		fi
		;;
	process-info)
		shift
		source=""
		while (($#)); do
			case "$1" in
				--pane)
					source="$2"
					shift 2
					;;
				--current)
					source="${HERDR_PANE_ID:-current}"
					shift
					;;
				*) shift ;;
			esac
		done
		foreground="${MOCK_FOREGROUND:-bash}"
		printf '{"result":{"type":"pane_process_info","process_info":{"pane_id":"%s","foreground_processes":[{"name":"%s"}]}}}\n' "$source" "$foreground"
		;;
	send-keys)
		shift
		source="${1:-}"
		key="${2:-}"
		log_call "send-keys $source $key"
		printf '{"result":{"type":"pane_info"}}\n'
		;;
	*)
		printf 'mock-herdr: unsupported pane subcommand: %s\n' "$*" >&2
		exit 2
		;;
esac
