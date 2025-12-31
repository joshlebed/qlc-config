"""OSC output for beat events."""

from pythonosc import udp_client


class OSCOutput:
    """
    Sends beat events via OSC.

    Messages:
    - /beat: 1 (bang on beat detection)
    - /bpm: float (current BPM, sent when changed)
    - /confidence: float (0-1, sent periodically)
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7701,
        bpm_change_threshold: float = 0.5,
    ):
        self.client = udp_client.SimpleUDPClient(host, port)
        self.bpm_change_threshold = bpm_change_threshold
        self.last_bpm: float = 0.0
        self.last_confidence: float = 0.0

    def send_beat(self) -> None:
        """Send /beat message (bang)."""
        self.client.send_message("/beat", 1)

    def send_bpm(self, bpm: float, force: bool = False) -> None:
        """
        Send /bpm message if BPM changed significantly.

        Args:
            bpm: Current BPM estimate
            force: Send even if unchanged
        """
        if force or abs(bpm - self.last_bpm) >= self.bpm_change_threshold:
            self.client.send_message("/bpm", float(bpm))
            self.last_bpm = bpm

    def send_confidence(self, confidence: float) -> None:
        """Send /confidence message (0-1)."""
        self.client.send_message("/confidence", float(confidence))
        self.last_confidence = confidence

    def send_state(self, state: str) -> None:
        """Send /state message (SEARCHING, LOCKED, HOLDOVER)."""
        self.client.send_message("/state", state)
