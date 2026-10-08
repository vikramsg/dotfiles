#!/bin/sh
set -eu

case "$(uname -s)" in
    Darwin)
        if ! command -v brew >/dev/null 2>&1; then
            echo "ERROR: Homebrew is required to install Fresh on macOS." >&2
            exit 1
        fi
        brew install fresh-editor
        ;;
    Linux)
        INSTALL_DIR=${FRESH_INSTALL_DIR:-"$HOME/.local/share/fresh-editor"}
        BIN_DIR=${FRESH_BIN_DIR:-"$HOME/.local/bin"}

        if [ -L "$INSTALL_DIR" ]; then
            echo "ERROR: refusing to install through symlink $INSTALL_DIR." >&2
            exit 1
        fi

        if [ -d "$INSTALL_DIR" ]; then
            DATABASE_FILE=$(find "$INSTALL_DIR" -type f \( -iname '*.sqlite' -o -iname '*.db' \) -print -quit)
            if [ -n "$DATABASE_FILE" ]; then
                echo "ERROR: Fresh's installer replaces $INSTALL_DIR, which contains a database:" >&2
                echo "  $DATABASE_FILE" >&2
                echo "Move that database before installing Fresh." >&2
                exit 1
            fi
        fi

        INSTALLER=$(mktemp)
        trap 'rm -f "$INSTALLER"' EXIT
        curl -fsSL https://raw.githubusercontent.com/sinelaw/fresh/refs/heads/master/scripts/install.sh -o "$INSTALLER"

        FRESH_INSTALL_DIR="$INSTALL_DIR" \
            FRESH_BIN_DIR="$BIN_DIR" \
            sh "$INSTALLER" --method=tarball --no-desktop-integration
        ;;
    *)
        echo "ERROR: Fresh installation supports macOS and Linux only." >&2
        exit 1
        ;;
esac
