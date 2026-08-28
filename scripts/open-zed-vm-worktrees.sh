#!/usr/bin/env bash
set -euo pipefail

# Open the Kunda main checkout and linked worktrees as separate remote Zed
# workspaces. This deliberately does not create or restore terminal threads.

readonly HOST="vm-us"
readonly OPEN_DELAY_SECONDS="${ZED_OPEN_DELAY_SECONDS:-3}"

readonly -a PATHS=(
  "/home/vikram_orbio_earth/projects/orbio/meanderx/kunda"
  "/home/vikram_orbio_earth/projects/orbio/meanderx/kunda-wt"
  "/home/vikram_orbio_earth/projects/orbio/meanderx/kunda-wt2"
)

usage() {
  printf 'Usage: %s --new|--reuse\n' "${0##*/}"
  printf '  --new    Create a new vm-us Zed window before adding worktrees.\n'
  printf '  --reuse  Add worktrees to an existing vm-us Zed window.\n'
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

if ! command -v zed >/dev/null; then
  printf 'Error: zed CLI is not available on PATH.\n' >&2
  exit 1
fi

open_workspace() {
  local flag="$1"
  local path="$2"

  zed "$flag" "ssh://${HOST}:${path}"
  sleep "$OPEN_DELAY_SECONDS"
}

case "$1" in
  --new)
    open_workspace -n "${PATHS[0]}"
    open_workspace -r "${PATHS[1]}"
    open_workspace -r "${PATHS[2]}"
    ;;
  --reuse)
    for path in "${PATHS[@]}"; do
      open_workspace -r "$path"
    done
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
