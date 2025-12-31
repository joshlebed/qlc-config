"""Benchmark script for testing PLP beat tracker with known-BPM files."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from plp_beat_service.audio import BLOCK_SIZE
from plp_beat_service.confidence import ConfidenceTracker
from plp_beat_service.file_source import FileAudioSource
from plp_beat_service.onset import OnsetEnvelopeTracker
from plp_beat_service.peaks import PeakPicker
from plp_beat_service.plp import PLPTracker
from plp_beat_service.state import BeatStateMachine
from plp_beat_service.tempogram import StreamingTempogram


def benchmark(
    file_path: str,
    expected_bpm: float | None = None,
    bpm_min: int = 115,
    bpm_max: int = 165,
    verbose: bool = True,
    debug: bool = False,
    record_path: str | None = None,
    simulate_room: bool = False,
) -> dict[str, Any]:
    """
    Run PLP pipeline on audio file and report metrics.

    Args:
        file_path: Path to audio file
        expected_bpm: Known BPM for accuracy calculation (optional)
        bpm_min: Minimum tempo to detect
        bpm_max: Maximum tempo to detect
        verbose: Print progress
        debug: Print per-frame debug info
        record_path: Path to save recording (JSONL format) for visualization
        simulate_room: Apply room acoustics simulation for mic-like behavior

    Returns:
        Dictionary with benchmark results
    """
    # Load audio
    source = FileAudioSource(file_path, simulate_room=simulate_room)
    if verbose:
        print(f"Loaded: {file_path}")
        print(f"Duration: {source.duration:.1f}s")
        print("Processing...")

    # Initialize pipeline
    # Note: hop_length must match the actual block size we're processing
    onset_tracker = OnsetEnvelopeTracker(samplerate=source.sr, hop_length=BLOCK_SIZE)
    tempogram = StreamingTempogram(
        samplerate=source.sr,
        hop_length=BLOCK_SIZE,
        tempo_min=bpm_min,
        tempo_max=bpm_max,
    )
    plp = PLPTracker(
        samplerate=source.sr,
        hop_length=BLOCK_SIZE,
        tempo_min=bpm_min,
        tempo_max=bpm_max,
    )
    peak_picker = PeakPicker(
        samplerate=source.sr,
        hop_length=BLOCK_SIZE,
        tempo_max=bpm_max,
    )
    confidence_tracker = ConfidenceTracker()
    state_machine = BeatStateMachine()

    # Open recording file if requested
    record_file = None
    if record_path:
        record_file = open(record_path, "w")
        # Write header as first line
        header = {
            "type": "header",
            "version": 1,
            "file": file_path,
            "expected_bpm": expected_bpm,
            "bpm_min": bpm_min,
            "bpm_max": bpm_max,
            "samplerate": source.sr,
            "block_size": BLOCK_SIZE,
            "duration": source.duration,
        }
        record_file.write(json.dumps(header) + "\n")
        if verbose:
            print(f"Recording to: {record_path}")

    # Process
    start_time = time.time()
    bpm_estimates: list[float] = []
    beat_times: list[float] = []  # For jitter calculation
    raw_beat_count = 0  # Peaks before state machine filtering
    frame_count = 0
    beat_count = 0
    state_counts: dict[str, int] = {"SEARCHING": 0, "LOCKED": 0, "HOLDOVER": 0}
    confidence_samples: list[float] = []  # For debug

    for chunk in source:
        onset = onset_tracker.process(chunk)
        tempogram.update(onset[0])
        bpm, strength = tempogram.estimate_tempo()

        # Default values for when tempo is not valid
        pulse = 0.0
        beat_detected = False
        confidence = 0.0

        if bpm > 0 and strength > 0.1:
            bpm_estimates.append(bpm)
            pulse = plp.update(bpm, strength, onset[0])

            # Check for raw peak (pass onset and phase for combined detection)
            beat_detected = peak_picker.update(
                pulse, bpm, onset_strength=onset[0], phase=plp.phase
            )
            if beat_detected:
                raw_beat_count += 1

            # Update confidence
            confidence = confidence_tracker.update(pulse, bpm, strength)
            confidence_samples.append(confidence)

            if debug and beat_detected:
                print(
                    f"Frame {frame_count}: beat detected, conf={confidence:.3f}, bpm={bpm:.1f}"
                )

        # Current simulated time for this frame
        current_time = frame_count * BLOCK_SIZE / source.sr

        # State machine decides if we should emit a beat
        state, should_emit = state_machine.update(
            confidence, bpm, beat_detected, current_time=current_time
        )
        state_counts[state.value] += 1

        if debug and should_emit:
            print(f"Frame {frame_count}: EMITTING BEAT (state={state.value})")

        if should_emit:
            beat_times.append(current_time)
            beat_count += 1

        # Record frame data if requested (same format as live debug server)
        if record_file:
            locked_bpm = state_machine.get_locked_bpm()
            conf_components = confidence_tracker.get_components()
            state_debug = state_machine.get_debug_info()
            frame_data = {
                "type": "frame",
                "seq": frame_count,
                "ts": current_time,
                "onset": float(onset[0]),
                "pulse": float(pulse),
                "phase": float(plp.phase),
                "bpm": float(locked_bpm),
                "bpm_raw": float(bpm),
                "confidence": float(confidence),
                "beat": should_emit,
                "state": state.value,
                "beats": beat_count,
                "conf_pulse": conf_components["pulse"],
                "conf_tempo": conf_components["tempo"],
                "conf_raw": conf_components["raw"],
                "good_count": state_debug["consecutive_good"],
                "bad_count": state_debug["consecutive_bad"],
            }
            record_file.write(json.dumps(frame_data) + "\n")

        frame_count += 1

    # Calculate jitter from beat intervals
    if len(beat_times) > 1:
        intervals = np.diff(beat_times) * 1000  # Convert to ms
        jitter_ms = float(np.std(intervals))
        mean_interval_ms = float(np.mean(intervals))
    else:
        jitter_ms = 0.0
        mean_interval_ms = 0.0

    elapsed = time.time() - start_time

    # Calculate metrics
    if len(bpm_estimates) > 0:
        # Use median of last N estimates for final BPM
        final_estimates = bpm_estimates[-100:] if len(bpm_estimates) > 100 else bpm_estimates
        detected_bpm = float(np.median(final_estimates))
        bpm_std = float(np.std(final_estimates))
    else:
        detected_bpm = 0.0
        bpm_std = 0.0

    # Find lock time (first 10 consecutive estimates within ±2 BPM of final)
    lock_frame: int | None = None
    if detected_bpm > 0:
        consecutive = 0
        for i, bpm in enumerate(bpm_estimates):
            if abs(bpm - detected_bpm) < 2.0:
                consecutive += 1
                if consecutive >= 10:
                    lock_frame = i - 9
                    break
            else:
                consecutive = 0

    lock_time = (lock_frame * 2048 / source.sr) if lock_frame else None

    # Close recording file
    if record_file:
        # Write summary as last line
        summary = {
            "type": "summary",
            "total_frames": frame_count,
            "total_beats": beat_count,
            "detected_bpm": detected_bpm,
            "processing_time_s": elapsed,
        }
        record_file.write(json.dumps(summary) + "\n")
        record_file.close()
        if verbose:
            print(f"Recording saved: {record_path}")

    # Calculate expected beats based on detected BPM
    expected_beats = int(source.duration * detected_bpm / 60) if detected_bpm > 0 else 0
    emitted_beat_count = len(beat_times)

    results: dict[str, Any] = {
        "file": file_path,
        "duration_s": source.duration,
        "processing_time_s": elapsed,
        "speed_factor": source.duration / elapsed,
        "detected_bpm": detected_bpm,
        "bpm_std": bpm_std,
        "lock_time_s": lock_time,
        "total_frames": frame_count,
        "valid_estimates": len(bpm_estimates),
        "beat_count": emitted_beat_count,
        "raw_beat_count": raw_beat_count,
        "expected_beats": expected_beats,
        "jitter_ms": jitter_ms,
        "mean_interval_ms": mean_interval_ms,
        "state_counts": state_counts,
    }

    if expected_bpm is not None:
        results["expected_bpm"] = expected_bpm
        results["bpm_error"] = abs(detected_bpm - expected_bpm)
        results["bpm_error_pct"] = abs(detected_bpm - expected_bpm) / expected_bpm * 100

    # Print results
    if verbose:
        print(f"\n{'=' * 50}")
        print("BENCHMARK RESULTS")
        print(f"{'=' * 50}")
        print(f"Processing speed: {results['speed_factor']:.1f}x realtime")
        print(f"Detected BPM: {detected_bpm:.1f} (±{bpm_std:.1f})")
        if expected_bpm:
            print(f"Expected BPM: {expected_bpm}")
            print(f"Error: {results['bpm_error']:.1f} BPM ({results['bpm_error_pct']:.1f}%)")
        if lock_time:
            print(f"Lock time: {lock_time:.1f}s")
        else:
            print("Lock time: Never locked")
        print("")
        print(
            f"Beats: {emitted_beat_count} emitted, {raw_beat_count} raw peaks (expected ~{expected_beats})"
        )
        print(f"Jitter: {jitter_ms:.1f} ms (target <15 ms)")
        print(f"Mean interval: {mean_interval_ms:.1f} ms")
        print("")
        locked_pct = 100 * state_counts["LOCKED"] / frame_count if frame_count > 0 else 0
        print(
            f"State: {locked_pct:.1f}% LOCKED, {state_counts['SEARCHING']} SEARCHING, {state_counts['HOLDOVER']} HOLDOVER"
        )
        if confidence_samples:
            print(
                f"Confidence: min={min(confidence_samples):.3f}, max={max(confidence_samples):.3f}, "
                f"mean={np.mean(confidence_samples):.3f}"
            )
        print(f"{'=' * 50}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark PLP beat tracker",
        epilog="""
Examples:
  # Basic benchmark
  python -m plp_beat_service.benchmark track.mp3 -e 140

  # Record for visualization
  python -m plp_beat_service.benchmark track.mp3 -e 140 --record track_benchmark.jsonl

  # View recording in compare.html (open in browser)
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="Audio file to process")
    parser.add_argument("--expected-bpm", "-e", type=float, help="Known BPM for accuracy check")
    parser.add_argument("--bpm-min", type=int, default=115, help="Minimum BPM (default: 115)")
    parser.add_argument("--bpm-max", type=int, default=165, help="Maximum BPM (default: 165)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress output")
    parser.add_argument("--debug", "-d", action="store_true", help="Print debug info")
    parser.add_argument(
        "--record", "-r",
        type=str,
        metavar="FILE",
        help="Save frame data to JSONL file for visualization comparison",
    )
    parser.add_argument(
        "--simulate-room", "-s",
        action="store_true",
        help="Simulate room acoustics (lowpass + compression + level reduction) for mic-like behavior",
    )

    args = parser.parse_args()

    benchmark(
        args.file,
        expected_bpm=args.expected_bpm,
        bpm_min=args.bpm_min,
        bpm_max=args.bpm_max,
        verbose=not args.quiet,
        debug=args.debug,
        record_path=args.record,
        simulate_room=args.simulate_room,
    )


if __name__ == "__main__":
    main()
