#!/usr/bin/env python3
"""
QLC+ OSC Control Script

Send OSC commands to QLC+ to control lighting modes.
Default QLC+ OSC port is 7700.

Usage:
    python3 osc_control.py off
    python3 osc_control.py audio
    python3 osc_control.py solid
    python3 osc_control.py manual
    python3 osc_control.py <custom_address> [value]
"""

import sys
from pythonosc import udp_client

# Configuration
QLCPLUS_HOST = "127.0.0.1"
QLCPLUS_OSC_PORT = 7700

# Predefined mode addresses (customize these in QLC+ Virtual Console)
MODES = {
    "off": "/lights/mode/off",
    "audio": "/lights/mode/audio",
    "solid": "/lights/mode/solid",
    "manual": "/lights/mode/manual",
}


def send_osc(address: str, value: float = 1.0):
    """Send an OSC message to QLC+."""
    client = udp_client.SimpleUDPClient(QLCPLUS_HOST, QLCPLUS_OSC_PORT)
    client.send_message(address, value)
    print(f"Sent: {address} = {value}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable modes:", ", ".join(MODES.keys()))
        sys.exit(1)

    command = sys.argv[1].lower()

    if command in MODES:
        send_osc(MODES[command], 1.0)
    elif command.startswith("/"):
        # Custom OSC address
        value = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
        send_osc(command, value)
    else:
        print(f"Unknown mode: {command}")
        print("Available modes:", ", ".join(MODES.keys()))
        sys.exit(1)


if __name__ == "__main__":
    main()
