"""Lock state machine for beat output gating."""

import time
from enum import Enum


class LockState(Enum):
    """Beat tracking lock states."""

    SEARCHING = "SEARCHING"  # Confidence low, do not emit beats
    LOCKED = "LOCKED"  # Confidence stable, emit beat events
    HOLDOVER = "HOLDOVER"  # Brief confidence dip, extrapolate beats


class BeatStateMachine:
    """
    State machine for beat output control.

    Manages transitions between SEARCHING, LOCKED, and HOLDOVER states
    based on confidence signal.
    """

    def __init__(
        self,
        lock_threshold: float = 0.35,  # Lowered to help tracks with subtle rhythms lock faster
        unlock_threshold: float = 0.35,  # Raised to enter HOLDOVER sooner during breakdowns
        lock_beats: int = 3,  # Consecutive good beats needed to lock
        holdover_beats: int = 8,  # Beats to extrapolate during breakdown before stopping
        beat_tolerance_ms: float = 50.0,  # Tolerance for beat alignment
    ):
        self.lock_threshold = lock_threshold
        self.unlock_threshold = unlock_threshold
        self.lock_beats = lock_beats
        self.holdover_beats = holdover_beats
        self.beat_tolerance = beat_tolerance_ms / 1000.0

        # State
        self.state = LockState.SEARCHING
        self.consecutive_good: int = 0
        self.consecutive_bad: int = 0
        self.locked_bpm: float = 0.0
        self.last_beat_time: float = 0.0
        self.next_expected_beat: float = 0.0  # For phase-locked prediction
        self.holdover_remaining: int = 0

    def update(
        self,
        confidence: float,
        bpm: float,
        beat_detected: bool,
        current_time: float | None = None,
    ) -> tuple[LockState, bool]:
        """
        Update state machine and determine if beat should be emitted.

        Args:
            confidence: Current confidence value (0-1)
            bpm: Current tempo estimate (BPM)
            beat_detected: Whether a beat was detected this frame
            current_time: Optional timestamp (uses time.time() if not provided)

        Returns:
            (current_state, should_emit): State and whether to emit beat event
        """
        should_emit = False
        now = current_time if current_time is not None else time.time()

        if self.state == LockState.SEARCHING:
            # Count consecutive BEATS with good confidence (not consecutive frames)
            if beat_detected:
                if confidence >= self.lock_threshold:
                    self.consecutive_good += 1
                    if self.consecutive_good >= self.lock_beats:
                        # Transition to LOCKED
                        self.state = LockState.LOCKED
                        self.locked_bpm = bpm
                        self.consecutive_bad = 0
                        should_emit = True
                        self.last_beat_time = now
                        # Initialize expected beat for phase locking
                        beat_period = 60.0 / bpm
                        self.next_expected_beat = now + beat_period
                else:
                    # Beat detected but confidence too low - reset counter
                    self.consecutive_good = 0

        elif self.state == LockState.LOCKED:
            if confidence >= self.unlock_threshold:
                self.consecutive_bad = 0
                beat_period = 60.0 / self.locked_bpm
                min_interval = beat_period * 0.7  # 70% of beat period

                if beat_detected:
                    # Only emit if enough time since last beat
                    if now - self.last_beat_time >= min_interval:
                        should_emit = True
                        self.last_beat_time = now
                    # Slowly adjust BPM toward detected (even if beat not emitted)
                    self.locked_bpm = self.locked_bpm * 0.95 + bpm * 0.05
            else:
                self.consecutive_bad += 1
                if self.consecutive_bad >= 2:
                    # Transition to HOLDOVER
                    self.state = LockState.HOLDOVER
                    self.holdover_remaining = self.holdover_beats

        elif self.state == LockState.HOLDOVER:
            if confidence >= self.lock_threshold:
                # Back to LOCKED
                self.state = LockState.LOCKED
                self.consecutive_bad = 0
                if beat_detected:
                    # Only emit if enough time since last beat (regardless of state)
                    beat_period = 60.0 / self.locked_bpm if self.locked_bpm > 0 else 0.5
                    min_interval = beat_period * 0.7  # 70% of beat period
                    if now - self.last_beat_time >= min_interval:
                        should_emit = True
                        self.last_beat_time = now
            else:
                # Extrapolate beats using last known BPM
                if self.locked_bpm > 0:
                    beat_period = 60.0 / self.locked_bpm
                    if now - self.last_beat_time >= beat_period:
                        should_emit = True
                        self.last_beat_time = now
                        self.holdover_remaining -= 1

                if self.holdover_remaining <= 0:
                    # Back to SEARCHING
                    self.state = LockState.SEARCHING
                    self.consecutive_good = 0
                    self.locked_bpm = 0.0

        return self.state, should_emit

    def get_state(self) -> LockState:
        """Get current state."""
        return self.state

    def get_locked_bpm(self) -> float:
        """Get locked BPM (0 if not locked)."""
        return self.locked_bpm if self.state != LockState.SEARCHING else 0.0

    def get_debug_info(self) -> dict:
        """Get state machine internals for debugging."""
        return {
            "consecutive_good": self.consecutive_good,
            "consecutive_bad": self.consecutive_bad,
            "holdover_remaining": self.holdover_remaining,
            "locked_bpm": self.locked_bpm,
        }

    def reset(self) -> None:
        """Reset state machine."""
        self.state = LockState.SEARCHING
        self.consecutive_good = 0
        self.consecutive_bad = 0
        self.locked_bpm = 0.0
        self.last_beat_time = 0.0
        self.next_expected_beat = 0.0
        self.holdover_remaining = 0
