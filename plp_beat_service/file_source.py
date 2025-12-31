"""File-based audio source for testing and benchmarking."""

import librosa
import numpy as np
from scipy import signal


class FileAudioSource:
    """
    Load audio file and yield chunks for processing.

    Processes faster than realtime for rapid testing.
    """

    def __init__(
        self,
        file_path: str,
        block_size: int = 2048,
        samplerate: int = 44100,
        simulate_room: bool = False,
    ):
        """
        Load audio file.

        Args:
            file_path: Path to audio file (WAV, MP3, etc.)
            block_size: Samples per chunk (default 2048)
            samplerate: Target sample rate (default 44100)
            simulate_room: Apply filtering to simulate room acoustics (mic playback)
        """
        self.samples, self.sr = librosa.load(file_path, sr=samplerate, mono=True)
        self.block_size = block_size
        self.position = 0
        self.duration = len(self.samples) / self.sr

        if simulate_room:
            # Simulate room acoustics: lowpass filter + soft compression + level reduction
            # This makes file-based testing produce similar results to mic-based testing

            # 1. Lowpass at 4kHz to simulate speaker/room response
            nyq = samplerate / 2
            cutoff = 4000 / nyq
            b, a = signal.butter(2, cutoff, btype='low')
            self.samples = signal.filtfilt(b, a, self.samples)

            # 2. Soft compression to reduce transient peaks (simulates room reverb)
            self.samples = np.tanh(self.samples * 2) / 2

            # 3. Reduce level to match typical mic input (~0.01-0.02 RMS vs 0.3 for files)
            # Target RMS around 0.015 to match mic levels
            current_rms = np.sqrt(np.mean(self.samples**2))
            target_rms = 0.015
            if current_rms > 0:
                self.samples = self.samples * (target_rms / current_rms)

    def __iter__(self) -> "FileAudioSource":
        self.position = 0
        return self

    def __next__(self) -> np.ndarray:
        if self.position >= len(self.samples):
            raise StopIteration
        end = min(self.position + self.block_size, len(self.samples))
        chunk = self.samples[self.position : end]
        self.position += self.block_size
        # Pad last chunk if needed
        if len(chunk) < self.block_size:
            chunk = np.pad(chunk, (0, self.block_size - len(chunk)))
        return chunk.astype(np.float32)

    def reset(self) -> None:
        """Reset to beginning of file."""
        self.position = 0
