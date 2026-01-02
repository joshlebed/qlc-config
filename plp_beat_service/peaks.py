"""Peak picking for beat detection from PLP pulse curve."""

import time
from collections.abc import Callable

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
        lookahead_frames: float = 5.0,  # Emit beats this many frames early
        on_prediction: Callable[[float, float], None] | None = None,  # Callback for predictions
    ):
        self.samplerate = samplerate
        self.hop_length = hop_length
        self.tempo_max = tempo_max
        self.threshold_ratio = threshold_ratio
        self.debug = debug
        self.lookahead_frames = lookahead_frames
        self.on_prediction = on_prediction  # Callback(time, phase)

        # Tempo sample rate (frames per second)
        self.sr_tempo = samplerate / hop_length

        # State
        self.last_beat_frame: int = -1000
        self.frame_count: int = 0
        self.recent_pulses: list[float] = []
        self.recent_onsets: list[float] = []
        self._reject_count: int = 0
        self._reject_reason: str = ""
        self._last_phase: float = 0.0  # Track phase for wrap detection
        self._last_beat_offset: float = 0.0  # Sub-frame offset for precise timing
        self._in_prediction_window: bool = False  # Track if we're in lookahead window

    def update(
        self,
        pulse_value: float,
        tempo: float,
        onset_strength: float = 0.0,
        phase: float = 0.0,
        current_time: float | None = None,
    ) -> bool:
        """
        Hybrid beat detection: onset peaks + phase-based prediction.

        Uses onset peaks as primary beat indicator (audio-driven),
        with phase-based prediction for low-latency emission.

        Args:
            pulse_value: Current PLP pulse curve value
            tempo: Current tempo estimate (BPM)
            onset_strength: Current onset envelope strength
            phase: Current PLP phase (0 = beat expected, 2*pi = next beat)
            current_time: Optional timestamp (uses time.time() if not provided)

        Returns:
            True if beat should be emitted this frame
        """
        self.frame_count += 1
        self.recent_pulses.append(pulse_value)
        self.recent_onsets.append(onset_strength)

        # Keep only recent history
        if len(self.recent_pulses) > 200:
            self.recent_pulses = self.recent_pulses[-100:]
            self.recent_onsets = self.recent_onsets[-100:]

        # Minimum inter-beat interval in frames (85% to prevent double triggers)
        if tempo > 0:
            beat_period_frames = self.sr_tempo * 60 / tempo
            min_interval = int(beat_period_frames * 0.85)
        else:
            min_interval = int(self.sr_tempo * 60 / self.tempo_max)

        # Check minimum interval since last beat
        frames_since_beat = self.frame_count - self.last_beat_frame
        if frames_since_beat < min_interval:
            self._reject_reason = f"min_int ({frames_since_beat}<{min_interval})"
            self._last_phase = phase
            return False

        # Need at least 3 samples to detect peaks
        if len(self.recent_onsets) < 3:
            self._last_phase = phase
            return False

        # ===== METHOD 1: Onset Peak Detection (primary, audio-driven) =====
        onset_prev = self.recent_onsets[-2]
        onset_prev_prev = self.recent_onsets[-3]
        onset_curr = self.recent_onsets[-1]

        # Adaptive onset threshold (works for both direct file and room sim/mic levels)
        if len(self.recent_onsets) >= 20:
            onset_mean = np.mean(self.recent_onsets[-50:])
            onset_std = np.std(self.recent_onsets[-50:])
            # Use percentile-based minimum to adapt to signal level
            onset_p90 = float(np.percentile(self.recent_onsets[-50:], 90))
            onset_threshold = onset_mean + 0.5 * onset_std
            # Minimum is 30% of peak level (adapts to mic/room gain)
            min_threshold = max(onset_p90 * 0.3, 0.01)
            onset_threshold = max(onset_threshold, min_threshold)
        else:
            onset_threshold = 0.1  # Lower initial threshold

        # Detect onset peak
        is_onset_peak = (
            onset_prev > onset_prev_prev
            and onset_prev > onset_curr
            and onset_prev > onset_threshold
        )

        # Sub-frame interpolation for onset peaks using parabolic fit
        onset_offset = -1.0  # Default: peak was 1 frame ago (at index -2)
        if is_onset_peak:
            # Parabolic interpolation: find true peak between samples
            denom = onset_prev_prev - 2 * onset_prev + onset_curr
            if abs(denom) > 1e-10:
                delta = 0.5 * (onset_prev_prev - onset_curr) / denom
                delta = np.clip(delta, -0.5, 0.5)  # Limit to reasonable range
                onset_offset = delta - 1.0  # Offset from current frame

        # ===== METHOD 2: Phase-Based Prediction (secondary, tempo-driven) =====
        phase_near_beat = False
        if tempo > 0:
            beat_period_frames = self.sr_tempo * 60 / tempo
            phase_increment = 2 * np.pi / beat_period_frames
            if phase_increment > 0:
                frames_to_beat = (2 * np.pi - phase) / phase_increment
                # Emit early when approaching beat position
                phase_near_beat = 0 < frames_to_beat <= self.lookahead_frames

                # Record prediction when we first enter the lookahead window
                if phase_near_beat and not self._in_prediction_window:
                    self._in_prediction_window = True
                    if self.on_prediction:
                        now = current_time if current_time is not None else time.time()
                        self.on_prediction(now, phase)

            # Also check for phase wrap (beat position crossed)
            phase_wrapped = self._last_phase > 5.0 and phase < 1.0
            if phase_wrapped:
                phase_near_beat = True
                self._in_prediction_window = False  # Reset for next beat

        # Reset prediction window when we exit the lookahead region
        if not phase_near_beat:
            self._in_prediction_window = False

        self._last_phase = phase

        # ===== DECISION LOGIC =====
        # Phase alignment check: is phase near beat position (within 90 degrees)?
        phase_tolerance = np.pi / 2  # 90 degrees
        phase_aligned = phase < phase_tolerance or phase > (2 * np.pi - phase_tolerance)

        method = None
        if is_onset_peak:
            # Onset peak detected
            if phase_aligned:
                method = "onset+phase"
            else:
                method = "onset"
        elif phase_near_beat:
            # Phase prediction - only if some audio activity
            if len(self.recent_onsets) >= 10:
                recent_mean = float(np.mean(self.recent_onsets[-10:]))
                if recent_mean >= 0.1:
                    method = "predict"

        if method is None:
            return False

        # Beat detected! Store sub-frame offset for precise timing
        # Only use sub-frame interpolation for onset detection (not prediction)
        if method in ("onset", "onset+phase"):
            self._last_beat_offset = onset_offset
        else:
            # For phase prediction, we're emitting early - use 0 offset
            # (the beat hasn't happened yet, so no interpolation is possible)
            self._last_beat_offset = 0.0

        if self.debug:
            phase_deg = phase * 180 / np.pi
            print(
                f"[peak] BEAT({method}) frame={self.frame_count}: "
                f"onset={onset_prev:.1f} phase={phase_deg:.0f}° "
                f"interval={frames_since_beat} offset={self._last_beat_offset:.2f}",
                flush=True,
            )

        self.last_beat_frame = self.frame_count
        return True

    def get_frames_since_beat(self) -> int:
        """Get number of frames since last detected beat."""
        return self.frame_count - self.last_beat_frame

    def get_last_beat_offset(self) -> float:
        """
        Get sub-frame offset of the last detected beat.

        Returns:
            Offset in frames from when the beat was reported.
            Negative values mean the beat was earlier (e.g., -0.5 = half frame ago).
            Positive values mean the beat is predicted for the future.
        """
        return self._last_beat_offset

    def reset(self) -> None:
        """Reset peak picker state."""
        self.last_beat_frame = -1000
        self.frame_count = 0
        self.recent_pulses.clear()
        self.recent_onsets.clear()
        self._last_phase = 0.0
        self._last_beat_offset = 0.0
        self._in_prediction_window = False
