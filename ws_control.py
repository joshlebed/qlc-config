#!/usr/bin/env python3
"""
QLC+ WebSocket Control Script

Control the ADJ Pinspot LED Quad DMX spotlight via QLC+ WebSocket API.
Uses setFunctionStatus for idempotent, direct function control.

Modes are idempotent - sending the same mode twice keeps the light in that state.

Usage:
    python3 ws_control.py off
    python3 ws_control.py red
    python3 ws_control.py reactive    # Beat-reactive mode
    python3 ws_control.py --list      # List all functions
    python3 ws_control.py --status    # Show running functions
"""

import sys

from qlcplus import MODES, QLCPlusClient
from qlcplus import set_mode as _set_mode


def set_mode(mode: str) -> bool:
    """Set mode and print confirmation."""
    if _set_mode(mode):
        print(f"Set mode: {mode}")
        return True
    return False


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
    all_modes = [*MODES.keys(), "reactive"]

    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable modes:", ", ".join(all_modes))
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "--list":
        list_functions()
    elif command == "--status":
        show_status()
    elif command in all_modes:
        set_mode(command)
    else:
        print(f"Unknown command: {command}")
        print("Available modes:", ", ".join(all_modes))
        print("Options: --list, --status")
        sys.exit(1)


if __name__ == "__main__":
    main()
