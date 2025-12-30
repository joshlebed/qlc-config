#!/usr/bin/env python3
"""
QLC+ WebSocket Control Script

Control the ADJ Pinspot LED Quad DMX spotlight via QLC+ WebSocket API.
Uses setFunctionStatus for idempotent, direct function control.

Modes are idempotent - sending the same mode twice keeps the light in that state.

Usage:
    python3 ws_control.py off
    python3 ws_control.py red
    python3 ws_control.py yellow
    python3 ws_control.py white
    python3 ws_control.py --list        # List all functions
    python3 ws_control.py --status      # Show running functions
"""

import sys

from qlcplus import QLCPlusClient

# Function IDs from spotlight.qxw
# These are the Scene function IDs, not Virtual Console widget IDs
MODES = {
    "off": 0,      # mode_off
    "white": 1,    # mode_white
    "red": 2,      # mode_red
    "yellow": 3,   # mode_yellow
}


def set_mode(mode: str) -> bool:
    """
    Set the spotlight to a specific mode.

    This is idempotent - calling set_mode("red") twice keeps the light red.
    Handles mutual exclusion by stopping other modes first.

    Args:
        mode: One of "off", "red", "yellow", "white"

    Returns:
        True if successful, False if mode is unknown
    """
    if mode not in MODES:
        return False

    with QLCPlusClient() as client:
        # Stop all other modes first
        for other_mode, func_id in MODES.items():
            if other_mode != mode:
                client.stop_function(func_id)

        # Start the target mode
        client.start_function(MODES[mode])
        print(f"Set mode: {mode}")
        return True


def list_functions():
    """List all available functions in QLC+."""
    with QLCPlusClient() as client:
        functions = client.get_functions_list()
        print("Functions:")
        for func_id, name in sorted(functions.items()):
            print(f"  {func_id}: {name}")


def show_status():
    """Show the running status of all mode functions."""
    with QLCPlusClient() as client:
        print("Function status:")
        for mode, func_id in MODES.items():
            status = client.get_function_status(func_id)
            print(f"  {mode} (ID {func_id}): {status}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable modes:", ", ".join(MODES.keys()))
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "--list":
        list_functions()
    elif command == "--status":
        show_status()
    elif command in MODES:
        set_mode(command)
    else:
        print(f"Unknown command: {command}")
        print("Available modes:", ", ".join(MODES.keys()))
        print("Options: --list, --status")
        sys.exit(1)


if __name__ == "__main__":
    main()
