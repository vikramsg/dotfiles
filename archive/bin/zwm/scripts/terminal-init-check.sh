#!/usr/bin/env bash
set -euo pipefail

readonly CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/zwm/config.json"
readonly ZED_DB="$HOME/Library/Application Support/Zed/db/0-stable/db.sqlite"

if [[ ! -f "$CONFIG_FILE" ]]; then
  printf 'Missing ZWM configuration: %s\n' "$CONFIG_FILE" >&2
  exit 1
fi

if [[ ! -f "$ZED_DB" ]]; then
  printf 'Missing Zed database: %s\n' "$ZED_DB" >&2
  exit 1
fi

readonly HOST="$(jq -er '.host | strings | select(length > 0)' "$CONFIG_FILE")"

printf 'Zed terminal records for %s:\n' "$HOST"
sqlite3 -readonly -header -column "$ZED_DB" "
  SELECT terminal_id, title, working_directory
  FROM sidebar_terminal_threads
  WHERE remote_connection LIKE '%\"Hostname\":\"$HOST\"%'
  ORDER BY created_at DESC;
"

printf '\nLive ZWM tmux sessions on %s:\n' "$HOST"
ssh -T -o BatchMode=yes "$HOST" "/home/linuxbrew/.linuxbrew/bin/tmux list-sessions -F '#{session_name}\t#{@zwm_worktree}'"

printf '\nReconciliation result:\n'
zwm status
