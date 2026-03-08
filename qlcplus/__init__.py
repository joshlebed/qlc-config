"""
QLC+ WebSocket Client Library

A Python library for controlling QLC+ lighting software via WebSocket API.
"""

from .client import QLCPlusClient, QLCPlusError

__version__ = "0.1.0"

# Function IDs from spotlight.qxw
# All modes are mutually exclusive
MODES: dict[str, int] = {
    "off": 0,
    "white": 1,
    "red": 2,
    "yellow": 3,
    "fade": 4,  # Rainbow fade chaser
    "orange": 5,
    "green": 6,
    "cyan": 7,
    "blue": 8,
    "purple": 9,
    "pink": 10,
    "yellow_pretty": 16,
}

# Beat-reactive chaser (controlled via Cue List with MIDI input)
REACTIVE_CHASER_ID = 14


def _stop_reactive(client: QLCPlusClient) -> None:
    """Stop the reactive mode."""
    client.stop_function(REACTIVE_CHASER_ID)


def _start_reactive(client: QLCPlusClient) -> None:
    """Start the reactive mode."""
    client.start_function(REACTIVE_CHASER_ID)


def set_mode(mode: str) -> bool:
    """
    Set the spotlight to a specific mode.

    This is idempotent and handles mutual exclusion - calling set_mode("red")
    twice keeps the light red, and stops any other running mode (including
    the beat-reactive chaser).

    Args:
        mode: One of the keys in MODES, or "reactive" for beat-reactive mode

    Returns:
        True if successful, False if mode is unknown
    """
    is_reactive = mode == "reactive"

    if not is_reactive and mode not in MODES:
        return False

    with QLCPlusClient() as client:
        # Stop reactive mode
        _stop_reactive(client)

        # Stop all static modes
        for other_mode, func_id in MODES.items():
            if other_mode != mode:
                client.stop_function(func_id)

        if is_reactive:
            _start_reactive(client)
        else:
            client.start_function(MODES[mode])

        return True


__all__ = ["MODES", "QLCPlusClient", "QLCPlusError", "set_mode"]
