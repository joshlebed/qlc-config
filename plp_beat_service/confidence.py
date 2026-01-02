"""Confidence signal tracking for beat gating."""

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class BeatPrediction:
    """A predicted beat and whether it was detected."""

    time: float
    phase: float
    hit: bool = False
    onset_strength: float = 0.0
    phase_error: float | None = None


class ConfidenceTracker:
    """
    Tracks confidence/stability signal for beat gating.

    Uses beat alignment (hit rate) as primary signal:
    - Records when beats are predicted (phase-based)
    - Records when beats are detected (onset-based)
    - Confidence = fraction of predictions that got hits
    """

    # Default silence floor - tune based on measured noise
    DEFAULT_SILENCE_FLOOR = 0.01  # Very conservative to start

    def __init__(
        self,
        pulse_window: int = 64,
        tempo_window: int = 16,
        smoothing_up: float = 0.1,  # Slow rise
        smoothing_down: float = 0.3,  # Fast fall (for breakdowns)
        silence_floor: float | None = None,  # Absolute RMS threshold
    ):
        self.pulse_window = pulse_window
        self.tempo_window = tempo_window
        self.smoothing_up = smoothing_up
        self.smoothing_down = smoothing_down
        self.silence_floor = (
            silence_floor if silence_floor is not None else self.DEFAULT_SILENCE_FLOOR
        )

        # Legacy state (kept for compatibility during transition)
        self.pulse_history: deque[float] = deque(maxlen=pulse_window)
        self.tempo_history: deque[float] = deque(maxlen=tempo_window)
        self.onset_history: deque[float] = deque(maxlen=32)
        self.confidence: float = 0.0

        # NEW: Prediction tracking for alignment-based confidence
        self.predictions: list[BeatPrediction] = []
        self.max_predictions: int = 16  # Keep last N predictions

    def record_prediction(self, predicted_time: float, phase: float) -> None:
        """
        Record that a beat is expected at the given time.

        Called when PLP phase indicates beat should occur.
        """
        self.predictions.append(
            BeatPrediction(
                time=predicted_time,
                phase=phase,
            )
        )
        # Trim old predictions
        if len(self.predictions) > self.max_predictions:
            self.predictions = self.predictions[-self.max_predictions :]

    def record_hit(
        self,
        onset_time: float,
        onset_strength: float,
        phase_error: float,
        tolerance: float = 0.050,  # 50ms
    ) -> bool:
        """
        Record that an onset peak was detected - match to nearest prediction.

        Args:
            onset_time: Time of detected onset peak
            onset_strength: Strength of the onset
            phase_error: Phase error at detection time
            tolerance: Max time difference to consider a match

        Returns:
            True if matched a prediction, False otherwise
        """
        # Find nearest unmatched prediction within tolerance
        for pred in reversed(self.predictions):
            if pred.hit:
                continue  # Already matched
            time_diff = abs(pred.time - onset_time)
            if time_diff <= tolerance:
                pred.hit = True
                pred.onset_strength = onset_strength
                pred.phase_error = phase_error
                return True
        return False

    def get_recent_predictions(self, n: int = 8) -> list[BeatPrediction]:
        """Get last N predictions for confidence computation."""
        return self.predictions[-n:] if self.predictions else []

    def update(
        self,
        pulse_peak: float,
        tempo: float,
        tempo_strength: float,
        onset_strength: float = 0.0,
        rms: float = 0.0,
        peak_rms: float = 0.0,
    ) -> float:
        """
        Update confidence signal using beat alignment.

        Args:
            pulse_peak: Current pulse curve peak value (legacy, kept for compat)
            tempo: Current tempo estimate (BPM)
            tempo_strength: Raw tempo estimate confidence
            onset_strength: Current onset envelope value
            rms: Current audio RMS level
            peak_rms: Peak RMS level observed

        Returns:
            Smoothed confidence value (0-1)
        """
        # Keep legacy tracking for now
        self.pulse_history.append(pulse_peak)
        self.onset_history.append(onset_strength)
        if tempo > 0:
            self.tempo_history.append(tempo)

        # ===== NEW CONFIDENCE COMPUTATION =====

        # GATE 1: Absolute energy floor
        # If peak RMS is below silence floor, no confidence
        if peak_rms < self.silence_floor:
            combined = 0.0
        else:
            # Get recent predictions for analysis
            recent = self.get_recent_predictions(8)

            if len(recent) < 4:
                # Not enough data yet - use tempo strength as fallback
                combined = tempo_strength * 0.5
            else:
                # Component 1: Hit rate (50% weight)
                # What fraction of predictions had matching onset peaks?
                hits = sum(1 for p in recent if p.hit)
                hit_rate = hits / len(recent)

                # Component 2: Onset strength ratio (30% weight)
                # Are hits louder than misses?
                hit_strengths = [p.onset_strength for p in recent if p.hit]
                if hit_strengths:
                    mean_hit_strength = float(np.mean(hit_strengths))
                    # Compare to background onset level
                    if len(self.onset_history) > 0:
                        bg_onset = float(np.percentile(list(self.onset_history), 50))
                        if bg_onset > 0.01:
                            ratio = mean_hit_strength / bg_onset
                            strength_conf = float(np.clip(ratio / 3.0, 0, 1))
                        else:
                            strength_conf = 1.0 if mean_hit_strength > 0.1 else 0.0
                    else:
                        strength_conf = 0.5
                else:
                    strength_conf = 0.0

                # Component 3: Phase error consistency (20% weight)
                # Low variance in phase errors = good lock
                phase_errors = [
                    p.phase_error for p in recent if p.phase_error is not None
                ]
                if len(phase_errors) >= 3:
                    phase_std = float(np.std(phase_errors))
                    # Expect phase errors < 0.5 radians for good lock
                    phase_conf = float(np.clip(1.0 - phase_std / 0.5, 0, 1))
                else:
                    phase_conf = 0.0

                # Combine components
                combined = hit_rate * 0.5 + strength_conf * 0.3 + phase_conf * 0.2

        # Asymmetric smoothing: fast fall, slow rise
        if combined < self.confidence:
            smoothing = self.smoothing_down  # Fast fall for breakdowns
        else:
            smoothing = self.smoothing_up  # Slow rise for stability

        self.confidence = self.confidence * (1 - smoothing) + combined * smoothing

        # Store components for debugging
        recent = self.get_recent_predictions(8)
        hits = sum(1 for p in recent if p.hit) if recent else 0
        self.last_hit_rate = hits / len(recent) if recent else 0.0
        self.last_combined = combined
        self.last_peak_rms = peak_rms

        return self.confidence

    def get_components(self) -> dict[str, float]:
        """Get confidence components for debugging."""
        return {
            "hit_rate": getattr(self, "last_hit_rate", 0.0),
            "combined": getattr(self, "last_combined", 0.0),
            "smoothed": self.confidence,
            "peak_rms": getattr(self, "last_peak_rms", 0.0),
            # Legacy (keep for compat)
            "pulse": 0.0,
            "tempo": 0.0,
            "onset": 0.0,
            "raw": 0.0,
        }

    def get_confidence(self) -> float:
        """Get current confidence value."""
        return self.confidence

    def reset(self) -> None:
        """Reset confidence tracker."""
        self.pulse_history.clear()
        self.tempo_history.clear()
        self.onset_history.clear()
        self.predictions.clear()
        self.confidence = 0.0
