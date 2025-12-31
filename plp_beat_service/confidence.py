"""Confidence signal tracking for beat gating."""

from collections import deque

import numpy as np


class ConfidenceTracker:
    """
    Tracks confidence/stability signal for beat gating.

    Uses:
    - Rolling variance of pulse amplitude
    - Agreement between tempo estimates
    - Slow-moving signal (not per-frame noise)
    """

    def __init__(
        self,
        pulse_window: int = 64,
        tempo_window: int = 16,
        smoothing: float = 0.1,
    ):
        self.pulse_window = pulse_window
        self.tempo_window = tempo_window
        self.smoothing = smoothing

        # State
        self.pulse_history: deque[float] = deque(maxlen=pulse_window)
        self.tempo_history: deque[float] = deque(maxlen=tempo_window)
        self.confidence: float = 0.0

    def update(self, pulse_peak: float, tempo: float, tempo_strength: float) -> float:
        """
        Update confidence signal.

        Args:
            pulse_peak: Current pulse curve peak value
            tempo: Current tempo estimate (BPM)
            tempo_strength: Raw tempo estimate confidence

        Returns:
            Smoothed confidence value (0-1)
        """
        self.pulse_history.append(pulse_peak)
        if tempo > 0:
            self.tempo_history.append(tempo)

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
                tempo_confidence = float(np.clip(1 - tempo_cv * 10, 0, 1))  # More sensitive
            else:
                tempo_confidence = 0.0
        else:
            tempo_confidence = 0.0

        # Component 3: Raw tempo strength
        raw_confidence = tempo_strength

        # Combine components
        combined = pulse_confidence * 0.3 + tempo_confidence * 0.4 + raw_confidence * 0.3

        # Smooth the confidence signal (slow-moving)
        self.confidence = self.confidence * (1 - self.smoothing) + combined * self.smoothing

        # Store components for debugging
        self.last_pulse_confidence = pulse_confidence
        self.last_tempo_confidence = tempo_confidence
        self.last_raw_confidence = raw_confidence
        self.last_combined = combined

        return self.confidence

    def get_components(self) -> dict:
        """Get confidence components for debugging."""
        return {
            "pulse": getattr(self, "last_pulse_confidence", 0.0),
            "tempo": getattr(self, "last_tempo_confidence", 0.0),
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
        self.confidence = 0.0
