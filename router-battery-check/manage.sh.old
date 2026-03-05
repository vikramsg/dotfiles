#!/bin/bash

# manage.sh - Tool for managing the router battery check service.
# 
# This script provides commands to:
#   probe: Run the battery check immediately for testing.
#   install: Set up a macOS Launch Agent to run the check periodically.
#   uninstall: Remove the macOS Launch Agent.
#   status: Check if the background job is running.
#   logs: View the output and error logs.

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_SCRIPT="$SCRIPT_DIR/check_battery.py"
UV_PATH=$(which uv)
LABEL="com.vikramsingh.router-battery-check"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
INTERVAL=900 # 15 minutes in seconds

usage() {
    echo "Usage: $0 [probe|install|uninstall|status|logs]"
    echo "  probe      - Run the battery check immediately"
    echo "  install    - Add the battery check to launchd"
    echo "  uninstall  - Remove the battery check from launchd"
    echo "  status     - Show status of the background job"
    echo "  logs       - Show output and error logs"
    exit 1
}

case "$1" in
    probe)
        echo "Running battery probe..."
        "$PYTHON_SCRIPT"
        ;;
    install)
        echo "Installing launch agent..."
        # Unload if already exists to ensure a clean update
        launchctl unload "$PLIST_PATH" 2>/dev/null
        
        cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$UV_PATH</string>
        <string>run</string>
        <string>--script</string>
        <string>$PYTHON_SCRIPT</string>
    </array>
    <key>StartInterval</key>
    <integer>$INTERVAL</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/$LABEL.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/$LABEL.err</string>
</dict>
</plist>
EOF
        launchctl load "$PLIST_PATH"
        echo "Launch agent installed and loaded: $PLIST_PATH"
        echo "Note: The first run is triggered immediately. Check './manage.sh logs' in a few seconds."
        ;;
    uninstall)
        echo "Uninstalling launch agent..."
        launchctl unload "$PLIST_PATH" 2>/dev/null
        rm -f "$PLIST_PATH"
        echo "Launch agent removed."
        ;;
    status)
        echo "Checking launch agent status..."
        if launchctl list | grep -q "$LABEL"; then
            echo "Status: Loaded"
            launchctl list "$LABEL"
        else
            echo "Status: Not loaded"
        fi
        ;;
    logs)
        echo "--- Latest Output Log (/tmp/$LABEL.log) ---"
        tail -n 20 "/tmp/$LABEL.log" 2>/dev/null || echo "No logs found."
        echo ""
        echo "--- Latest Error Log (/tmp/$LABEL.err) ---"
        tail -n 20 "/tmp/$LABEL.err" 2>/dev/null || echo "No error logs found."
        ;;
    *)
        usage
        ;;
esac
