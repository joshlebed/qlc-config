"""Real-time audio capture using sounddevice."""

from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd

# Audio constants (from handoff section 7)
SAMPLERATE = 44100
BLOCK_SIZE = 512  # ~11.6ms per block (reduced for lower latency)
HOP_SIZE = 512  # ~11.6ms hop
CHANNELS = 2  # Stereo input (mixed to mono)


AudioCallback = Callable[[np.ndarray], None]


class AudioCapture:
    """Real-time audio capture with callback processing."""

    def __init__(
        self,
        callback: AudioCallback,
        device: int | None = None,
        samplerate: int = SAMPLERATE,
        blocksize: int = BLOCK_SIZE,
    ):
        self.callback = callback
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.stream: sd.InputStream | None = None

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags | None,
    ) -> None:
        """Internal sounddevice callback."""
        if status:
            print(f"Audio status: {status}")

        # Convert to mono float32
        if indata.ndim > 1 and indata.shape[1] > 1:
            samples = np.mean(indata, axis=1).astype(np.float32)
        else:
            samples = indata[:, 0].astype(np.float32)

        # Call user callback with mono samples
        self.callback(samples)

    def start(self) -> None:
        """Start audio capture."""
        self.stream = sd.InputStream(
            device=self.device,
            channels=CHANNELS,
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            callback=self._audio_callback,
        )
        self.stream.start()

    def stop(self) -> None:
        """Stop audio capture."""
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None


def list_devices() -> None:
    """List available audio input devices."""
    print("Available audio input devices:\n")
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            default = " (default)" if i == sd.default.device[0] else ""
            print(f"  {i}: {dev['name']}{default}")
            print(
                f"      Channels: {dev['max_input_channels']}, "
                f"Sample Rate: {dev['default_samplerate']}"
            )
    print()
