# Keypad Service Integration Guide

This document is for the engineer/agent integrating the `qlcplus` package into the keypad service running on the other server.

## Overview

The keypad service needs to control a QLC+ lighting server via WebSocket. The `qlcplus` package provides a clean Python client for this purpose.

**Network topology:**
```
┌─────────────────────┐                      ┌─────────────────────┐
│  Keypad Service     │    WebSocket:9999    │  QLC+ Server        │
│  (your server)      │ ──────────────────▶  │  192.168.0.221      │
│                     │                      │                     │
│  Hardware keypad    │                      │  USB-DMX adapter    │
│  ↓                  │                      │  ↓                  │
│  Python service     │                      │  ADJ Pinspot light  │
└─────────────────────┘                      └─────────────────────┘
```

## Installation

### Option 1: Add to pyproject.toml (Recommended)

```toml
[project]
dependencies = [
    "qlcplus @ git+https://github.com/joshlebed/qlc-config.git",
    # ... other deps
]
```

Then run:
```bash
uv sync
```

### Option 2: Direct install

```bash
uv pip install git+https://github.com/joshlebed/qlc-config.git
```

### Option 3: Pin to specific version

```toml
dependencies = [
    "qlcplus @ git+https://github.com/joshlebed/qlc-config.git@v0.1.0",
]
```

## Quick Start

```python
from qlcplus import QLCPlusClient

# Set the light to red
with QLCPlusClient(host="192.168.0.221") as client:
    client.stop_function(0)   # Stop mode_off
    client.stop_function(1)   # Stop mode_white
    client.stop_function(3)   # Stop mode_yellow
    client.start_function(2)  # Start mode_red
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QLCPLUS_HOST` | `192.168.0.221` | QLC+ server IP |
| `QLCPLUS_WS_PORT` | `9999` | WebSocket port |

Set these in your service's environment:
```bash
export QLCPLUS_HOST=192.168.0.221
```

Or pass directly to the client:
```python
client = QLCPlusClient(host="192.168.0.221", port=9999)
```

## Function Reference

These are the available lighting modes (QLC+ Scene functions):

| ID | Name | Description | DMX Values |
|----|------|-------------|------------|
| 0 | `mode_off` | Light off | All channels 0 |
| 1 | `mode_white` | Bright white | RGBW=255, Dimmer=255 |
| 2 | `mode_red` | Red | R=255, Dimmer=255 |
| 3 | `mode_yellow` | Yellow | R=255, G=255, Dimmer=255 |

## Recommended Integration Pattern

### SpotlightController Class

Here's a recommended wrapper class for your keypad service:

```python
"""
Spotlight controller for keypad service integration.
"""

from qlcplus import QLCPlusClient, QLCPlusError


class SpotlightController:
    """
    Controls the ADJ Pinspot LED Quad DMX spotlight via QLC+.

    Provides idempotent mode switching with automatic mutual exclusion.
    """

    # Function IDs from QLC+ project
    MODES = {
        "off": 0,
        "white": 1,
        "red": 2,
        "yellow": 3,
    }

    def __init__(self, host: str = "192.168.0.221", port: int = 9999):
        self.host = host
        self.port = port
        self._current_mode: str | None = None

    def set_mode(self, mode: str) -> bool:
        """
        Set the spotlight to a specific mode.

        Idempotent: calling set_mode("red") twice is safe.
        Exclusive: activating one mode deactivates all others.

        Args:
            mode: One of "off", "red", "yellow", "white"

        Returns:
            True if successful, False if mode unknown

        Raises:
            QLCPlusError: If connection to QLC+ fails
        """
        if mode not in self.MODES:
            return False

        # Skip if already in this mode (optimization)
        if mode == self._current_mode:
            return True

        with QLCPlusClient(host=self.host, port=self.port) as client:
            # Stop all other modes first
            for name, func_id in self.MODES.items():
                if name != mode:
                    client.stop_function(func_id)

            # Start the target mode
            client.start_function(self.MODES[mode])

        self._current_mode = mode
        return True

    def off(self) -> bool:
        """Turn the spotlight off."""
        return self.set_mode("off")

    def red(self) -> bool:
        """Set spotlight to red."""
        return self.set_mode("red")

    def yellow(self) -> bool:
        """Set spotlight to yellow."""
        return self.set_mode("yellow")

    def white(self) -> bool:
        """Set spotlight to white."""
        return self.set_mode("white")

    def get_status(self) -> dict[str, str]:
        """
        Get the running status of all modes.

        Returns:
            Dict mapping mode name to status ("Running" or "Stopped")
        """
        with QLCPlusClient(host=self.host, port=self.port) as client:
            return {
                name: client.get_function_status(func_id)
                for name, func_id in self.MODES.items()
            }
```

### Usage in Keypad Handler

```python
from spotlight_controller import SpotlightController
from qlcplus import QLCPlusError

# Initialize once at startup
spotlight = SpotlightController(host="192.168.0.221")

def handle_keypad_event(key: int) -> None:
    """Handle a keypad button press."""
    try:
        match key:
            case 1:
                spotlight.off()
            case 2:
                spotlight.red()
            case 3:
                spotlight.yellow()
            case 4:
                spotlight.white()
            case _:
                print(f"Unknown key: {key}")
    except QLCPlusError as e:
        print(f"Failed to control spotlight: {e}")
        # Maybe retry, log, or alert
```

### Async Support

If your keypad service is async, wrap the sync client:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2)

async def set_spotlight_mode(mode: str) -> bool:
    """Async wrapper for spotlight control."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        spotlight.set_mode,
        mode
    )

# Usage
async def handle_keypad_async(key: int) -> None:
    if key == 2:
        await set_spotlight_mode("red")
```

## Error Handling

The package raises `QLCPlusError` for connection and communication failures:

```python
from qlcplus import QLCPlusClient, QLCPlusError

try:
    with QLCPlusClient() as client:
        client.start_function(2)
except QLCPlusError as e:
    # Connection failed or command failed
    print(f"QLC+ error: {e}")
    # Retry logic, fallback, or alert
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Failed to connect` | QLC+ not running or wrong host | Check QLC+ is running with `-w` flag |
| `Connection refused` | Port blocked or wrong port | Check firewall, verify port 9999 |
| `Connection timed out` | Network issue | Check network connectivity |

## Testing the Connection

Quick test from the command line:

```bash
# Test connection
python3 -c "
from qlcplus import QLCPlusClient
with QLCPlusClient(host='192.168.0.221') as c:
    print('Functions:', c.get_functions_list())
"
```

Or use the CLI tool (if installed):
```bash
QLCPLUS_HOST=192.168.0.221 qlc --list
```

## Architecture Notes

### Why WebSocket over OSC?

The package supports both, but WebSocket is preferred:

| Feature | WebSocket | OSC |
|---------|-----------|-----|
| Idempotent | Yes (start/stop are absolute) | No (buttons toggle) |
| Mutual exclusion | Manual in client | Solo Frame in QLC+ (unreliable via OSC) |
| Status queries | Yes | No |
| Port | 9999 | 7701 |

### Thread Safety

The `QLCPlusClient` is **not thread-safe**. Create a new client per thread, or use locking:

```python
import threading

lock = threading.Lock()

def thread_safe_set_mode(mode: str) -> None:
    with lock:
        spotlight.set_mode(mode)
```

### Connection Lifecycle

The client connects on first use and disconnects when exiting the context manager:

```python
# Good: Connection opened and closed
with QLCPlusClient() as client:
    client.start_function(2)
# Connection closed here

# Also good: Manual lifecycle
client = QLCPlusClient()
client.connect()
try:
    client.start_function(2)
finally:
    client.disconnect()
```

## Adding New Modes

If you need new lighting modes:

1. Create the scene in QLC+ GUI (on 192.168.0.221)
2. Save the project
3. Note the new function ID (use `--list` to see all)
4. Add to your `MODES` dict

```python
# After adding mode_blue in QLC+
MODES = {
    "off": 0,
    "white": 1,
    "red": 2,
    "yellow": 3,
    "blue": 4,  # New mode
}
```

## Monitoring

To check if QLC+ is responsive:

```python
def health_check() -> bool:
    """Return True if QLC+ is reachable."""
    try:
        with QLCPlusClient(host="192.168.0.221", timeout=2) as client:
            client.get_functions_list()
        return True
    except QLCPlusError:
        return False
```

## Questions?

- **Package source**: https://github.com/joshlebed/qlc-config
- **QLC+ server**: 192.168.0.221
- **WebSocket port**: 9999
