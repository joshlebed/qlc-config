"""Peak picking for beat detection from PLP pulse curve."""

import numpy as np


class PeakPicker:
    """
    Detects beats from PLP pulse curve and onset envelope.

    Uses combined detection:
    - Onset peaks (transients in the audio)
    - Phase proximity (when PLP phase is near beat position)
    - Minimum inter-beat interval (based on BPM)
    """

    def __init__(
        self,
        samplerate: int = 44100,
        hop_length: int = 512,
        tempo_max: int = 165,
        threshold_ratio: float = 0.5,
        debug: bool = False,
    ):
        self.samplerate = samplerate
        self.hop_length = hop_length
        self.tempo_max = tempo_max
        self.threshold_ratio = threshold_ratio
        self.debug = debug

        # Tempo sample rate (frames per second)
        self.sr_tempo = samplerate / hop_length

        # State
        self.last_beat_frame: int = -1000
        self.frame_count: int = 0
        self.recent_pulses: list[float] = []
        self.recent_onsets: list[float] = []
        self._reject_count: int = 0
        self._reject_reason: str = ""

    def update(
        self,
        pulse_value: float,
        tempo: float,
        onset_strength: float = 0.0,
        phase: float = 0.0,
    ) -> bool:
        """
        Check if current frame is a beat.

        Args:
            pulse_value: Current PLP pulse curve value
            tempo: Current tempo estimate (BPM)
            onset_strength: Current onset envelope strength
            phase: Current PLP phase (0 = beat expected, pi = half cycle)

        Returns:
            True if beat detected at this frame
        """
        self.frame_count += 1
        self.recent_pulses.append(pulse_value)
        self.recent_onsets.append(onset_strength)

        # Keep only recent history
        if len(self.recent_pulses) > 200:
            self.recent_pulses = self.recent_pulses[-100:]
            self.recent_onsets = self.recent_onsets[-100:]

        # Minimum inter-beat interval in frames
        if tempo > 0:
            # At least 70% of expected beat period (reduced from 80% to catch more beats)
            beat_period_frames = self.sr_tempo * 60 / tempo
            min_interval = int(beat_period_frames * 0.70)
        else:
            min_interval = int(self.sr_tempo * 60 / self.tempo_max)

        # Check minimum interval since last beat
        frames_since_beat = self.frame_count - self.last_beat_frame
        if frames_since_beat < min_interval:
            self._reject_reason = f"min_int ({frames_since_beat}<{min_interval})"
            return False

        # Need at least 3 samples to detect
        if len(self.recent_onsets) < 3:
            return False

        # Check for onset peak (primary beat indicator)
        onset_prev = self.recent_onsets[-2]
        onset_prev_prev = self.recent_onsets[-3]
        onset_curr = self.recent_onsets[-1]

        # Compute adaptive onset threshold
        if len(self.recent_onsets) >= 20:
            onset_mean = np.mean(self.recent_onsets[-50:])
            onset_std = np.std(self.recent_onsets[-50:])
            # Lower threshold to catch more beats (reduced from 0.3 to 0.2)
            onset_threshold = onset_mean + 0.2 * onset_std
            onset_threshold = max(onset_threshold, 0.3)  # Lower minimum threshold
        else:
            onset_threshold = 1.0

        # Detect onset peak
        is_onset_peak = (
            onset_prev > onset_prev_prev
            and onset_prev > onset_curr
            and onset_prev > onset_threshold
        )

        # Check phase proximity (phase near 0 or near 2*pi means beat expected)
        # Allow beats within +/- 90 degrees of expected position (widened from 60°)
        phase_tolerance = np.pi / 2  # 90 degrees
        phase_near_beat = phase < phase_tolerance or phase > (2 * np.pi - phase_tolerance)

        # Also check pulse peaks as backup
        pulse_prev = self.recent_pulses[-2]
        pulse_prev_prev = self.recent_pulses[-3]
        pulse_curr = self.recent_pulses[-1]
        is_pulse_peak = (
            pulse_prev > pulse_prev_prev
            and pulse_prev >= pulse_curr
            and pulse_prev > 0.3
        )

        # Beat detection strategies:
        # Primary: onset peaks (audio-driven)
        # Secondary: pulse peaks with phase alignment (tempo-driven)

        method = None
        if is_onset_peak:
            # Onset peak - trust the audio
            if phase_near_beat:
                method = "onset+phase"
            else:
                method = "onset"
        elif is_pulse_peak and phase_near_beat:
            # Pulse peak requires phase alignment
            method = "pulse+phase"

        if method is None:
            return False

        # Beat detected!
        if self.debug:
            phase_deg = phase * 180 / np.pi
            print(
                f"[peak] BEAT({method}) frame={self.frame_count}: "
                f"onset={onset_prev:.1f} pulse={pulse_prev:.2f} phase={phase_deg:.0f}° "
                f"interval={frames_since_beat}",
                flush=True,
            )
        self.last_beat_frame = self.frame_count - 1
        return True

    def get_frames_since_beat(self) -> int:
        """Get number of frames since last detected beat."""
        return self.frame_count - self.last_beat_frame

    def reset(self) -> None:
        """Reset peak picker state."""
        self.last_beat_frame = -1000
        self.frame_count = 0
        self.recent_pulses.clear()
        self.recent_onsets.clear()
