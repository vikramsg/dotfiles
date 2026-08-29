#!/usr/bin/env bash
set -euo pipefail

apply=false
if [[ $# -gt 0 ]]; then
  if [[ "$1" != "--apply" || $# -ne 1 ]]; then
    printf 'Usage: %s [--apply]\n' "${0##*/}" >&2
    exit 2
  fi
  apply=true
fi

printf 'Persisted active ZWM inventory:\n'
zwm list

printf '\nPlanned Zed workspace opens from current inventory:\n'
zwm restore --latest --dry-run

if [[ "$apply" == false ]]; then
  exit 0
fi

printf '\nApplying Zed restoration:\n'
zwm restore --latest --new-window
zwm status
