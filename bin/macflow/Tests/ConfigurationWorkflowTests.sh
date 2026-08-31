#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT=$(cd "$1" && pwd)
JUSTFILE="$REPOSITORY_ROOT/justfile"
TEMPORARY_DIRECTORY=$(mktemp -d)
trap 'rm -rf "$TEMPORARY_DIRECTORY"' EXIT

SCREENSHOT_DIRECTORY="$TEMPORARY_DIRECTORY/Screenshots"
SCREENSHOT_CONFIG="$TEMPORARY_DIRECTORY/screenshot.json"
MACFLOW_CONFIG="$TEMPORARY_DIRECTORY/macflow.json"
mkdir -p "$SCREENSHOT_DIRECTORY"

jq --arg directory "$SCREENSHOT_DIRECTORY" \
    '.screenshot_dir = $directory' \
    "$REPOSITORY_ROOT/screenshot/config.json" > "$SCREENSHOT_CONFIG"
jq --arg directory "$SCREENSHOT_DIRECTORY" '
    .screenshots.directory = $directory
    | (.shelves.screenshots.sources[] | select(.id == "local") | .directory) = $directory
    | (.surfaces["screenshots-web"].configuration.sources[] | select(.id == "local") | .directory) = $directory
' "$REPOSITORY_ROOT/macflow/config.json" > "$MACFLOW_CONFIG"

validate_directories() {
    SCREENSHOT_CONFIG="$SCREENSHOT_CONFIG" \
        MACFLOW_CONFIG="$MACFLOW_CONFIG" \
        just --justfile "$JUSTFILE" validate-screenshot-directories
}

expect_validation_failure() {
    local expected_message=$1
    if validate_directories > "$TEMPORARY_DIRECTORY/stdout" 2> "$TEMPORARY_DIRECTORY/stderr"; then
        echo "Expected screenshot-directory validation to fail" >&2
        exit 1
    fi
    grep -F "$expected_message" "$TEMPORARY_DIRECTORY/stderr" > /dev/null
}

validate_directories

jq '.screenshots.directory = "/mismatch"' "$MACFLOW_CONFIG" > "$TEMPORARY_DIRECTORY/changed.json"
mv "$TEMPORARY_DIRECTORY/changed.json" "$MACFLOW_CONFIG"
expect_validation_failure "Macflow capture directory"

jq --arg directory "$SCREENSHOT_DIRECTORY" '
    .screenshots.directory = $directory
    | (.shelves.screenshots.sources[] | select(.id == "local") | .directory) = "/mismatch"
' "$MACFLOW_CONFIG" > "$TEMPORARY_DIRECTORY/changed.json"
mv "$TEMPORARY_DIRECTORY/changed.json" "$MACFLOW_CONFIG"
expect_validation_failure "Macflow local shelf directory"

jq --arg directory "$SCREENSHOT_DIRECTORY" '
    (.shelves.screenshots.sources[] | select(.id == "local") | .directory) = $directory
    | (.surfaces["screenshots-web"].configuration.sources[] | select(.id == "local") | .directory) = "/mismatch"
' "$MACFLOW_CONFIG" > "$TEMPORARY_DIRECTORY/changed.json"
mv "$TEMPORARY_DIRECTORY/changed.json" "$MACFLOW_CONFIG"
expect_validation_failure "Macflow WebKit local shelf directory"

jq --arg directory "$SCREENSHOT_DIRECTORY" '
    (.surfaces["screenshots-web"].configuration.sources[] | select(.id == "local") | .directory) = $directory
    | (.shelves.screenshots.sources[] | select(.id == "remote") | .directory) = "/remote-native"
    | (.surfaces["screenshots-web"].configuration.sources[] | select(.id == "remote") | .directory) = "/remote-web"
' "$MACFLOW_CONFIG" > "$TEMPORARY_DIRECTORY/changed.json"
mv "$TEMPORARY_DIRECTORY/changed.json" "$MACFLOW_CONFIG"
validate_directories

TEST_HOME="$TEMPORARY_DIRECTORY/home"
TEST_XDG_CONFIG_HOME="$TEMPORARY_DIRECTORY/xdg"
mkdir -p "$TEST_HOME"
HOME="$TEST_HOME" XDG_CONFIG_HOME="$TEST_XDG_CONFIG_HOME" \
    just --justfile "$JUSTFILE" link-macflow-config

test -L "$TEST_XDG_CONFIG_HOME/macflow/config.json"
test -L "$TEST_XDG_CONFIG_HOME/macflow/ui"
test "$(readlink "$TEST_XDG_CONFIG_HOME/macflow/config.json")" = "$REPOSITORY_ROOT/macflow/config.json"
test "$(readlink "$TEST_XDG_CONFIG_HOME/macflow/ui")" = "$REPOSITORY_ROOT/macflow/ui"
test ! -e "$TEST_HOME/.config/macflow"
