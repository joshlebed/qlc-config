"""Confidence signal tracking for beat gating."""

from collections import deque

import numpy as np


class ConfidenceTracker:
    """
    Tracks confidence/stability signal for beat gating.

    Uses 4-component energy-based model:
    - Pulse consistency (low CV = high confidence)
    - Tempo agreement (low CV = high confidence)
    - Onset energy (relative to recent peak)
    - Raw tempo strength

    Includes absolute RMS gate to prevent beats during silence.
    """

    # Silence threshold - only absolute, relative was too aggressive for music dynamics
    # User's mic shows ~0.002-0.005 during silence, ~0.01+ during music
    SILENCE_RMS_THRESHOLD = 0.006

    def __init__(
        self,
        pulse_window: int = 64,
        tempo_window: int = 16,
        smoothing_up: float = 0.2,  # Moderate rise
        smoothing_down: float = 0.3,  # Fast fall (for breakdowns)
    ):
        self.pulse_window = pulse_window
        self.tempo_window = tempo_window
        self.smoothing_up = smoothing_up
        self.smoothing_down = smoothing_down

        # State
        self.pulse_history: deque[float] = deque(maxlen=pulse_window)
        self.tempo_history: deque[float] = deque(maxlen=tempo_window)
        self.onset_history: deque[float] = deque(maxlen=32)
        self.rms_history: deque[float] = deque(maxlen=32)  # Track RMS for silence detection (longer window)
        self.rms_peak: float = 0.0  # Peak RMS seen (for relative silence detection)
        self.confidence: float = 0.0
        self.is_silence: bool = False  # True when in silence/noise floor

    def update(
        self,
        pulse_peak: float,
        tempo: float,
        tempo_strength: float,
        onset_strength: float = 0.0,
        rms: float = 0.0,
    ) -> float:
        """
        Update confidence signal.

        Args:
            pulse_peak: Current pulse curve peak value
            tempo: Current tempo estimate (BPM)
            tempo_strength: Raw tempo estimate confidence
            onset_strength: Current onset envelope value (audio energy)
            rms: Current RMS level for absolute silence detection

        Returns:
            Smoothed confidence value (0-1)
        """
        self.pulse_history.append(pulse_peak)
        self.onset_history.append(onset_strength)
        self.rms_history.append(rms)
        if tempo > 0:
            self.tempo_history.append(tempo)

        # SILENCE GATE: Simple absolute threshold with median smoothing
        # Update peak RMS for status logging
        self.rms_peak = max(self.rms_peak * 0.999, rms)

        # Use median of recent RMS values - robust to occasional noise spikes
        if len(self.rms_history) >= 8:
            recent_rms = float(np.median(list(self.rms_history)[-16:]))
        else:
            recent_rms = rms

        self.is_silence = recent_rms < self.SILENCE_RMS_THRESHOLD

        # If in silence, force confidence to 0 immediately
        if self.is_silence:
            self.confidence = 0.0
            self.last_pulse_confidence = 0.0
            self.last_tempo_confidence = 0.0
            self.last_onset_confidence = 0.0
            self.last_raw_confidence = 0.0
            self.last_combined = 0.0
            return 0.0

        # Component 1: Pulse consistency (low variance = high confidence)
        if len(self.pulse_history) >= 4:
            pulse_std = float(np.std(self.pulse_history))
            pulse_mean = float(np.mean(self.pulse_history))
            if pulse_mean > 0:
                pulse_cv = pulse_std / pulse_mean  # Coefficient of variation
                pulse_confidence = float(np.clip(1 - pulse_cv, 0, 1))
            else:
                pulse_confidence = 0.0
        else:
            pulse_confidence = 0.0

        # Component 2: Tempo agreement (low variance = high confidence)
        if len(self.tempo_history) >= 4:
            tempo_std = float(np.std(self.tempo_history))
            tempo_mean = float(np.mean(self.tempo_history))
            if tempo_mean > 0:
                tempo_cv = tempo_std / tempo_mean
                # 5% CV (6 BPM on 120) = 75% confidence, 2% CV = 90%
                tempo_confidence = float(np.clip(1 - tempo_cv * 5, 0, 1))
            else:
                tempo_confidence = 0.0
        else:
            tempo_confidence = 0.0

        # Component 3: Onset energy (adaptive threshold for breakdown detection)
        if len(self.onset_history) >= 16:
            recent_onset = float(np.mean(list(self.onset_history)[-8:]))
            # Use 75th percentile as reference (more forgiving than 90th)
            peak_onset = float(np.percentile(list(self.onset_history), 75))
            if peak_onset > 0.01:  # Have some reference
                # If recent is near typical level, high confidence
                # If recent is much lower, breakdown
                ratio = recent_onset / peak_onset
                onset_confidence = float(np.clip(ratio * 1.2, 0, 1))
            else:
                onset_confidence = 0.5  # No reference yet
        else:
            onset_confidence = 0.5  # Neutral early on

        # Component 4: Raw tempo strength
        raw_confidence = tempo_strength

        # Combine components (onset energy now weighted heavily)
        combined = (
            pulse_confidence * 0.2
            + tempo_confidence * 0.2
            + onset_confidence * 0.4  # Heavily weight actual audio energy
            + raw_confidence * 0.2
        )

        # Asymmetric smoothing: fast fall, slow rise
        if combined < self.confidence:
            smoothing = self.smoothing_down  # Fast fall
        else:
            smoothing = self.smoothing_up  # Slow rise

        self.confidence = self.confidence * (1 - smoothing) + combined * smoothing

        # Store components for debugging
        self.last_pulse_confidence = pulse_confidence
        self.last_tempo_confidence = tempo_confidence
        self.last_onset_confidence = onset_confidence
        self.last_raw_confidence = raw_confidence
        self.last_combined = combined

        return self.confidence

    def get_components(self) -> dict[str, float]:
        """Get confidence components for debugging."""
        return {
            "pulse": getattr(self, "last_pulse_confidence", 0.0),
            "tempo": getattr(self, "last_tempo_confidence", 0.0),
            "onset": getattr(self, "last_onset_confidence", 0.0),
            "raw": getattr(self, "last_raw_confidence", 0.0),
            "combined": getattr(self, "last_combined", 0.0),
            "smoothed": self.confidence,
        }

    def get_confidence(self) -> float:
        """Get current confidence value."""
        return self.confidence

    def reset(self) -> None:
        """Reset confidence tracker."""
        self.pulse_history.clear()
        self.tempo_history.clear()
        self.onset_history.clear()
        self.rms_history.clear()
        self.rms_peak = 0.0
        self.confidence = 0.0
        self.is_silence = False
