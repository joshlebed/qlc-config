"""Main PLP Beat Service implementation."""

import json
import sys
import time
from dataclasses import dataclass
from typing import TextIO

import sounddevice as sd

from plp_beat_service.audio import BLOCK_SIZE, SAMPLERATE
from plp_beat_service.confidence import ConfidenceTracker
from plp_beat_service.onset import OnsetEnvelopeTracker
from plp_beat_service.osc import OSCOutput
from plp_beat_service.peaks import PeakPicker
from plp_beat_service.plp import PLPTracker
from plp_beat_service.state import BeatStateMachine, LockState
from plp_beat_service.tempogram import StreamingTempogram

# Status update interval for log output (seconds)
LOG_STATUS_INTERVAL = 5.0

# Optional MIDI support
try:
    from plp_beat_service.midi import MIDIOutput

    HAVE_MIDI = True
except ImportError:
    HAVE_MIDI = False
    MIDIOutput = None  # type: ignore


@dataclass
class BeatEvent:
    """A detected beat event."""

    timestamp: float
    bpm: float
    confidence: float


class PLPBeatService:
    """
    Real-time PLP-based beat tracking service.

    Produces beat events with tempo and confidence for lighting control.
    """

    def __init__(
        self,
        device: int | None = None,
        samplerate: int = SAMPLERATE,
        bpm_min: int = 115,
        bpm_max: int = 165,
        osc_host: str = "127.0.0.1",
        osc_port: int = 7701,
        enable_osc: bool = True,
        enable_midi: bool = False,
        midi_note_mode: bool = True,
        midi_port_name: str = "PLPBeat",
        debug: bool = False,
        enable_debug_server: bool = False,
        debug_ws_port: int = 9998,
        debug_http_port: int = 8080,
        record_path: str | None = None,
    ):
        self.device = device
        self.samplerate = samplerate
        self.bpm_min = bpm_min
        self.bpm_max = bpm_max
        self.running = False
        self.debug = debug
        self._debug_frame = 0

        # Pipeline components
        self.onset_tracker = OnsetEnvelopeTracker(
            samplerate=samplerate, hop_length=BLOCK_SIZE
        )
        self.tempogram = StreamingTempogram(
            samplerate=samplerate,
            hop_length=BLOCK_SIZE,
            tempo_min=bpm_min,
            tempo_max=bpm_max,
        )
        self.plp = PLPTracker(
            samplerate=samplerate,
            hop_length=BLOCK_SIZE,
            tempo_min=bpm_min,
            tempo_max=bpm_max,
        )
        self.peak_picker = PeakPicker(
            samplerate=samplerate,
            hop_length=BLOCK_SIZE,
            tempo_max=bpm_max,
            debug=debug,
        )
        self.confidence_tracker = ConfidenceTracker()
        self.state_machine = BeatStateMachine()

        # Output - OSC
        self.enable_osc = enable_osc
        if enable_osc:
            self.osc = OSCOutput(host=osc_host, port=osc_port)
        else:
            self.osc = None

        # Output - MIDI
        self.enable_midi = enable_midi
        self.midi_note_mode = midi_note_mode
        if enable_midi:
            if not HAVE_MIDI:
                raise ImportError(
                    "MIDI support requires rtmidi. Install with: uv pip install python-rtmidi"
                )
            self.midi = MIDIOutput(
                port_name=midi_port_name,
                note_mode=midi_note_mode,
            )
        else:
            self.midi = None

        # Debug server
        self.enable_debug_server = enable_debug_server
        if enable_debug_server:
            from plp_beat_service.debug_server import DebugWebSocket

            self.debug_ws = DebugWebSocket(
                ws_port=debug_ws_port, http_port=debug_http_port
            )
        else:
            self.debug_ws = None

        # Recording
        self.record_path = record_path
        self.record_file: TextIO | None = None
        if record_path:
            self.record_file = open(record_path, "w")
            header = {
                "type": "header",
                "version": 1,
                "source": "live",
                "bpm_min": bpm_min,
                "bpm_max": bpm_max,
                "samplerate": samplerate,
                "block_size": BLOCK_SIZE,
            }
            self.record_file.write(json.dumps(header) + "\n")
            print(f"[record] Recording to: {record_path}")

        # State
        self.current_bpm: float = 0.0
        self.current_confidence: float = 0.0
        self.beat_count: int = 0
        self.last_state_change: float = 0.0
        self._last_status_log: float = 0.0
        self._last_overflow_log: float = 0.0
        self._is_tty = sys.stdout.isatty()

    def _audio_callback(
        self,
        indata,
        frames: int,
        time_info,
        status,
    ) -> None:
        """Process audio block from sounddevice."""
        if status:
            # Only log overflow warnings every 30 seconds to reduce spam
            now = time.time()
            if now - self._last_overflow_log > 30.0:
                self._last_overflow_log = now
                print(f"[audio] {status}", flush=True)

        # Get mono audio
        audio = indata[:, 0].astype("float32")

        # Process through pipeline
        self._process_audio(audio)

    def _process_audio(self, audio) -> None:
        """Process audio chunk through the PLP pipeline."""
        now = time.time()
        self._debug_frame += 1

        # Onset envelope
        onset = self.onset_tracker.process(audio)
        onset_val = onset[0]
        self.tempogram.update(onset_val)

        # Tempo estimation
        bpm, strength = self.tempogram.estimate_tempo()

        # Default values
        pulse = 0.0
        beat_detected = False
        confidence = 0.0

        if bpm > 0 and strength > 0.01:
            self.current_bpm = bpm

            # PLP pulse
            pulse = self.plp.update(bpm, strength, onset_val)

            # Peak detection - pass onset and phase for combined detection
            beat_detected = self.peak_picker.update(
                pulse, bpm, onset_strength=onset_val, phase=self.plp.phase
            )

            # Confidence tracking
            confidence = self.confidence_tracker.update(pulse, bpm, strength)
            self.current_confidence = confidence

        # Debug logging every 20 frames (~1 second)
        if self.debug and self._debug_frame % 20 == 0:
            phase = self.plp.phase
            phase_deg = phase * 180 / 3.14159

            # Show all tempo candidates with raw autocorrelation
            tempos, tgram = self.tempogram.compute()
            # Show all tempos
            all_str = " ".join(f"{int(tempos[i])}:{tgram[i]:.2f}" for i in range(len(tempos)))

            print(
                f"[debug] frame={self._debug_frame} onset={onset_val:.1f} "
                f"bpm={bpm:.0f} pulse={pulse:.2f} phase={phase_deg:.0f}° "
                f"tgram=[{all_str}]",
                flush=True,
            )

        # State machine
        state, should_emit = self.state_machine.update(
            confidence, bpm, beat_detected, current_time=now
        )

        # Track state changes
        prev_state = getattr(self, "_prev_state", None)
        if state != prev_state:
            self._prev_state = state
            self.last_state_change = now
            if self.osc:
                self.osc.send_state(state.value)

            # Log state transition
            if prev_state is not None:
                bpm_str = f"{self.current_bpm:.1f} BPM" if self.current_bpm > 0 else "no tempo"
                print(f"[state] {prev_state.value} -> {state.value} ({bpm_str})", flush=True)

            # MIDI clock mode: send Start/Stop on state transitions
            if self.midi and not self.midi_note_mode:
                if state == LockState.LOCKED:
                    self.midi.start_clock(self.current_bpm)
                elif prev_state == LockState.LOCKED:
                    self.midi.stop_clock()

        # Debug WebSocket broadcast
        # Use the same values that appear in server logs for consistency
        locked_bpm = self.state_machine.get_locked_bpm()
        conf_components = self.confidence_tracker.get_components()
        state_debug = self.state_machine.get_debug_info()

        if self.debug_ws:
            self.debug_ws.broadcast(
                {
                    "type": "frame",
                    "seq": self._debug_frame,
                    "ts": now,
                    "onset": float(onset_val),
                    "pulse": float(pulse),
                    "phase": float(self.plp.phase),
                    "bpm": float(locked_bpm),  # Use locked BPM, same as status log
                    "bpm_raw": float(bpm),  # Also include raw for debugging
                    "confidence": float(self.current_confidence),
                    "beat": should_emit,
                    "state": state.value,
                    "beats": self.beat_count,
                    # Diagnostic data
                    "conf_pulse": conf_components["pulse"],
                    "conf_tempo": conf_components["tempo"],
                    "conf_raw": conf_components["raw"],
                    "good_count": state_debug["consecutive_good"],
                    "bad_count": state_debug["consecutive_bad"],
                }
            )

        # Record frame data to file (same format as benchmark.py)
        if self.record_file:
            frame_data = {
                "type": "frame",
                "seq": self._debug_frame,
                "ts": now,
                "onset": float(onset_val),
                "pulse": float(pulse),
                "phase": float(self.plp.phase),
                "bpm": float(locked_bpm),
                "bpm_raw": float(bpm),
                "confidence": float(self.current_confidence),
                "beat": should_emit,
                "state": state.value,
                "beats": self.beat_count,
                "conf_pulse": conf_components["pulse"],
                "conf_tempo": conf_components["tempo"],
                "conf_raw": conf_components["raw"],
                "good_count": state_debug["consecutive_good"],
                "bad_count": state_debug["consecutive_bad"],
            }
            self.record_file.write(json.dumps(frame_data) + "\n")

        # Emit beat
        if should_emit:
            self.beat_count += 1

            # Log each beat
            print(f"[beat] #{self.beat_count} at {self.current_bpm:.1f} BPM (conf: {confidence:.0%})", flush=True)

            if self.osc:
                self.osc.send_beat()
                self.osc.send_bpm(self.current_bpm)
                self.osc.send_confidence(confidence)
            if self.midi:
                self.midi.send_beat()
                if not self.midi_note_mode:
                    self.midi.update_tempo(self.current_bpm)

    def run(self) -> None:
        """Start the beat tracking service."""
        self.running = True
        print("Starting PLP Beat Service...")
        print(f"  Device: {self.device or 'default'}")
        print(f"  Sample rate: {self.samplerate}")
        print(f"  BPM range: {self.bpm_min}-{self.bpm_max}")
        if self.osc:
            print(f"  OSC: {self.osc.client._address}:{self.osc.client._port}")
        if self.midi:
            mode = "Note" if self.midi_note_mode else "Clock (24 PPQN)"
            print(f"  MIDI: {self.midi.port_name} ({mode})")
        if self.debug_ws:
            print(f"  Debug: WebSocket on port {self.debug_ws.ws_port}, HTTP on port {self.debug_ws.http_port}")
        print("Press Ctrl+C to stop")
        print()

        # Start debug server if enabled
        if self.debug_ws:
            self.debug_ws.start()

        try:
            with sd.InputStream(
                device=self.device,
                channels=1,
                samplerate=self.samplerate,
                blocksize=BLOCK_SIZE,
                callback=self._audio_callback,
            ):
                while self.running:
                    time.sleep(0.1)
                    now = time.time()

                    # Status line for interactive terminal (updates in place)
                    if self._is_tty:
                        state = self.state_machine.get_state()
                        locked_bpm = self.state_machine.get_locked_bpm()
                        print(
                            f"\r[{state.value:10s}] BPM: {locked_bpm:5.1f} "
                            f"Conf: {self.current_confidence:.2f} "
                            f"Beats: {self.beat_count}",
                            end="",
                            flush=True,
                        )
                    # Periodic status for journal logs (every N seconds)
                    elif now - self._last_status_log >= LOG_STATUS_INTERVAL:
                        self._last_status_log = now
                        state = self.state_machine.get_state()
                        locked_bpm = self.state_machine.get_locked_bpm()
                        print(
                            f"[status] {state.value} | "
                            f"{locked_bpm:.1f} BPM | "
                            f"conf: {self.current_confidence:.0%} | "
                            f"beats: {self.beat_count}",
                            flush=True,
                        )
        except KeyboardInterrupt:
            if self._is_tty:
                print("\n")
            print("Stopping...", flush=True)
        finally:
            self.running = False
            if self.midi:
                self.midi.close()
            if self.debug_ws:
                self.debug_ws.stop()
            if self.record_file:
                self.record_file.close()
                print(f"[record] Recording saved: {self.record_path}", flush=True)
            print(f"[shutdown] Total beats: {self.beat_count}", flush=True)

    def stop(self) -> None:
        """Stop the beat tracking service."""
        self.running = False

    def get_state(self) -> LockState:
        """Get current lock state."""
        return self.state_machine.get_state()

    def get_bpm(self) -> float:
        """Get current BPM estimate."""
        return self.state_machine.get_locked_bpm() or self.current_bpm

    def get_confidence(self) -> float:
        """Get current confidence value."""
        return self.current_confidence
