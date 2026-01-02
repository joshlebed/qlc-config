"""WebSocket debug server for real-time visualization."""

from __future__ import annotations

import http.server
import json
import queue
import socketserver
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from websockets.sync.server import ServerConnection


class DebugWebSocket:
    """
    Non-blocking WebSocket server for broadcasting debug data.

    Uses a dedicated broadcaster thread to send data to all clients,
    avoiding race conditions with per-client handlers.
    """

    def __init__(self, ws_port: int = 9998, http_port: int = 8080):
        self.ws_port = ws_port
        self.http_port = http_port
        self._clients: set[ServerConnection] = set()
        self._clients_lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue(maxsize=100)
        self._ws_thread: threading.Thread | None = None
        self._http_thread: threading.Thread | None = None
        self._broadcast_thread: threading.Thread | None = None
        self._ws_server: Any = None
        self._http_server: socketserver.TCPServer | None = None
        self._running = False
        self._msg_count = 0
        self._last_log_time = 0.0

    def start(self) -> None:
        """Start WebSocket and HTTP servers in background threads."""
        self._running = True

        # Start WebSocket server
        self._ws_thread = threading.Thread(target=self._run_ws_server, daemon=True)
        self._ws_thread.start()

        # Start dedicated broadcaster thread
        self._broadcast_thread = threading.Thread(target=self._run_broadcaster, daemon=True)
        self._broadcast_thread.start()

        # Start HTTP server for static files
        self._http_thread = threading.Thread(target=self._run_http_server, daemon=True)
        self._http_thread.start()

        print(f"[debug] WebSocket server started on ws://0.0.0.0:{self.ws_port}")
        print(f"[debug] Debug console at http://0.0.0.0:{self.http_port}/debug.html")

    def _run_broadcaster(self) -> None:
        """Dedicated thread for broadcasting queued messages to all clients."""
        print("[debug] Broadcaster thread started")
        while self._running:
            try:
                # Get message from queue (blocking with timeout)
                msg = self._queue.get(timeout=0.1)
                self._msg_count += 1

                # Log periodically
                now = time.time()
                if now - self._last_log_time > 10.0:
                    with self._clients_lock:
                        client_count = len(self._clients)
                    print(
                        f"[debug] Broadcaster: {self._msg_count} msgs sent, {client_count} clients, queue size: {self._queue.qsize()}"
                    )
                    self._last_log_time = now

                # Send to all clients
                with self._clients_lock:
                    if not self._clients:
                        continue
                    dead_clients: set[ServerConnection] = set()
                    for client in self._clients:
                        try:
                            client.send(msg)
                        except Exception as e:
                            print(f"[debug] Send failed to {client.remote_address}: {e}")
                            dead_clients.add(client)
                    if dead_clients:
                        self._clients -= dead_clients
                        print(f"[debug] Removed {len(dead_clients)} dead client(s)")

            except queue.Empty:
                pass
            except Exception as e:
                print(f"[debug] Broadcaster error: {e}")

        print("[debug] Broadcaster thread stopped")

    def _run_ws_server(self) -> None:
        """Run the WebSocket server (blocking, runs in thread)."""
        try:
            from websockets.sync.server import serve
        except ImportError:
            print("[debug] WebSocket server requires 'websockets' package")
            return

        def handler(websocket: ServerConnection) -> None:
            """Handle a single WebSocket connection."""
            client_addr = websocket.remote_address
            with self._clients_lock:
                self._clients.add(websocket)
                print(f"[debug] Client connected: {client_addr} (total: {len(self._clients)})")

            try:
                # Just keep connection alive - broadcaster thread handles sending
                while self._running:
                    try:
                        # Check for incoming messages (pings handled automatically)
                        # Use recv with timeout to detect disconnects
                        websocket.recv(timeout=1.0)
                    except TimeoutError:
                        # Normal timeout, connection still alive
                        pass
                    except Exception as e:
                        print(f"[debug] Client {client_addr} recv error: {e}")
                        break
            except Exception as e:
                print(f"[debug] Handler error for {client_addr}: {e}")
            finally:
                with self._clients_lock:
                    self._clients.discard(websocket)
                    print(
                        f"[debug] Client disconnected: {client_addr} (total: {len(self._clients)})"
                    )

        try:
            # Bind to all interfaces for network access
            with serve(handler, "0.0.0.0", self.ws_port) as server:
                self._ws_server = server
                server.serve_forever()
        except Exception as e:
            print(f"[debug] WebSocket server error: {e}")

    def _run_http_server(self) -> None:
        """Run HTTP server for static files (blocking, runs in thread)."""
        static_dir = Path(__file__).parent / "static"
        # Look for test_data in project root (parent of plp_beat_service)
        project_root = Path(__file__).parent.parent
        recordings_dir = project_root / "test_data"

        class RecordingsHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any):
                super().__init__(*args, directory=str(static_dir), **kwargs)

            def log_message(self, format: str, *args: Any) -> None:
                # Suppress request logging
                pass

            def do_GET(self) -> None:
                # API: List available recordings
                if self.path == "/api/recordings":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    recordings = []
                    if recordings_dir.exists():
                        for f in sorted(recordings_dir.glob("*.jsonl")):
                            recordings.append(f.name)
                    self.wfile.write(json.dumps(recordings).encode())
                    return

                # Serve recording files from test_data/
                if self.path.startswith("/recordings/"):
                    filename = self.path[12:]  # Remove "/recordings/"
                    # Security: only allow .jsonl files, no path traversal
                    if ".." in filename or "/" in filename:
                        self.send_error(403, "Forbidden")
                        return
                    if not filename.endswith(".jsonl"):
                        self.send_error(403, "Only .jsonl files allowed")
                        return

                    filepath = recordings_dir / filename
                    if not filepath.exists():
                        self.send_error(404, "Recording not found")
                        return

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                    return

                # Default: serve static files
                super().do_GET()

        try:
            # Bind to all interfaces for network access
            # Use SO_REUSEADDR to allow quick restart
            socketserver.TCPServer.allow_reuse_address = True
            self._http_server = socketserver.TCPServer(
                ("0.0.0.0", self.http_port), RecordingsHandler
            )
            self._http_server.serve_forever()
        except Exception as e:
            print(f"[debug] HTTP server error: {e}")

    def broadcast(self, data: dict[str, Any]) -> None:
        """
        Queue data for broadcast to all connected clients.

        Non-blocking: drops oldest message if queue is full.
        """
        if not self._running:
            return

        # Skip if no clients (but still allow queueing for newly connecting clients)
        with self._clients_lock:
            if not self._clients:
                return

        try:
            msg = json.dumps(data)
            self._queue.put_nowait(msg)
        except queue.Full:
            # Drop oldest message to make room
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(msg)
            except queue.Empty:
                pass

    def stop(self) -> None:
        """Stop the servers."""
        self._running = False

        if self._http_server:
            self._http_server.shutdown()

        if self._ws_server:
            self._ws_server.shutdown()

        print("[debug] Debug servers stopped")

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        with self._clients_lock:
            return len(self._clients)
