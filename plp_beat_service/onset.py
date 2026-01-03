"""Streaming onset strength envelope computation."""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class OnsetEnvelopeTracker:
    """
    Beat activation (spectral flux) from audio input.

    Ported from reference: ../real_time_plp/realtimeplp.py BeatActivation class

    Uses log-compressed spectrogram and half-wave rectified spectral flux
    with causal local average subtraction.
    """

    N: int = 1024  # Window size for STFT
    H: int = 512  # Hop size (must match audio block size)
    samplerate: int = 44100
    gamma: int = 1000  # Log compression parameter
    M: int = 10  # Local average window size (frames, causal)

    # Internal state
    _window_buffer: np.ndarray = field(init=False, repr=False)
    _la_buffer: np.ndarray = field(init=False, repr=False)
    _Y_last: np.ndarray = field(init=False, repr=False)
    _hann_window: np.ndarray = field(init=False, repr=False)

    # Output
    activation_frame: np.ndarray = field(init=False, repr=False)
    peak_rms: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._window_buffer = np.zeros(self.N)
        self._la_buffer = np.zeros(self.M)
        self._Y_last = np.zeros((self.N // 2 + 1, 1))
        self._hann_window = np.hanning(self.N)
        self.activation_frame = np.array([0.0])

    def process(self, audio_frame: np.ndarray) -> tuple[np.ndarray, float]:
        """
        Process audio frame to compute onset activation.

        Args:
            audio_frame: Audio samples (length should be H=512)

        Returns:
            Tuple of (onset activation array, RMS level)
        """
        # Compute RMS for energy tracking
        rms = float(np.sqrt(np.mean(audio_frame**2)))
        self.peak_rms = max(self.peak_rms * 0.99, rms)

        # STFT
        X_frame = self._stft(audio_frame)

        # Spectrogram with log compression
        Y_frame = self._spectrogram(X_frame)

        # Spectral flux (novelty)
        Y_diff = np.diff(Y_frame, n=1, prepend=self._Y_last, axis=0)
        Y_diff[Y_diff < 0] = 0  # Half-wave rectification
        nov = np.sum(Y_diff, axis=0)

        # Store last spectrogram
        self._Y_last = Y_frame

        # Local average (causal - only looks back)
        la = self._local_average(nov)

        # Normalize: subtract local average and half-wave rectify
        nov_norm = self._normalize(nov, la)

        # Store result
        if nov_norm.size == 0:
            self.activation_frame = np.array([0.0])
        else:
            self.activation_frame = nov_norm

        return self.activation_frame, rms

    def _stft(self, audio_frame: np.ndarray) -> np.ndarray:
        """Compute STFT of current window buffer."""
        # Roll buffer and add new samples
        self._window_buffer = np.roll(self._window_buffer, -self.H)
        self._window_buffer[-self.H :] = audio_frame

        # Apply window and compute FFT
        windowed = self._window_buffer * self._hann_window
        X_frame = np.fft.rfft(windowed)

        return X_frame.reshape(-1, 1)

    def _spectrogram(self, X_frame: np.ndarray) -> np.ndarray:
        """Compute log-compressed spectrogram."""
        return np.log(1 + self.gamma * np.abs(X_frame))

    def _local_average(self, nov: np.ndarray) -> float:
        """Compute causal local average."""
        if len(nov) > 0:
            self._la_buffer = np.roll(self._la_buffer, -1)
            self._la_buffer[-1] = nov[0]

        return float(np.sum(self._la_buffer) / self.M)

    def _normalize(self, nov: np.ndarray, la: float) -> np.ndarray:
        """Subtract local average and half-wave rectify."""
        nov_norm = nov - la
        nov_norm[nov_norm < 0] = 0
        return nov_norm

    def get_peak_rms(self) -> float:
        """Get peak RMS level for silence detection."""
        return self.peak_rms

    def reset(self) -> None:
        """Reset all state."""
        self._window_buffer.fill(0)
        self._la_buffer.fill(0)
        self._Y_last.fill(0)
        self.activation_frame = np.array([0.0])
        self.peak_rms = 0.0
