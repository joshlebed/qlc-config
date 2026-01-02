"""Streaming onset strength envelope computation."""

from collections import deque

import librosa
import numpy as np
from scipy import signal


class OnsetEnvelopeTracker:
    """
    Computes onset strength envelope in streaming mode.

    Maintains state across frames for continuous processing.
    """

    def __init__(
        self,
        samplerate: int = 44100,
        hop_length: int = 512,
        n_fft: int = 2048,
        n_mels: int = 128,
    ):
        self.samplerate = samplerate
        self.hop_length = hop_length
        self.n_fft = n_fft
        self.n_mels = n_mels

        # Create mel filterbank
        self.mel_basis = self._create_mel_filterbank()

        # State for streaming
        self.prev_mel: np.ndarray | None = None
        self.onset_history: deque[float] = deque(maxlen=512)
        self.peak_rms: float = 0.0  # Track peak RMS for silence detection

        # Hann window for STFT
        self.window = signal.windows.hann(n_fft)

    def _create_mel_filterbank(self) -> np.ndarray:
        """Create mel filterbank matrix."""
        return librosa.filters.mel(
            sr=self.samplerate,
            n_fft=self.n_fft,
            n_mels=self.n_mels,
            fmin=30,
            fmax=8000,
        )

    def process(self, samples: np.ndarray) -> tuple[np.ndarray, float]:
        """
        Process audio samples and return onset strength values and RMS.

        Args:
            samples: Mono audio samples (float32)

        Returns:
            Tuple of (onset strength array, RMS level)
        """
        # Pad to n_fft if needed
        if len(samples) < self.n_fft:
            samples = np.pad(samples, (0, self.n_fft - len(samples)))

        # Compute STFT magnitude
        stft = np.fft.rfft(samples * self.window)
        mag = np.abs(stft)

        # Apply mel filterbank
        mel_spec = np.dot(self.mel_basis, mag**2)
        mel_spec = np.log1p(mel_spec)  # Log compression

        # Compute spectral flux (onset strength)
        if self.prev_mel is not None:
            # Half-wave rectified difference
            diff = mel_spec - self.prev_mel
            onset_strength = np.sum(np.maximum(0, diff))
        else:
            onset_strength = 0.0

        self.prev_mel = mel_spec.copy()
        self.onset_history.append(onset_strength)

        # Compute RMS for absolute energy gate
        rms = float(np.sqrt(np.mean(samples**2)))
        # Track peak with slow decay (0.9995 per frame at ~86 fps = ~15s half-life)
        self.peak_rms = max(self.peak_rms * 0.9995, rms)

        return np.array([onset_strength]), rms

    def get_envelope(self, n_frames: int = 64) -> np.ndarray:
        """Get recent onset envelope for tempogram computation."""
        hist = list(self.onset_history)
        if len(hist) < n_frames:
            # Pad with zeros at start
            hist = [0.0] * (n_frames - len(hist)) + hist
        return np.array(hist[-n_frames:])

    def get_peak_rms(self) -> float:
        """Get peak RMS level (for silence detection)."""
        return self.peak_rms

    def reset(self) -> None:
        """Reset state (e.g., after long silence)."""
        self.prev_mel = None
        self.onset_history.clear()
        self.peak_rms = 0.0
