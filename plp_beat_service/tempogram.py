"""Streaming tempogram computation for local tempo estimation."""

import numpy as np


class StreamingTempogram:
    """
    Computes tempogram in streaming mode.

    Based on autocorrelation of onset envelope.
    """

    def __init__(
        self,
        samplerate: int = 44100,
        hop_length: int = 512,
        win_length: int = 768,  # ~8.9 seconds at 512 block size
        tempo_min: int = 115,
        tempo_max: int = 165,
    ):
        self.samplerate = samplerate
        self.hop_length = hop_length
        self.win_length = win_length
        self.tempo_min = tempo_min
        self.tempo_max = tempo_max

        # Compute tempo range in lag samples
        self.sr_tempo = samplerate / hop_length  # Tempo sample rate
        # Use ceil for min (faster tempo = smaller lag) to not exceed tempo_max
        # Use floor for max (slower tempo = larger lag) to not go below tempo_min
        import math

        self.lag_min = math.ceil(60 * self.sr_tempo / tempo_max)
        self.lag_max = math.floor(60 * self.sr_tempo / tempo_min)

        # State
        self.onset_buffer: np.ndarray = np.zeros(win_length)

    def update(self, onset_strength: float) -> None:
        """Add new onset strength value to buffer."""
        self.onset_buffer = np.roll(self.onset_buffer, -1)
        self.onset_buffer[-1] = onset_strength

    def compute(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute tempogram from current buffer.

        Returns:
            (tempos, tempogram): Tempo values and corresponding strengths
        """
        # Normalize onset envelope
        env = self.onset_buffer - np.mean(self.onset_buffer)
        env_std = np.std(env)
        if env_std > 0:
            env = env / env_std

        # Compute autocorrelation for tempo range
        n_tempos = self.lag_max - self.lag_min + 1
        tempogram = np.zeros(n_tempos)

        for i, lag in enumerate(range(self.lag_min, self.lag_max + 1)):
            if lag < len(env):
                # Autocorrelation at this lag
                tempogram[i] = np.sum(env[:-lag] * env[lag:]) / (len(env) - lag)

        # Convert lags to BPM
        lags = np.arange(self.lag_min, self.lag_max + 1)
        tempos = 60 * self.sr_tempo / lags

        # Apply mild tempo prior: slight preference for middle of range
        # Use wide Gaussian to avoid over-penalizing edge tempos
        center_bpm = (self.tempo_min + self.tempo_max) / 2  # 140 for 115-165 range
        sigma = 50.0  # Wider preference to not penalize edge tempos too much
        tempo_prior = np.exp(-0.5 * ((tempos - center_bpm) / sigma) ** 2)
        # Ensure minimum prior of 0.7 so no tempo is penalized more than 30%
        tempo_prior = np.maximum(tempo_prior, 0.7)
        tempogram = tempogram * tempo_prior

        # Apply octave penalty to disambiguate half/double-time
        tempogram = self._apply_octave_penalty(tempos, tempogram)

        return tempos, tempogram

    def _apply_octave_penalty(self, tempos: np.ndarray, tempogram: np.ndarray) -> np.ndarray:
        """
        Penalize tempos whose half/double time is also strong.

        If 120 BPM and 60 BPM are both strong, prefer 120 BPM.
        If 120 BPM and 240 BPM are both strong, prefer 120 BPM.
        """
        result = tempogram.copy()

        for i, tempo in enumerate(tempos):
            # Check half-time
            half_tempo = tempo / 2
            if self.tempo_min <= half_tempo <= self.tempo_max:
                half_idx = np.argmin(np.abs(tempos - half_tempo))
                if np.abs(tempos[half_idx] - half_tempo) < 3.0:  # Within 3 BPM
                    half_strength = tempogram[half_idx]
                    # If half-time is nearly as strong, this might be double-time
                    if half_strength > tempogram[i] * 0.6:
                        result[i] *= 0.5  # Penalize potential double-time

            # Check double-time
            double_tempo = tempo * 2
            if self.tempo_min <= double_tempo <= self.tempo_max:
                double_idx = np.argmin(np.abs(tempos - double_tempo))
                if np.abs(tempos[double_idx] - double_tempo) < 3.0:
                    double_strength = tempogram[double_idx]
                    # If double-time has significant energy, boost this tempo
                    if double_strength > tempogram[i] * 0.4:
                        result[i] *= 1.3  # Boost the "normal" tempo

        return result

    def estimate_tempo(self) -> tuple[float, float]:
        """
        Estimate dominant tempo from tempogram.

        Uses parabolic interpolation for sub-sample peak accuracy.

        Returns:
            (bpm, strength): Estimated BPM and confidence
        """
        tempos, tempogram = self.compute()

        if len(tempogram) == 0 or np.max(tempogram) <= 0:
            return 0.0, 0.0

        # Find peak
        peak_idx = int(np.argmax(tempogram))
        strength = tempogram[peak_idx]

        # Parabolic interpolation for sub-sample accuracy
        # Only if we have neighbors on both sides
        if 0 < peak_idx < len(tempogram) - 1:
            y_prev = tempogram[peak_idx - 1]
            y_peak = tempogram[peak_idx]
            y_next = tempogram[peak_idx + 1]

            # Avoid division by zero
            denom = y_prev - 2 * y_peak + y_next
            if abs(denom) > 1e-10:
                delta = 0.5 * (y_prev - y_next) / denom
                # Clamp delta to reasonable range
                delta = np.clip(delta, -0.5, 0.5)
            else:
                delta = 0.0

            # Interpolated lag
            lag_int = self.lag_min + peak_idx
            lag_interp = lag_int + delta

            # Convert interpolated lag to BPM
            bpm = 60 * self.sr_tempo / lag_interp
        else:
            bpm = tempos[peak_idx]

        # Normalize strength to 0-1
        strength = float(np.clip(strength, 0, 1))

        return float(bpm), strength

    def reset(self) -> None:
        """Reset tempogram state."""
        self.onset_buffer.fill(0)
