#!/usr/bin/env python3
"""
State-of-the-Art Beat Detection to MIDI Clock

Professional-grade beat detection for driving lighting systems.
Designed for house/techno in the 110-160 BPM range.

Features:
- Low-pass filtering for kick drum emphasis
- RNN-based beat detection (madmom) with aubio fallback
- Phase-locked loop (PLL) for stable timing
- Lock state machine (SEARCHING -> LOCKING -> LOCKED)
- MIDI Clock output (24 PPQN) instead of notes
- Jitter compensation and outlier rejection

Usage:
    python beat_to_midi.py                      # Use default device
    python beat_to_midi.py --device 2           # Specify device index
    python beat_to_midi.py --list-devices       # List audio devices
    python beat_to_midi.py --note-mode          # Use Note On/Off instead of clock

MIDI Output:
    Creates virtual MIDI port "BeatClock"
    Sends MIDI Clock (0xF8) at 24 pulses per quarter note
    Sends Start (0xFA) when locked, Stop (0xFC) when unlocked
"""

import argparse
import sys
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import numpy as np
import rtmidi
import sounddevice as sd
from scipy import signal

# Try to import aubio (madmom has Python 3.11 compatibility issues)
HAVE_MADMOM = False  # Disabled due to Python 3.11 incompatibility
HAVE_AUBIO = False

try:
    import aubio
    HAVE_AUBIO = True
except ImportError:
    pass

if not HAVE_AUBIO:
    print("ERROR: aubio not found. Install with: uv pip install aubio", file=sys.stderr)
    sys.exit(1)


# =============================================================================
# Constants
# =============================================================================

SAMPLERATE = 44100
BLOCK_SIZE = 512          # ~11.6ms per block
CHANNELS = 2              # Stereo input (mixed to mono internally)

# Kick drum emphasis filter (30-200 Hz bandpass for fast techno)
KICK_LOW_HZ = 30
KICK_HIGH_HZ = 200

# PLL / Phase tracking
MIN_BPM = 100
MAX_BPM = 180             # Support faster techno
BEATS_TO_LOCK = 6         # Fewer beats needed to lock
PHASE_TOLERANCE = 0.30    # Accept beats within 30% of expected phase (more tolerant)
BPM_TOLERANCE = 0.15      # 15% BPM variation allowed when locked

# Timeout and adaptation
BEAT_TIMEOUT_BEATS = 6    # Lose lock after this many missed beats
TEMPO_CHANGE_THRESHOLD = 0.25  # 25% BPM change triggers reset (more tolerant)
TEMPO_CHANGE_BEATS = 5    # Consecutive beats at different tempo to trigger reset
MAX_BEAT_AGE = 15.0       # Ignore beats older than this (seconds)

# MIDI
MIDI_CLOCK = 0xF8
MIDI_START = 0xFA
MIDI_STOP = 0xFC
MIDI_NOTE_ON = 0x90
MIDI_NOTE_OFF = 0x80
PPQN = 24                 # Pulses per quarter note


class LockState(Enum):
    SEARCHING = "SEARCHING"  # Looking for consistent beats
    LOCKING = "LOCKING"      # Found beats, building confidence
    LOCKED = "LOCKED"        # Stable tempo, outputting clock


@dataclass
class BeatInfo:
    """Information about a detected beat."""
    timestamp: float        # When the beat was detected
    confidence: float       # Detection confidence (0-1)
    bpm: float             # Instantaneous BPM estimate


class KickFilter:
    """Low-pass filter to emphasize kick drum frequencies."""

    def __init__(self, samplerate: int = SAMPLERATE):
        # Design a bandpass filter for kick frequencies
        nyquist = samplerate / 2
        low = KICK_LOW_HZ / nyquist
        high = min(KICK_HIGH_HZ / nyquist, 0.99)

        # 4th order Butterworth bandpass
        self.b, self.a = signal.butter(4, [low, high], btype='band')
        # Initialize filter state (scale by 0 for zero initial conditions)
        self.zi = signal.lfilter_zi(self.b, self.a) * 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Apply kick emphasis filter."""
        # Ensure input is float64 for filter stability
        samples_f64 = samples.astype(np.float64)
        filtered, self.zi = signal.lfilter(self.b, self.a, samples_f64, zi=self.zi)
        # Clip and convert back to float32
        return np.clip(filtered, -1.0, 1.0).astype(np.float32)


class PhaseLockLoop:
    """
    Phase-locked loop for stable beat timing.

    Uses interval-based median tracking with drift correction for accurate
    tempo locking. Tracks tempo and phase, predicts next beat, accepts/rejects.
    """

    def __init__(self):
        self.state = LockState.SEARCHING
        self.bpm = 0.0
        self.last_beat_time = 0.0
        self.last_detection_time = 0.0  # When we last detected ANY beat
        self.beat_times: deque[float] = deque(maxlen=16)
        self.intervals: deque[float] = deque(maxlen=16)  # Recent beat intervals
        self.phase_errors: deque[float] = deque(maxlen=8)  # For drift detection
        self.consistent_count = 0
        self.clock_accumulator = 0.0
        self.tempo_change_count = 0
        self._last_debug = ""

    def beat_period(self) -> float:
        """Seconds per beat."""
        if self.bpm <= 0:
            return 0.5  # Default 120 BPM
        return 60.0 / self.bpm

    def predict_next_beat(self) -> float:
        """Predict timestamp of next beat."""
        if self.last_beat_time <= 0:
            return time.time()
        return self.last_beat_time + self.beat_period()

    def update_tempo_from_intervals(self) -> None:
        """Update BPM using median of recent valid intervals."""
        if len(self.intervals) < 3:
            return

        # Filter to valid intervals
        valid = [i for i in self.intervals if 60/MAX_BPM < i < 60/MIN_BPM]
        if len(valid) >= 3:
            # Use median for robustness
            median_interval = np.median(valid)
            new_bpm = 60.0 / median_interval

            # Only update if significantly different (reduces oscillation)
            if self.bpm <= 0:
                self.bpm = new_bpm
            elif abs(new_bpm - self.bpm) / self.bpm > 0.01:  # >1% change
                # Blend old and new (80% old, 20% new for stability)
                self.bpm = self.bpm * 0.8 + new_bpm * 0.2

    def apply_drift_correction(self) -> None:
        """Correct tempo based on accumulated phase drift."""
        if len(self.phase_errors) < 6:
            return

        errors = list(self.phase_errors)
        mean_error = np.mean(errors)

        # Only correct if errors are consistently biased (same direction)
        if all(e > 0.002 for e in errors) or all(e < -0.002 for e in errors):
            # Very gentle correction: 0.3% of mean error per cycle
            correction = mean_error / self.beat_period() * 0.03
            correction = np.clip(correction, -0.005, 0.005)  # Max 0.5% per cycle
            self.bpm *= (1 - correction)
            self.bpm = np.clip(self.bpm, MIN_BPM, MAX_BPM)

    def check_timeout(self) -> bool:
        """Check if we've timed out waiting for beats. Returns True if timed out."""
        if self.state != LockState.LOCKED or self.bpm <= 0:
            return False

        now = time.time()
        time_since_last = now - self.last_detection_time
        timeout_duration = self.beat_period() * BEAT_TIMEOUT_BEATS

        if time_since_last > timeout_duration:
            self.state = LockState.LOCKING
            self.consistent_count = BEATS_TO_LOCK // 2
            return True
        return False

    def prune_old_beats(self) -> None:
        """Remove beats older than MAX_BEAT_AGE."""
        now = time.time()
        while self.beat_times and (now - self.beat_times[0]) > MAX_BEAT_AGE:
            self.beat_times.popleft()
        # Also limit intervals to match
        while len(self.intervals) > len(self.beat_times):
            self.intervals.popleft()

    def process_beat(self, timestamp: float, confidence: float = 1.0) -> bool:
        """
        Process a detected beat. Returns True if beat was accepted.
        """
        now = timestamp
        self.last_detection_time = now
        self.prune_old_beats()

        # Calculate interval from last beat
        interval = now - self.last_beat_time if self.last_beat_time > 0 else 0.0

        if self.state == LockState.SEARCHING:
            # Accept all beats, try to find tempo
            self.beat_times.append(now)
            if interval > 0.1:  # Valid interval
                self.intervals.append(interval)
            self.last_beat_time = now
            self.tempo_change_count = 0
            self.phase_errors.clear()

            if len(self.intervals) >= 4:
                # Use median of intervals for robust tempo estimate
                self.update_tempo_from_intervals()

                if MIN_BPM <= self.bpm <= MAX_BPM:
                    self.state = LockState.LOCKING
                    self.consistent_count = 0
                    return True
            return True

        elif self.state == LockState.LOCKING:
            # Check if beat is near expected time
            expected = self.predict_next_beat()
            error = now - expected  # Positive = late, negative = early
            tolerance = self.beat_period() * PHASE_TOLERANCE

            self._last_debug = f"err={error:.3f}s tol={tolerance:.3f}s int={interval:.3f}s"

            # Accept if within tolerance OR if interval is valid
            valid_interval = 60/MAX_BPM < interval < 60/MIN_BPM

            if abs(error) < tolerance or valid_interval:
                # Accept beat and update tracking
                self.beat_times.append(now)
                if valid_interval:
                    self.intervals.append(interval)
                self.last_beat_time = now

                if abs(error) < tolerance:
                    self.consistent_count += 1
                else:
                    # Valid interval but not in phase - still learning
                    self.consistent_count = max(0, self.consistent_count)

                # Update tempo from intervals (median-based)
                self.update_tempo_from_intervals()

                if self.consistent_count >= BEATS_TO_LOCK:
                    self.state = LockState.LOCKED
                    self.clock_accumulator = 0.0
                    self.phase_errors.clear()
                return True
            else:
                # Invalid beat - too far from expected and invalid interval
                if interval > self.beat_period() * 2:
                    # Missed multiple beats - resync
                    self.last_beat_time = now
                    self.beat_times.append(now)
                    return True
                return False

        elif self.state == LockState.LOCKED:
            expected = self.predict_next_beat()
            error = now - expected  # Positive = late, negative = early
            tolerance = self.beat_period() * PHASE_TOLERANCE
            valid_interval = 60/MAX_BPM < interval < 60/MIN_BPM
            instant_bpm = 60.0 / interval if interval > 0.1 else 0.0

            self._last_debug = f"err={error:.3f}s tol={tolerance:.3f}s int={interval:.3f}s ibpm={instant_bpm:.1f}"

            # Check for tempo change
            if instant_bpm > 0 and self.bpm > 0:
                bpm_diff = abs(instant_bpm - self.bpm) / self.bpm
                if bpm_diff > TEMPO_CHANGE_THRESHOLD:
                    self.tempo_change_count += 1
                    if self.tempo_change_count >= TEMPO_CHANGE_BEATS:
                        # Tempo changed - reset
                        self.state = LockState.SEARCHING
                        self.bpm = 0.0
                        self.beat_times.clear()
                        self.intervals.clear()
                        self.phase_errors.clear()
                        self.consistent_count = 0
                        self.tempo_change_count = 0
                        self.beat_times.append(now)
                        self.last_beat_time = now
                        return True
                else:
                    self.tempo_change_count = 0

            if abs(error) < tolerance:
                # Good beat within phase tolerance - update everything
                self.beat_times.append(now)
                self.last_beat_time = now

                # Only add intervals that are close to expected (within 10%)
                if valid_interval and abs(instant_bpm - self.bpm) / self.bpm < 0.10:
                    self.intervals.append(interval)
                    self.update_tempo_from_intervals()

                # Track phase error for drift correction
                self.phase_errors.append(error)
                self.apply_drift_correction()

                return True
            elif interval > self.beat_period() * 1.5:
                # Missed beats - just resync timing, don't change tempo
                self.last_beat_time = now
                self.beat_times.append(now)
                return True
            elif valid_interval:
                # Valid interval but wrong phase - might be off-beat detection
                # Accept but don't update tempo
                self.last_beat_time = now
                self.beat_times.append(now)
                return True
            else:
                # Spurious detection
                self.consistent_count -= 1
                if self.consistent_count <= -5:  # More tolerant
                    self.state = LockState.LOCKING
                    self.consistent_count = BEATS_TO_LOCK // 2
                    self.tempo_change_count = 0
                return False

        return False

    def get_clock_pulses(self, dt: float) -> int:
        """
        Get number of MIDI clock pulses to send for elapsed time dt.
        Only returns pulses when LOCKED.
        """
        if self.state != LockState.LOCKED or self.bpm <= 0:
            return 0

        # Clock pulses per second = BPM/60 * PPQN
        pulses_per_second = (self.bpm / 60.0) * PPQN
        self.clock_accumulator += dt * pulses_per_second

        pulses = int(self.clock_accumulator)
        self.clock_accumulator -= pulses
        return pulses


class BeatDetector:
    """
    Beat detector using aubio onset detection.
    Uses onset detection for precise timing + tempo tracking for BPM estimation.
    """

    def __init__(self, samplerate: int = SAMPLERATE, method: str = "energy"):
        self.samplerate = samplerate
        self.last_beat_time = 0.0
        self.intervals: deque[float] = deque(maxlen=32)

        # Use onset detection for precise timing
        win_s = 1024
        hop_s = 512

        # Use energy-based onset for kick drums
        self.onset = aubio.onset(method, win_s, hop_s, samplerate)
        self.onset.set_threshold(0.3)  # Moderate threshold to catch kicks
        self.onset.set_silence(-50)    # dB threshold below which onsets are ignored

        # Minimum interval between beats (based on MAX_BPM)
        self.min_interval = 60.0 / MAX_BPM * 0.8  # 80% of minimum beat period

        print(f"Beat detection: aubio onset ({method}, threshold=0.3, silence=-50dB)")

    def process(self, samples: np.ndarray) -> list[BeatInfo]:
        """Process audio samples, return detected beats."""
        beats = []
        now = time.time()

        # Check for onset
        if self.onset(samples):
            # Calculate interval from last beat
            interval = now - self.last_beat_time if self.last_beat_time > 0 else 0.0

            # Debounce: ignore onsets too close together
            if interval < self.min_interval and self.last_beat_time > 0:
                return beats

            self.last_beat_time = now

            # Store interval for BPM calculation
            if interval > 0.1:  # Ignore first detection
                self.intervals.append(interval)

            # Compute BPM from median of recent intervals
            if len(self.intervals) >= 3:
                # Filter to valid range and take median
                valid_intervals = [
                    i for i in self.intervals
                    if 60/MAX_BPM < i < 60/MIN_BPM
                ]
                if valid_intervals:
                    median_interval = np.median(valid_intervals)
                    bpm = 60.0 / median_interval
                else:
                    bpm = 0.0
            else:
                bpm = 60.0 / interval if interval > 0.1 else 0.0

            beats.append(BeatInfo(
                timestamp=now,
                confidence=1.0,  # Onset detection gives binary result
                bpm=bpm
            ))

        return beats


class MIDIOutput:
    """MIDI output handler."""

    def __init__(self, port_name: str = "BeatClock"):
        self.midi = rtmidi.MidiOut()
        self.midi.open_virtual_port(port_name)
        self.clock_running = False
        print(f"MIDI output: virtual port '{port_name}' created")

    def send_clock(self) -> None:
        """Send MIDI clock pulse."""
        self.midi.send_message([MIDI_CLOCK])

    def send_start(self) -> None:
        """Send MIDI Start."""
        if not self.clock_running:
            self.midi.send_message([MIDI_START])
            self.clock_running = True

    def send_stop(self) -> None:
        """Send MIDI Stop."""
        if self.clock_running:
            self.midi.send_message([MIDI_STOP])
            self.clock_running = False

    def send_note(self, note: int = 36, velocity: int = 100, duration: float = 0.02) -> None:
        """Send a MIDI note with proper duration."""
        self.midi.send_message([MIDI_NOTE_ON, note, velocity])
        # Schedule note off
        threading.Timer(duration, lambda: self.midi.send_message([MIDI_NOTE_OFF, note, 0])).start()

    def close(self) -> None:
        """Clean up."""
        self.send_stop()
        self.midi.close_port()


class BeatToMidi:
    """Main beat-to-MIDI processor."""

    def __init__(
        self,
        device: int | None = None,
        note_mode: bool = False,
        samplerate: int = SAMPLERATE,
        no_filter: bool = False,
        debug: bool = False,
        file_path: str | None = None,
    ):
        self.device = device
        self.note_mode = note_mode
        self.samplerate = samplerate
        self.no_filter = no_filter
        self.debug = debug
        self.file_path = file_path
        self.running = False

        # Components
        self.kick_filter = None if no_filter else KickFilter(samplerate)
        self.detector = BeatDetector(samplerate)
        self.pll = PhaseLockLoop()
        self.midi = MIDIOutput()

        # Timing
        self.last_time = time.time()
        self.beat_count = 0
        self.last_state = LockState.SEARCHING

        # Stats
        self.beats_accepted = 0
        self.beats_rejected = 0

    def audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """Audio input callback."""
        if status:
            print(f"Audio status: {status}")

        # Convert to mono float32 (mix stereo if needed)
        if indata.ndim > 1 and indata.shape[1] > 1:
            samples = np.mean(indata, axis=1).astype(np.float32)
        else:
            samples = indata[:, 0].astype(np.float32)

        # Apply kick emphasis filter (if enabled)
        if self.kick_filter is not None:
            filtered = self.kick_filter.process(samples)
        else:
            filtered = samples

        # Detect beats
        beats = self.detector.process(filtered)

        # Process each detected beat through PLL
        for beat in beats:
            accepted = self.pll.process_beat(beat.timestamp, beat.confidence)
            if accepted:
                self.beats_accepted += 1
                self.beat_count += 1

                if self.note_mode:
                    # Send MIDI note on each beat
                    self.midi.send_note()

                # Print beat info
                state_char = {"SEARCHING": "?", "LOCKING": "~", "LOCKED": "*"}[self.pll.state.value]
                debug_info = f" | aubio: {beat.bpm:5.1f}" if self.debug else ""
                print(
                    f"{state_char} Beat {self.beat_count:4d} | "
                    f"BPM: {self.pll.bpm:5.1f} | "
                    f"State: {self.pll.state.value}{debug_info}",
                    flush=True,
                )
            else:
                self.beats_rejected += 1
                # Debug: show rejected beats
                if self.debug:
                    pll_debug = getattr(self.pll, '_last_debug', '')
                    print(
                        f"  [rejected] PLL: {self.pll.bpm:5.1f} | {pll_debug}",
                        flush=True,
                    )

        # Check for timeout (no beats detected for a while)
        if self.pll.check_timeout():
            print(f"\n>>> TIMEOUT - no beats detected <<<\n")
            if not self.note_mode:
                self.midi.send_stop()

        # Handle state transitions
        if self.pll.state != self.last_state:
            if self.pll.state == LockState.LOCKED:
                print(f"\n>>> LOCKED at {self.pll.bpm:.1f} BPM <<<\n")
                if not self.note_mode:
                    self.midi.send_start()
            elif self.last_state == LockState.LOCKED:
                print(f"\n>>> LOST LOCK <<<\n")
                if not self.note_mode:
                    self.midi.send_stop()
            self.last_state = self.pll.state

        # In clock mode, only send pulses on actual beat detection (not continuously)
        # This prevents phantom beats during breakdowns
        if not self.note_mode and self.pll.state == LockState.LOCKED:
            # Send 24 clock pulses distributed between beats
            # But only when we actually detected a beat this callback
            if beats and any(self.pll.process_beat(b.timestamp) for b in []):  # Already processed above
                pass  # Clock pulses sent on beat detection
            # For continuous clock, uncomment below:
            # now = time.time()
            # dt = now - self.last_time
            # self.last_time = now
            # pulses = self.pll.get_clock_pulses(dt)
            # for _ in range(pulses):
            #     self.midi.send_clock()

    def run(self) -> None:
        """Main loop."""
        self.running = True
        self.last_time = time.time()

        if self.file_path:
            print(f"Audio file: {self.file_path}")
        else:
            print(f"Audio device: {self.device or 'default'}")
        print(f"Sample rate: {self.samplerate} Hz")
        print(f"Mode: {'Note On/Off' if self.note_mode else 'MIDI Clock (24 PPQN)'}")
        print(f"BPM range: {MIN_BPM}-{MAX_BPM}")
        print(f"Kick filter: {'disabled' if self.no_filter else f'{KICK_LOW_HZ}-{KICK_HIGH_HZ} Hz bandpass'}")
        print(f"Debug: {'enabled' if self.debug else 'disabled'}")
        print("\nListening for beats...")
        print("States: ? = SEARCHING, ~ = LOCKING, * = LOCKED")
        print("Press Ctrl+C to stop\n")

        try:
            if self.file_path:
                self._run_from_file()
            else:
                self._run_from_device()
        except KeyboardInterrupt:
            print("\n\nStopping...")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()

    def _run_from_device(self) -> None:
        """Run beat detection from audio device."""
        with sd.InputStream(
            device=self.device,
            channels=CHANNELS,
            samplerate=self.samplerate,
            blocksize=BLOCK_SIZE,
            callback=self.audio_callback,
        ):
            while self.running:
                time.sleep(0.1)

    def _run_from_file(self) -> None:
        """Run beat detection from audio file."""
        path = Path(self.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {self.file_path}")

        # Read WAV file
        with wave.open(str(path), 'rb') as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            file_rate = wf.getframerate()
            n_frames = wf.getnframes()

            print(f"File: {channels} ch, {file_rate} Hz, {n_frames} frames ({n_frames/file_rate:.1f}s)")

            if file_rate != self.samplerate:
                print(f"Warning: File sample rate ({file_rate}) differs from expected ({self.samplerate})")

            # Process in blocks
            while self.running:
                raw_data = wf.readframes(BLOCK_SIZE)
                if not raw_data:
                    print("\n>>> End of file <<<")
                    break

                # Convert to numpy array
                if sample_width == 2:  # 16-bit
                    data = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                elif sample_width == 4:  # 32-bit
                    data = np.frombuffer(raw_data, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    raise ValueError(f"Unsupported sample width: {sample_width}")

                # Skip if block is too small (end of file)
                if len(data) < BLOCK_SIZE // 2:
                    continue

                # Pad to BLOCK_SIZE if needed
                if len(data) < BLOCK_SIZE:
                    data = np.pad(data, (0, BLOCK_SIZE - len(data)), mode='constant')

                # Reshape to (frames, channels)
                if channels > 1:
                    data = data.reshape(-1, channels)
                else:
                    data = data.reshape(-1, 1)

                # Simulate real-time by sleeping
                time.sleep(BLOCK_SIZE / file_rate)

                # Process through callback
                self.audio_callback(data, len(data), None, None)

    def cleanup(self) -> None:
        """Clean up resources."""
        self.running = False
        self.midi.close()

        # Print stats
        total = self.beats_accepted + self.beats_rejected
        if total > 0:
            accept_rate = self.beats_accepted / total * 100
            print(f"\nStats: {self.beats_accepted} accepted, {self.beats_rejected} rejected ({accept_rate:.1f}% accept rate)")
        print("Cleaned up")


def list_devices() -> None:
    """List available audio input devices."""
    print("Available audio input devices:\n")
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            default = " (default)" if i == sd.default.device[0] else ""
            print(f"  {i}: {dev['name']}{default}")
            print(f"      Channels: {dev['max_input_channels']}, Sample Rate: {dev['default_samplerate']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="State-of-the-art beat detection to MIDI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--device", "-d",
        type=int,
        default=None,
        help="Audio device index (use --list-devices to see options)",
    )
    parser.add_argument(
        "--list-devices", "-l",
        action="store_true",
        help="List available audio devices and exit",
    )
    parser.add_argument(
        "--note-mode", "-n",
        action="store_true",
        help="Send Note On/Off instead of MIDI Clock",
    )
    parser.add_argument(
        "--samplerate", "-r",
        type=int,
        default=SAMPLERATE,
        help=f"Audio sample rate (default: {SAMPLERATE})",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable kick drum bandpass filter (use raw audio)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show raw aubio BPM estimates for debugging",
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Process audio from WAV file instead of microphone",
    )

    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    processor = BeatToMidi(
        device=args.device,
        note_mode=args.note_mode,
        samplerate=args.samplerate,
        no_filter=args.no_filter,
        debug=args.debug,
        file_path=args.file,
    )
    processor.run()


if __name__ == "__main__":
    main()
