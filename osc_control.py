#!/usr/bin/env python3
"""
QLC+ OSC Control Script

Send OSC commands to QLC+ to control the ADJ Pinspot LED Quad DMX spotlight.

Modes are idempotent - sending the same mode twice keeps the light in that mode
(it does not toggle off). Modes are mutually exclusive - activating one mode
automatically deactivates the others.

Usage:
    python3 osc_control.py off
    python3 osc_control.py red
    python3 osc_control.py yellow
    python3 osc_control.py white
    python3 osc_control.py <custom_address> [value]
"""

import os
import sys
from pythonosc import udp_client

# Configuration - can override with environment variables
QLCPLUS_HOST = os.environ.get("QLCPLUS_HOST", "192.168.0.221")
QLCPLUS_OSC_PORT = int(os.environ.get("QLCPLUS_PORT", "7701"))

# OSC paths for Virtual Console buttons
# Buttons use Flash mode for idempotent behavior
MODES = {
    "off": "/mode/off",
    "red": "/mode/red",
    "yellow": "/mode/yellow",
    "white": "/mode/white",
}


def send_osc(address: str, value: float = 1.0):
    """Send an OSC message to QLC+."""
    client = udp_client.SimpleUDPClient(QLCPLUS_HOST, QLCPLUS_OSC_PORT)
    client.send_message(address, value)
    print(f"Sent: {address} = {value}")


def set_mode(mode: str) -> bool:
    """
    Set the spotlight to a specific mode.

    Modes are idempotent - calling set_mode("red") twice keeps the light red.
    Modes are mutually exclusive - setting a new mode deactivates the previous one.

    Args:
        mode: One of "off", "red", "yellow", "white"

    Returns:
        True if the command was sent, False if mode is unknown
    """
    if mode not in MODES:
        return False
    client = udp_client.SimpleUDPClient(QLCPLUS_HOST, QLCPLUS_OSC_PORT)
    # Turn off all other modes first (Flash mode: 0.0 = off)
    for other_mode, path in MODES.items():
        if other_mode != mode:
            client.send_message(path, 0.0)
    # Turn on the target mode
    client.send_message(MODES[mode], 1.0)
    print(f"Set mode: {mode}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable modes:", ", ".join(MODES.keys()))
        sys.exit(1)

    command = sys.argv[1].lower()

    if command in MODES:
        set_mode(command)
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
