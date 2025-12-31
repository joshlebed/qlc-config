"""MIDI output for beat events."""

import threading
import time

try:
    import rtmidi

    HAVE_RTMIDI = True
except ImportError:
    HAVE_RTMIDI = False
    rtmidi = None  # type: ignore

# MIDI message types
MIDI_CLOCK = 0xF8
MIDI_START = 0xFA
MIDI_STOP = 0xFC
MIDI_NOTE_ON = 0x90
MIDI_NOTE_OFF = 0x80


class MIDIOutput:
    """
    MIDI output for beat events.

    Supports two modes:
    - Note mode: Send MIDI notes on each beat
    - Clock mode: Send MIDI Clock (24 PPQN) with Start/Stop
    """

    def __init__(
        self,
        port_name: str = "PLPBeat",
        note_mode: bool = True,
        note: int = 36,  # C1 (kick drum in GM)
        velocity: int = 100,
        channel: int = 0,
    ):
        if not HAVE_RTMIDI:
            raise ImportError(
                "rtmidi not installed. Install with: uv pip install python-rtmidi"
            )

        self.port_name = port_name
        self.note_mode = note_mode
        self.note = note
        self.velocity = velocity
        self.channel = channel

        # MIDI state
        self.midi = rtmidi.MidiOut()
        self.midi.open_virtual_port(port_name)
        self.clock_running = False
        self.last_bpm: float = 0.0

        # Clock thread (for continuous PPQN output)
        self._clock_thread: threading.Thread | None = None
        self._clock_stop = threading.Event()

    def send_beat(self) -> None:
        """Send beat event (note or clock pulse depending on mode)."""
        if self.note_mode:
            self._send_note()
        else:
            # In clock mode, beats are handled by the clock thread
            pass

    def _send_note(self, duration: float = 0.02) -> None:
        """Send a MIDI note with proper duration."""
        msg_on = [MIDI_NOTE_ON | self.channel, self.note, self.velocity]
        msg_off = [MIDI_NOTE_OFF | self.channel, self.note, 0]
        self.midi.send_message(msg_on)
        # Schedule note off
        threading.Timer(duration, lambda: self.midi.send_message(msg_off)).start()

    def send_clock(self) -> None:
        """Send single MIDI clock pulse."""
        self.midi.send_message([MIDI_CLOCK])

    def send_start(self) -> None:
        """Send MIDI Start message."""
        if not self.clock_running:
            self.midi.send_message([MIDI_START])
            self.clock_running = True

    def send_stop(self) -> None:
        """Send MIDI Stop message."""
        if self.clock_running:
            self.midi.send_message([MIDI_STOP])
            self.clock_running = False

    def start_clock(self, bpm: float) -> None:
        """
        Start continuous MIDI clock output.

        Sends 24 pulses per quarter note at the given BPM.
        """
        if self._clock_thread is not None and self._clock_thread.is_alive():
            self.stop_clock()

        self.last_bpm = bpm
        self._clock_stop.clear()
        self._clock_thread = threading.Thread(target=self._clock_loop, daemon=True)
        self._clock_thread.start()
        self.send_start()

    def stop_clock(self) -> None:
        """Stop continuous MIDI clock output."""
        self._clock_stop.set()
        if self._clock_thread is not None:
            self._clock_thread.join(timeout=0.5)
        self.send_stop()

    def update_tempo(self, bpm: float) -> None:
        """Update the clock tempo."""
        self.last_bpm = bpm

    def _clock_loop(self) -> None:
        """Background thread for continuous clock output."""
        ppqn = 24  # Pulses per quarter note
        while not self._clock_stop.is_set():
            if self.last_bpm > 0:
                # Calculate pulse interval
                beat_period = 60.0 / self.last_bpm
                pulse_interval = beat_period / ppqn

                self.send_clock()
                time.sleep(pulse_interval)
            else:
                time.sleep(0.01)

    def close(self) -> None:
        """Clean up MIDI resources."""
        self.stop_clock()
        self.midi.close_port()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
