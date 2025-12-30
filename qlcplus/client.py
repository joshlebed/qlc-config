"""
QLC+ WebSocket Client

Provides a client for controlling QLC+ via WebSocket API.
"""

import os

from websocket import WebSocket, create_connection


class QLCPlusError(Exception):
    """Exception raised for QLC+ communication errors."""
    pass


class QLCPlusClient:
    """
    Client for controlling QLC+ via WebSocket API.

    Provides idempotent function control - calling start on a running function
    is safe and won't toggle it off.

    Usage:
        client = QLCPlusClient("192.168.0.221")
        client.start_function(2)  # Start function ID 2
        client.stop_function(2)   # Stop function ID 2

        # Or use context manager for auto-disconnect
        with QLCPlusClient("192.168.0.221") as client:
            client.start_function(2)
    """

    DEFAULT_HOST = "192.168.0.221"
    DEFAULT_PORT = 9999
    DEFAULT_TIMEOUT = 5

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        Initialize the QLC+ client.

        Args:
            host: QLC+ server hostname/IP. Defaults to QLCPLUS_HOST env var
                  or 192.168.0.221
            port: WebSocket port. Defaults to QLCPLUS_WS_PORT env var or 9999
            timeout: Connection timeout in seconds
        """
        self.host = host or os.environ.get("QLCPLUS_HOST", self.DEFAULT_HOST)
        self.port = port or int(os.environ.get("QLCPLUS_WS_PORT", self.DEFAULT_PORT))
        self.timeout = timeout
        self._ws: WebSocket | None = None

    @property
    def url(self) -> str:
        """WebSocket URL for QLC+."""
        return f"ws://{self.host}:{self.port}/qlcplusWS"

    def connect(self) -> None:
        """Establish WebSocket connection to QLC+."""
        if self._ws is not None:
            return
        try:
            self._ws = create_connection(self.url, timeout=self.timeout)
        except Exception as e:
            raise QLCPlusError(f"Failed to connect to QLC+ at {self.url}: {e}") from e

    def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def __enter__(self) -> "QLCPlusClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def _send(self, command: str, wait_response: bool = True) -> str:
        """
        Send a command to QLC+ API.

        Args:
            command: API command (without QLC+API| prefix)
            wait_response: Whether to wait for a response

        Returns:
            Response string if wait_response is True, empty string otherwise
        """
        if self._ws is None:
            self.connect()

        try:
            self._ws.send(f"QLC+API|{command}")
            if wait_response:
                return self._ws.recv()
            return ""
        except Exception as e:
            raise QLCPlusError(f"Failed to send command '{command}': {e}") from e

    # -------------------------------------------------------------------------
    # Function Control
    # -------------------------------------------------------------------------

    def start_function(self, function_id: int) -> None:
        """
        Start a function by ID. Idempotent - safe to call multiple times.

        Args:
            function_id: The QLC+ function ID
        """
        self._send(f"setFunctionStatus|{function_id}|1", wait_response=False)

    def stop_function(self, function_id: int) -> None:
        """
        Stop a function by ID. Idempotent - safe to call multiple times.

        Args:
            function_id: The QLC+ function ID
        """
        self._send(f"setFunctionStatus|{function_id}|0", wait_response=False)

    def get_function_status(self, function_id: int) -> str:
        """
        Get the running status of a function.

        Args:
            function_id: The QLC+ function ID

        Returns:
            Status string: "Running", "Stopped", or "Undefined"
        """
        response = self._send(f"getFunctionStatus|{function_id}")
        # Response format: "QLC+API|getFunctionStatus|Running"
        parts = response.split("|")
        return parts[-1] if parts else "Unknown"

    def get_functions_list(self) -> dict[int, str]:
        """
        Get a list of all functions.

        Returns:
            Dict mapping function ID to function name
        """
        response = self._send("getFunctionsList")
        # Response format: "QLC+API|getFunctionsList|0|name1|1|name2|..."
        parts = response.split("|")

        functions = {}
        # Skip the "QLC+API|getFunctionsList" prefix
        data_parts = parts[2:] if len(parts) > 2 else []
        for i in range(0, len(data_parts) - 1, 2):
            try:
                func_id = int(data_parts[i])
                name = data_parts[i + 1]
                functions[func_id] = name
            except (ValueError, IndexError):
                continue
        return functions

    def get_function_type(self, function_id: int) -> str:
        """
        Get the type of a function.

        Args:
            function_id: The QLC+ function ID

        Returns:
            Function type string (e.g., "Scene", "Chaser", "EFX")
        """
        response = self._send(f"getFunctionType|{function_id}")
        parts = response.split("|")
        return parts[-1] if parts else "Unknown"

    # -------------------------------------------------------------------------
    # Channel Control (Simple Desk)
    # -------------------------------------------------------------------------

    def set_channel(self, universe: int, channel: int, value: int) -> None:
        """
        Set a DMX channel value directly.

        Args:
            universe: Universe number (1-based)
            channel: Channel number (1-based)
            value: DMX value (0-255)
        """
        # Simple desk uses absolute addressing: (universe-1)*512 + channel
        address = (universe - 1) * 512 + channel
        self._ws.send(f"CH|{address}|{value}")

    # -------------------------------------------------------------------------
    # Virtual Console Widget Control
    # -------------------------------------------------------------------------

    def get_widgets_list(self) -> dict[int, str]:
        """
        Get a list of Virtual Console widgets.

        Returns:
            Dict mapping widget ID to widget name
        """
        response = self._send("getWidgetsList")
        parts = response.split("|")

        widgets = {}
        data_parts = parts[2:] if len(parts) > 2 else []
        for i in range(0, len(data_parts) - 1, 2):
            try:
                widget_id = int(data_parts[i])
                name = data_parts[i + 1]
                widgets[widget_id] = name
            except (ValueError, IndexError):
                continue
        return widgets

    def set_widget_value(self, widget_id: int, value: int) -> None:
        """
        Set a Virtual Console widget value.

        Args:
            widget_id: The widget ID
            value: Value to set (0-255 for buttons/sliders)
        """
        self._ws.send(f"{widget_id}|{value}")
