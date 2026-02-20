#!/usr/bin/env -S uv run --python 3.14t
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "requests",
#   "python-dotenv",
#   "pyobjc-framework-CoreWLAN",
# ]
# ///

"""
This script checks the battery status of a router via its API and sends a native macOS
notification if the battery level falls below a specified threshold and the device is
not currently charging.

Usage:
    ./check_battery.py (directly via uv)
"""

import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import CoreWLAN
import requests
from dotenv import load_dotenv
from requests.auth import HTTPDigestAuth

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
        iface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interface()
        rssi = iface.rssiValue()
        return f"{rssi} dBm"
    except Exception as e:
        logger.debug(f"Failed to get Wi-Fi signal via CoreWLAN: {e}")

    # Fallback to system_profiler if CoreWLAN fails or is unavailable
    try:
        cmd = "system_profiler SPAirPortDataType | awk '/Current Network Information:/, /Signal \\/ Noise:/' | grep 'Signal / Noise'"
        output = subprocess.check_output(cmd, shell=True).decode("utf-8")
        match = re.search(r"Signal / Noise: (-?\d+) dBm", output)
        if match:
            return f"{match.group(1)} dBm"
    except Exception as e:
        logger.debug(f"Failed to get local Wi-Fi signal via fallback: {e}")
    return "Unknown"


def fetch_router_data(auth, url, method):
    """Generic function to fetch data from the router API."""
    payload = {"id": 1, "method": method, "params": []}
    try:
        response = requests.post(url, json=payload, auth=auth, timeout=5)
        response.raise_for_status()
        return response.json().get("result")
    except Exception as e:
        logger.error(f"Error fetching {method}: {e}")
        return None


def process_results(results):
    """Common logic to process and log the results from both sync and threaded versions."""
    device_state, rx_session, tx_session, local_signal = results

    if not device_state:
        logger.error("Failed to retrieve device state")
        return

    level = int(device_state.get("BatteryLevel", 0))
    status = device_state.get("BatteryStatus", "Unknown")
    router_signal = device_state.get("Signal", "Unknown")

    logger.info(f"Battery Level: {level}%")
    logger.info(f"Status: {status}")
    logger.info(f"Router Signal (Cellular): {router_signal}/5 bars")
    logger.info(f"Local Signal (Wi-Fi): {local_signal}")
    logger.info(f"Session Download: {rx_session or '0 B'}")
    logger.info(f"Session Upload: {tx_session or '0 B'}")

    if level <= LOW_BATTERY_THRESHOLD and status != "Charging":
        send_notification(f"Battery Low: {level}% ({status})")
    else:
        logger.info("Battery is sufficient or charging. No alert sent.")


def check_battery():
    """Version of the battery check using concurrency."""
    if not all([ROUTER_IP, ROUTER_USER, ROUTER_PASS]):
        logger.error("ROUTER_IP, ROUTER_USER, and ROUTER_PASS must be set in .env")
        return

    url = f"http://{ROUTER_IP}/sl4a"
    auth = HTTPDigestAuth(str(ROUTER_USER), str(ROUTER_PASS))

    with ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(fetch_router_data, auth, url, "getDeviceState")
        f2 = executor.submit(fetch_router_data, auth, url, "getMobileCurrentRxBytes")
        f3 = executor.submit(fetch_router_data, auth, url, "getMobileCurrentTxBytes")
        f4 = executor.submit(get_local_wifi_signal)

        results = (f1.result(), f2.result(), f3.result(), f4.result())

    process_results(results)


if __name__ == "__main__":
    # Defaulting to concurrent version for normal use
    check_battery()
