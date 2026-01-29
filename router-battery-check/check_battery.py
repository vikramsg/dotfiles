#!/usr/bin/env -S uv run --python 3.14t
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
# ]
# ///

"""
This script checks the battery status of a router via its API and sends a native macOS
notification if the battery level falls below a specified threshold and the device is
not currently charging.

Usage:
    ./check_battery.py (directly via uv)
"""

import requests
from requests.auth import HTTPDigestAuth
from dotenv import load_dotenv
import json
import os
import logging
import subprocess
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
ROUTER_IP = os.getenv("ROUTER_IP")
ROUTER_USER = os.getenv("ROUTER_USER")
ROUTER_PASS = os.getenv("ROUTER_PASS")
LOW_BATTERY_THRESHOLD = int(os.getenv("LOW_BATTERY_THRESHOLD", "20"))


def send_notification(message):
    """Sends a native macOS notification via AppleScript."""
    os.system(
        f'osascript -e "display notification \\"{message}\\" with title \\"Router Alert\\" sound name \\"Glass\\""'
    )


def get_local_wifi_signal():
    """Probes the local Wi-Fi RSSI (Signal Strength) on macOS."""
    try:
        # system_profiler is more reliable on modern macOS than the deprecated airport utility
        cmd = "system_profiler SPAirPortDataType | awk '/Current Network Information:/, /Signal \\/ Noise:/' | grep 'Signal / Noise'"
        output = subprocess.check_output(cmd, shell=True).decode("utf-8")
        # Example output: "Signal / Noise: -62 dBm / -96 dBm"
        match = re.search(r"Signal / Noise: (-?\d+) dBm", output)
        if match:
            return f"{match.group(1)} dBm"
    except Exception as e:
        logger.debug(f"Failed to get local Wi-Fi signal: {e}")
    return "Unknown"


def check_battery():
    if not all([ROUTER_IP, ROUTER_USER, ROUTER_PASS]):
        logger.error("ROUTER_IP, ROUTER_USER, and ROUTER_PASS must be set in .env")
        return

    # Ensure credentials are strings for HTTPDigestAuth
    user = str(ROUTER_USER)
    passwd = str(ROUTER_PASS)

    url = f"http://{ROUTER_IP}/sl4a"
    auth = HTTPDigestAuth(user, passwd)
    payload = {"id": 1, "method": "getDeviceState", "params": []}

    try:
        # Using digest auth as discovered during probing
        response = requests.post(
            url,
            json=payload,
            auth=auth,
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()

        if data is None:
            logger.error("Received empty response from router")
            return

        result = data.get("result")
        if result is None:
            logger.error(f"No 'result' field in router response. Response: {data}")
            return

        level = int(result.get("BatteryLevel", 0))
        status = result.get("BatteryStatus", "Unknown")
        router_signal = result.get("Signal", "Unknown")
        local_signal = get_local_wifi_signal()

        # Fetch session data
        rx_session = (
            requests.post(
                url,
                json={"id": 1, "method": "getMobileCurrentRxBytes", "params": []},
                auth=auth,
                timeout=5,
            )
            .json()
            .get("result", "0 B")
        )
        tx_session = (
            requests.post(
                url,
                json={"id": 1, "method": "getMobileCurrentTxBytes", "params": []},
                auth=auth,
                timeout=5,
            )
            .json()
            .get("result", "0 B")
        )

        logger.info(f"Battery Level: {level}%")
        logger.info(f"Status: {status}")
        logger.info(f"Router Signal (Cellular): {router_signal}/5 bars")
        logger.info(f"Local Signal (Wi-Fi): {local_signal}")
        logger.info(f"Session Download: {rx_session}")
        logger.info(f"Session Upload: {tx_session}")

        # Send notification only if battery is below threshold and NOT currently charging
        if level <= LOW_BATTERY_THRESHOLD and status != "Charging":
            send_notification(f"Battery Low: {level}% ({status})")
        else:
            logger.info("Battery is sufficient or charging. No alert sent.")

    except Exception as e:
        logger.error(f"Error checking battery: {e}")


if __name__ == "__main__":
    check_battery()
