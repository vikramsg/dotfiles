# Router Battery Check

A macOS background service that monitors your router's battery level and sends native notifications when it's low, preventing unexpected shutdowns.

It uses native macOS `launchd` for scheduling and `osascript` for alerts.

## Quick Start

Use the `manage.sh` script to handle everything:

```bash
# 1. Run an immediate probe
./manage.sh probe

# 2. Schedule it to run periodically (via launchd)
./manage.sh install

# 3. Check status and logs
./manage.sh status
./manage.sh logs

# 4. Stop the periodic checks
./manage.sh uninstall
```

## Configuration

### Credentials & Settings (.env)
Copy the example environment file and fill in your router's details:
```bash
cp .env.example .env
```
Settings available in `.env`:
- `ROUTER_IP`: IP address of your router.
- `ROUTER_USER`: Username for router login.
- `ROUTER_PASS`: Password for router login.
- `LOW_BATTERY_THRESHOLD`: Battery percentage to trigger alert (default: `20`).

### Interval (Frequency)
The frequency of the check is controlled in `manage.sh`. 
1. Open `manage.sh`.
2. Find the `INTERVAL` variable (set in seconds).
3. Change it (e.g., `3600` for 1 hour).
4. Run `./manage.sh install` to apply the change.

## How Notifications Work

The script checks the router periodically (default 15 mins). It will only send a macOS notification if:
1.  **Battery Level** is 20% or lower.
2.  **Battery Status** is NOT "Charging".

### Logs
When running via `launchd`, you can check the logs using `./manage.sh logs` or directly:
- **Output:** `/tmp/com.vikramsingh.router-battery-check.log`
- **Errors:** `/tmp/com.vikramsingh.router-battery-check.err`

### Test Your Notifications
To verify that your Mac is correctly receiving notifications from this script, you can run:
```bash
osascript -e 'display notification "Testing the router alert!" with title "Router Alert" sound name "Glass"'
```

## Requirements
- [uv](https://github.com/astral-sh/uv) installed on your Mac.
- Router accessible on your local network.
- macOS (for `launchd` and `osascript` notifications).
