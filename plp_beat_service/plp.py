"""Predominant Local Pulse (PLP) computation with kernel overlap-add."""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Kernel:
    """Sinusoidal kernel for PLP pulse synthesis."""

    tempo: float  # BPM
    omega: float  # Frequency in cycles per frame
    phase: float  # Phase offset from DFT
    t_start: int  # Start frame index
    t_end: int  # End frame index
    x: np.ndarray  # The kernel waveform

    @classmethod
    def from_tempogram(
        cls,
        N: int,
        framerate: float,
        Theta: np.ndarray,
        X: np.ndarray,
        window: np.ndarray,
    ) -> "Kernel":
        """
        Create kernel from tempogram output.

        Args:
            N: Kernel length (same as tempogram window)
            framerate: Frames per second
            Theta: Tempo candidates (BPM array)
            X: Complex DFT coefficients
            window: Hann window

        Returns:
            Kernel with synthesized cosine waveform
        """
        # Find peak tempo
        magnitudes = np.abs(X)
        k = int(np.argmax(magnitudes))
        tempo = float(Theta[k])

        # Compute kernel parameters
        omega = (tempo / 60) / framerate  # Cycles per frame
        c = X[k]  # Complex coefficient
        # Phase from DFT with half-cycle offset for beat alignment
        # Without +0.5, peaks align with offbeats instead of downbeats
        phase = -np.angle(c) / (2 * np.pi) + 0.5

        # Synthesize kernel
        t = np.arange(N)
        x = window * np.cos(2 * np.pi * (t * omega - phase))

        return cls(
            tempo=tempo,
            omega=omega,
            phase=phase,
            t_start=0,
            t_end=N,
            x=x,
        )


@dataclass
class PLPTracker:
    """
    Streaming PLP pulse curve computation with kernel overlap-add.

    Reference: ../real_time_plp/realtimeplp.py PredominantLocalPulse class
    """

    samplerate: int = 44100
    hop_length: int = 512
    win_length_sec: float = 6.0
    tempo_min: int = 115
    tempo_max: int = 165
    lookahead: int = 0  # Frames to look ahead for beat detection

    # Derived attributes
    framerate: float = field(init=False)
    win_length: int = field(init=False)
    Theta: np.ndarray = field(init=False)

    # State
    _pulse_buffer: np.ndarray = field(init=False, repr=False)
    _t: np.ndarray = field(init=False, repr=False)
    _cursor: int = field(init=False)
    _window: np.ndarray = field(init=False, repr=False)
    _max_window_sum: float = field(init=False)

    current_tempo: float = field(default=0.0, init=False)
    current_kernel: Kernel | None = field(default=None, init=False)
    stability: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.framerate = self.samplerate / self.hop_length
        self.win_length = round(self.win_length_sec * self.framerate)
        self.Theta = np.arange(self.tempo_min, self.tempo_max + 1, 1)

        self._pulse_buffer = np.zeros(self.win_length)
        self._t = np.arange(self.win_length) / self.framerate
        self._cursor = (self.win_length // 2) + self.lookahead
        self._window = np.hanning(self.win_length)
        self._max_window_sum = float(np.sum(self._window))

    def update(self, Theta: np.ndarray, X: np.ndarray) -> float:
        """
        Update PLP pulse buffer with new tempogram frame.

        Args:
            Theta: Tempo candidates (BPM array)
            X: Complex DFT coefficients from tempogram

        Returns:
            Current pulse value at cursor position
        """
        # Roll buffer and zero new positions
        self._pulse_buffer = np.roll(self._pulse_buffer, -1)
        self._pulse_buffer[-1] = 0

        # Create and add kernel
        kernel = Kernel.from_tempogram(
            N=self.win_length,
            framerate=self.framerate,
            Theta=Theta,
            X=X,
            window=self._window,
        )

        # Overlap-add kernel to buffer
        self._pulse_buffer = self._pulse_buffer + kernel.x

        # Update state
        self.current_tempo = kernel.tempo
        self.current_kernel = kernel

        # Return normalized pulse at cursor
        return self.get_pulse_at_cursor()

    def get_pulse_at_cursor(self) -> float:
        """Get normalized pulse value at cursor position."""
        if self._max_window_sum > 0:
            return float(self._pulse_buffer[self._cursor] / self._max_window_sum)
        return 0.0

    def get_normalized_buffer(self) -> np.ndarray:
        """Get normalized pulse buffer (values in [-1, 1])."""
        if self._max_window_sum > 0:
            return self._pulse_buffer / self._max_window_sum
        return self._pulse_buffer

    @property
    def phase(self) -> float:
        """Get current phase estimate (for compatibility)."""
        # Approximate phase from cursor position relative to peak
        if self.current_kernel is None:
            return 0.0
        return float(self.current_kernel.phase * 2 * np.pi)

    def reset(self) -> None:
        """Reset PLP state."""
        self._pulse_buffer.fill(0)
        self.current_tempo = 0.0
        self.current_kernel = None
        self.stability = 0.0
