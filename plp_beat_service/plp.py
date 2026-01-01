"""Predominant Local Pulse (PLP) computation with phase locking."""

from collections import deque

import numpy as np


class PLPTracker:
    """
    Streaming PLP pulse curve computation with phase locking.

    Instead of free-running oscillator, this tracks actual onset positions
    and adjusts phase to align with detected beats.
    """

    def __init__(
        self,
        samplerate: int = 44100,
        hop_length: int = 512,
        tempo_min: int = 115,
        tempo_max: int = 165,
    ):
        self.samplerate = samplerate
        self.hop_length = hop_length
        self.tempo_min = tempo_min
        self.tempo_max = tempo_max

        # Tempo sample rate (frames per second)
        self.sr_tempo = samplerate / hop_length

        # State
        self.pulse_history: list[float] = []
        self.onset_history: deque[float] = deque(maxlen=200)
        self.current_tempo: float = 0.0
        self.phase: float = 0.0
        self.frame_count: int = 0

        # Phase locking state
        self.last_onset_peak_frame: int = -100
        self.onset_peak_threshold: float = 0.5

    def update(self, tempo: float, tempo_strength: float, onset_strength: float) -> float:
        """
        Update PLP pulse curve with phase locking to onset peaks.

        Args:
            tempo: Estimated tempo in BPM
            tempo_strength: Confidence in tempo estimate (0-1)
            onset_strength: Current onset strength

        Returns:
            Current pulse value (high near expected beat positions)
        """
        self.frame_count += 1
        self.onset_history.append(onset_strength)

        if tempo <= 0 or tempo_strength < 0.01:
            pulse = onset_strength * 0.3
            self.pulse_history.append(pulse)
            return pulse

        # Update tempo with smoothing
        if self.current_tempo <= 0:
            self.current_tempo = tempo
        else:
            blend = 0.05 * tempo_strength
            self.current_tempo = self.current_tempo * (1 - blend) + tempo * blend

        # Beat period in frames
        beat_period = self.sr_tempo * 60 / self.current_tempo
        phase_increment = 2 * np.pi / beat_period

        # Advance phase (use modulo for proper wrapping)
        self.phase += phase_increment
        self.phase = self.phase % (2 * np.pi)

        # Detect onset peaks and adjust phase
        if len(self.onset_history) >= 3:
            # Check if previous frame was an onset peak
            prev = self.onset_history[-2]
            prev_prev = self.onset_history[-3]
            curr = self.onset_history[-1]

            # Compute adaptive threshold from recent onset values (lowered to catch more peaks)
            if len(self.onset_history) >= 20:
                recent = list(self.onset_history)[-50:]
                threshold = np.mean(recent) + 0.3 * np.std(recent)  # Reduced from 0.5
                threshold = max(threshold, 0.2)  # Reduced from 0.3
            else:
                threshold = 0.3  # Lower initial threshold

            is_peak = prev > prev_prev and prev > curr and prev > threshold

            # Check minimum distance from last peak (at least 60% of beat period)
            frames_since_peak = self.frame_count - 1 - self.last_onset_peak_frame
            min_distance = int(beat_period * 0.6)

            if is_peak and frames_since_peak >= min_distance:
                self.last_onset_peak_frame = self.frame_count - 1

                # Phase correction: onset peak should be at phase = 0
                # Current phase tells us how far we are from expected beat
                phase_error = self.phase
                if phase_error > np.pi:
                    phase_error -= 2 * np.pi

                # Apply phase correction (blend toward zero)
                # Stronger correction when far from expected beat (increased from 0.3 to 0.5)
                correction_strength = 0.5 * min(1.0, abs(phase_error) / np.pi)
                self.phase = self.phase * (1 - correction_strength)

        # Compute pulse value
        # High pulse (near 1) when phase is near 0 (beat expected)
        # Pulse is half-rectified cosine centered on beat
        pulse = float(np.maximum(0, np.cos(self.phase)))

        # Weight by onset strength to emphasize actual transients
        pulse = pulse * (0.6 + 0.4 * min(onset_strength / 5.0, 1.0))

        self.pulse_history.append(pulse)
        return pulse

    def predict_frames_to_beat(self) -> float:
        """
        Predict frames until next beat based on current phase.

        Returns:
            Number of frames until phase wraps to 0 (beat position).
            Returns infinity if tempo is not established.
        """
        if self.current_tempo <= 0:
            return float("inf")

        # Beat period in frames
        beat_period_frames = self.sr_tempo * 60 / self.current_tempo
        phase_increment = 2 * np.pi / beat_period_frames

        # Phase wraps at 2*pi, beat occurs at phase=0
        # Calculate frames until phase wraps
        if phase_increment <= 0:
            return float("inf")

        frames_to_beat = (2 * np.pi - self.phase) / phase_increment
        return float(frames_to_beat)

    def get_pulse_curve(self, n_frames: int = 64) -> np.ndarray:
        """Get recent pulse curve for peak detection."""
        if len(self.pulse_history) < n_frames:
            pad = [0.0] * (n_frames - len(self.pulse_history))
            return np.array(pad + self.pulse_history[-n_frames:])
        return np.array(self.pulse_history[-n_frames:])

    def reset(self) -> None:
        """Reset PLP state."""
        self.pulse_history.clear()
        self.onset_history.clear()
        self.current_tempo = 0.0
        self.phase = 0.0
        self.frame_count = 0
        self.last_onset_peak_frame = -100
