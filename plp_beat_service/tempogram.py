"""Streaming tempogram computation using Fourier DFT at tempo frequencies."""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class StreamingTempogram:
    """
    Computes Fourier tempogram in streaming mode.

    Based on DFT at tempo candidate frequencies (not autocorrelation).
    Reference: ../real_time_plp/realtimeplp.py Tempogram class
    """

    samplerate: int = 44100
    hop_length: int = 512
    win_length_sec: float = 6.0  # Window length in seconds
    tempo_min: int = 115
    tempo_max: int = 165

    # Derived attributes (set in __post_init__)
    framerate: float = field(init=False)
    win_length: int = field(init=False)
    Theta: np.ndarray = field(init=False)  # Tempo candidates in BPM
    _tempo_buffer: np.ndarray = field(init=False, repr=False)
    _window: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.framerate = self.samplerate / self.hop_length
        self.win_length = round(self.win_length_sec * self.framerate)
        self.Theta = np.arange(self.tempo_min, self.tempo_max + 1, 1)
        self._tempo_buffer = np.zeros(self.win_length)
        self._window = np.hanning(self.win_length)

    def update(self, onset_strength: float) -> None:
        """Add new onset strength using half-window causal method."""
        # Half-window method: only roll left half, right stays zero
        half = self.win_length // 2
        left_half = self._tempo_buffer[:half]
        left_half = np.roll(left_half, -1)
        left_half[-1] = onset_strength
        self._tempo_buffer[:half] = left_half
        # Right half stays zero (no future data)

    def compute(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute Fourier tempogram using DFT at tempo frequencies.

        Returns:
            (Theta, X): Tempo values (BPM) and complex DFT coefficients
        """
        L = self._tempo_buffer.shape[0]
        m = np.arange(L) / self.framerate  # Time array in seconds
        K = len(self.Theta)
        X = np.zeros(K, dtype=np.complex128)

        for k in range(K):
            omega = self.Theta[k] / 60  # Convert BPM to Hz
            exponential = np.exp(-2 * np.pi * 1j * omega * m)
            X[k] = np.sum(self._tempo_buffer * self._window * exponential)

        return self.Theta, X

    def estimate_tempo(self) -> tuple[float, float, complex]:
        """
        Estimate dominant tempo from Fourier tempogram.

        Returns:
            (bpm, strength, coefficient): BPM, magnitude, and complex coefficient
        """
        Theta, X = self.compute()

        if len(X) == 0:
            return 0.0, 0.0, 0j

        magnitudes = np.abs(X)
        peak_idx = int(np.argmax(magnitudes))

        bpm = float(Theta[peak_idx])
        strength = float(magnitudes[peak_idx])
        coefficient = X[peak_idx]

        # Normalize strength to 0-1 range (based on window sum)
        max_possible = np.sum(self._window)
        if max_possible > 0:
            strength = min(1.0, strength / max_possible)

        return bpm, strength, coefficient

    def reset(self) -> None:
        """Reset tempogram state."""
        self._tempo_buffer.fill(0)
