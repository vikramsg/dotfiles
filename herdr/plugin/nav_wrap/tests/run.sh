#!/usr/bin/env bash
#
# Behavioural tests for the dotfiles.nav-wrap action scripts. The mock herdr
# records the pane-focus calls the scripts issue; assertions are about the
# resulting call sequence, not about text output.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_root="$(dirname "$here")"
mock="$here/mock-herdr.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

failures=0
case_index=0

new_case() {
	case_index=$((case_index + 1))
	MOCK_STATE_DIR="$work/case$case_index"
	mkdir -p "$MOCK_STATE_DIR"
	export MOCK_STATE_DIR
	: >"$MOCK_STATE_DIR/transitions"
	: >"$MOCK_STATE_DIR/calls"
}

transition() {
	printf '%s %s %s\n' "$1" "$2" "$3" >>"$MOCK_STATE_DIR/transitions"
}

expect_calls() {
	local name="$1"
	shift
	local expected actual
	expected="$(printf '%s\n' "$@")"
	actual="$(cat "$MOCK_STATE_DIR/calls")"
	if [[ $expected != "$actual" ]]; then
		printf 'FAIL %s\n  expected: %s\n  actual:   %s\n' \
			"$name" "${expected//$'\n'/; }" "${actual//$'\n'/; }"
		failures=$((failures + 1))
	else
		printf 'ok   %s\n' "$name"
	fi
}

export HERDR_BIN_PATH="$mock"

# 1. Normal neighbour: one move, no wrap.
new_case
transition left p1 p2
HERDR_PANE_ID=p1 bash "$plugin_root/focus-wrap.sh" left p1
expect_calls "normal move left p1 -> p2" "focus left p1 -> p2"

# 2. Edge wrap across a row p1 p2 p3.
new_case
transition right p1 p2
transition right p2 p3
HERDR_PANE_ID=p1 bash "$plugin_root/focus-wrap.sh" left p1
expect_calls \
	"edge wrap left from p1 lands on p3" \
	"focus left p1 -> none" \
	"focus right p1 -> p2" \
	"focus right p2 -> p3" \
	"focus right p3 -> none"

# 3. Single pane terminates without moving.
new_case
HERDR_PANE_ID=p1 bash "$plugin_root/focus-wrap.sh" left p1
expect_calls \
	"single pane no-op" \
	"focus left p1 -> none" \
	"focus right p1 -> none"

# 4. Grid: repeated steps reach the far-right pane.
new_case
transition right p1 p2
transition right p2 p4
HERDR_PANE_ID=p1 bash "$plugin_root/focus-wrap.sh" left p1
expect_calls \
	"grid wrap reaches p4" \
	"focus left p1 -> none" \
	"focus right p1 -> p2" \
	"focus right p2 -> p4" \
	"focus right p4 -> none"

# 5. Vim foreground forwards the chord instead of moving focus.
new_case
export MOCK_FOREGROUND=nvim
HERDR_PANE_ID=p1 bash "$plugin_root/navigate.sh" left
expect_calls "vim forwards ctrl+h" "send-keys p1 ctrl+h"

# 6. Non-Vim foreground wraps panes.
new_case
transition right p1 p2
transition right p2 p3
unset MOCK_FOREGROUND
HERDR_PANE_ID=p1 bash "$plugin_root/navigate.sh" left
expect_calls \
	"non-vim navigate wraps" \
	"focus left p1 -> none" \
	"focus right p1 -> p2" \
	"focus right p2 -> p3" \
	"focus right p3 -> none"

if ((failures)); then
	printf '\n%d test(s) failed\n' "$failures" >&2
	exit 1
fi
printf '\nall focus-wrap/navigate tests passed\n'
