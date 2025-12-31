#!/usr/bin/env python3
"""
Audio Reactive Lighting Control

Captures audio from a microphone and controls QLC+ lighting based on volume levels.
Uses direct DMX channel control for real-time responsiveness.

Usage:
    python audio_reactive.py              # Run with defaults
    python audio_reactive.py --device 1   # Specify ALSA card number
    python audio_reactive.py --gain 2.0   # Boost sensitivity
    python audio_reactive.py --mode pulse # Pulse mode (on/off based on beats)

Modes:
    intensity - Dim/brighten based on volume (default)
    pulse     - Flash on beat detection
    color     - Cycle colors based on volume
"""

import argparse
import math
import signal
import struct
import subprocess
import sys
import time
from typing import NoReturn

from qlcplus import QLCPlusClient, QLCPlusError

# DMX channel mappings for ADJ Pinspot LED Quad DMX (6-channel mode)
CHANNEL_RED = 1
CHANNEL_GREEN = 2
CHANNEL_BLUE = 3
CHANNEL_WHITE = 4
CHANNEL_DIMMER = 5
CHANNEL_STROBE = 6

# Audio settings
SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_FORMAT = "S16_LE"
CHUNK_SIZE = 1024  # samples per chunk (~21ms at 48kHz)

# Beat detection
BEAT_THRESHOLD = 1.5  # multiplier above average for beat detection
BEAT_COOLDOWN = 0.1  # minimum seconds between beats


class AudioReactive:
    """Audio reactive lighting controller."""

    def __init__(
        self,
        device: int = 1,
        gain: float = 1.0,
        mode: str = "intensity",
        base_color: tuple[int, int, int] = (255, 100, 50),  # warm orange
    ):
        self.device = device
        self.gain = gain
        self.mode = mode
        self.base_color = base_color
        self.running = False
        self.client: QLCPlusClient | None = None

        # Audio analysis state
        self.avg_level = 0.0
        self.last_beat_time = 0.0
        self.color_phase = 0.0

        # For smoothing
        self.smoothed_level = 0.0
        self.smooth_factor = 0.3

    def start(self) -> None:
        """Start audio reactive mode."""
        self.running = True

        # Connect to QLC+
        try:
            self.client = QLCPlusClient()
            self.client.connect()
            print(f"Connected to QLC+ at {self.client.url}")
        except QLCPlusError as e:
            print(f"Failed to connect to QLC+: {e}", file=sys.stderr)
            sys.exit(1)

        # Start audio capture (plughw allows ALSA to convert stereo->mono if needed)
        arecord_cmd = [
            "arecord",
            "-D",
            f"plughw:{self.device},0",
            "-f",
            SAMPLE_FORMAT,
            "-r",
            str(SAMPLE_RATE),
            "-c",
            str(CHANNELS),
            "-t",
            "raw",
            "-q",  # quiet
        ]

        print(f"Starting audio capture from plughw:{self.device},0")
        print(f"Mode: {self.mode}, Gain: {self.gain}")
        print("Press Ctrl+C to stop")

        try:
            proc = subprocess.Popen(
                arecord_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            bytes_per_sample = 2  # 16-bit
            chunk_bytes = CHUNK_SIZE * bytes_per_sample

            while self.running:
                data = proc.stdout.read(chunk_bytes)
                if not data:
                    break

                # Parse audio samples
                samples = struct.unpack(f"<{len(data) // 2}h", data)
                self.process_audio(samples)

        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            proc.terminate()
            self.cleanup()

    def process_audio(self, samples: tuple[int, ...]) -> None:
        """Process audio samples and update lighting."""
        if not samples:
            return

        # Calculate RMS level
        rms = math.sqrt(sum(s**2 for s in samples) / len(samples))

        # Normalize to 0-1 range (16-bit max is 32768)
        level = min(1.0, (rms / 32768) * self.gain * 10)

        # Update rolling average for beat detection
        self.avg_level = self.avg_level * 0.95 + level * 0.05

        # Smooth the level for less jittery output
        self.smoothed_level = (
            self.smoothed_level * (1 - self.smooth_factor) + level * self.smooth_factor
        )

        # Detect beats
        is_beat = False
        now = time.time()
        if (
            level > self.avg_level * BEAT_THRESHOLD
            and level > 0.1
            and now - self.last_beat_time > BEAT_COOLDOWN
        ):
            is_beat = True
            self.last_beat_time = now

        # Update lighting based on mode
        if self.mode == "intensity":
            self.update_intensity(self.smoothed_level)
        elif self.mode == "pulse":
            self.update_pulse(is_beat, self.smoothed_level)
        elif self.mode == "color":
            self.update_color(self.smoothed_level, is_beat)

    def update_intensity(self, level: float) -> None:
        """Mode: Adjust brightness based on volume."""
        dimmer = int(level * 255)
        r, g, b = self.base_color

        self.set_dmx(r, g, b, 0, dimmer)

    def update_pulse(self, is_beat: bool, level: float) -> None:
        """Mode: Flash on beat detection."""
        if is_beat:
            # Full brightness on beat
            self.set_dmx(255, 255, 255, 255, 255)
        else:
            # Fade based on current level
            dimmer = int(level * 100)  # dimmer for non-beat
            r, g, b = self.base_color
            self.set_dmx(r, g, b, 0, dimmer)

    def update_color(self, level: float, is_beat: bool) -> None:
        """Mode: Cycle through colors, faster on louder audio."""
        # Advance color phase based on level
        self.color_phase += level * 0.1
        if is_beat:
            self.color_phase += 0.2  # jump on beat

        # Convert phase to RGB using HSV-like cycling
        phase = self.color_phase % 1.0
        if phase < 0.333:
            # Red to Green
            t = phase / 0.333
            r, g, b = int(255 * (1 - t)), int(255 * t), 0
        elif phase < 0.666:
            # Green to Blue
            t = (phase - 0.333) / 0.333
            r, g, b = 0, int(255 * (1 - t)), int(255 * t)
        else:
            # Blue to Red
            t = (phase - 0.666) / 0.333
            r, g, b = int(255 * t), 0, int(255 * (1 - t))

        dimmer = int(50 + level * 205)  # base 50, max 255
        self.set_dmx(r, g, b, 0, dimmer)

    def set_dmx(self, r: int, g: int, b: int, w: int, dimmer: int) -> None:
        """Set DMX channels."""
        if not self.client:
            return

        try:
            self.client.set_channel(1, CHANNEL_RED, r)
            self.client.set_channel(1, CHANNEL_GREEN, g)
            self.client.set_channel(1, CHANNEL_BLUE, b)
            self.client.set_channel(1, CHANNEL_WHITE, w)
            self.client.set_channel(1, CHANNEL_DIMMER, dimmer)
        except QLCPlusError:
            pass  # Ignore transient errors

    def cleanup(self) -> None:
        """Clean up resources."""
        self.running = False
        if self.client:
            # Turn off light
            try:
                self.set_dmx(0, 0, 0, 0, 0)
            except Exception:
                pass
            self.client.disconnect()
            self.client = None
        print("Cleaned up")

    def stop(self) -> None:
        """Signal stop."""
        self.running = False


def main() -> NoReturn:
    parser = argparse.ArgumentParser(
        description="Audio reactive lighting control for QLC+",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[0],
    )
    parser.add_argument(
        "--device",
        "-d",
        type=int,
        default=1,
        help="ALSA card number for audio input (default: 1)",
    )
    parser.add_argument(
        "--gain",
        "-g",
        type=float,
        default=1.0,
        help="Audio gain multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["intensity", "pulse", "color"],
        default="intensity",
        help="Lighting mode (default: intensity)",
    )
    parser.add_argument(
        "--color",
        "-c",
        type=str,
        default="255,100,50",
        help="Base color as R,G,B (default: 255,100,50 warm orange)",
    )

    args = parser.parse_args()

    # Parse color
    try:
        color = tuple(int(x) for x in args.color.split(","))
        if len(color) != 3:
            raise ValueError
        base_color = (color[0], color[1], color[2])
    except ValueError:
        print(f"Invalid color format: {args.color}", file=sys.stderr)
        print("Use R,G,B format, e.g., 255,0,0 for red", file=sys.stderr)
        sys.exit(1)

    controller = AudioReactive(
        device=args.device,
        gain=args.gain,
        mode=args.mode,
        base_color=base_color,
    )

    # Handle signals
    def signal_handler(sig: int, frame: object) -> None:
        controller.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    controller.start()
    sys.exit(0)


if __name__ == "__main__":
    main()
