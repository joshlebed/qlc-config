"""Benchmark script for testing PLP beat tracker with known-BPM files."""

import argparse
import json
import os
import time
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


def analyze_interval_distribution(
    beat_times: list[float],
    detected_bpm: float | None = None,
    tolerance: float = 0.15,  # 15% tolerance for "on beat"
) -> dict[str, Any]:
    """
    Analyze the distribution of beat intervals normalized to beat period.

    A perfect beat tracker would have all intervals at exactly 1.0 beat periods.
    This function measures how well intervals cluster at integer beat multiples.

    Args:
        beat_times: List of beat timestamps in seconds
        detected_bpm: BPM to use for normalization (if None, uses median interval)
        tolerance: Tolerance for considering an interval "on beat" (0.15 = ±15%)

    Returns:
        Dictionary with interval distribution metrics
    """
    if len(beat_times) < 2:
        return {
            "total_intervals": 0,
            "normalized_intervals": [],
            "on_1beat_pct": 0.0,
            "on_2beat_pct": 0.0,
            "half_beat_pct": 0.0,
            "interval_std_beats": 0.0,
            "histogram": {},
        }

    intervals_sec = np.diff(beat_times)

    # Determine beat period for normalization
    if detected_bpm and detected_bpm > 0:
        beat_period = 60.0 / detected_bpm
    else:
        # Use median interval as beat period estimate
        beat_period = float(np.median(intervals_sec))

    # Normalize intervals to beat periods
    normalized = intervals_sec / beat_period

    # Calculate distribution metrics
    total = len(normalized)

    # Count intervals at each beat multiple (within tolerance)
    on_1beat = np.sum((normalized >= 1.0 - tolerance) & (normalized <= 1.0 + tolerance))
    on_2beat = np.sum((normalized >= 2.0 - tolerance) & (normalized <= 2.0 + tolerance))
    half_beat = np.sum((normalized >= 0.5 - tolerance) & (normalized <= 0.5 + tolerance))
    on_3beat = np.sum((normalized >= 3.0 - tolerance) & (normalized <= 3.0 + tolerance))

    # Build histogram buckets (0.25 beat resolution)
    histogram: dict[str, int] = {}
    for bucket in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0]:
        bucket_tolerance = 0.125  # Half of 0.25 resolution
        count = int(
            np.sum(
                (normalized >= bucket - bucket_tolerance) & (normalized < bucket + bucket_tolerance)
            )
        )
        if count > 0:
            histogram[f"{bucket:.2f}"] = count

    # Count outliers (outside expected range)
    outliers = int(np.sum((normalized < 0.25) | (normalized > 4.0)))
    if outliers > 0:
        histogram["outliers"] = outliers

    # Calculate core quality (excluding outliers and long gaps)
    core_mask = (normalized >= 0.5) & (normalized <= 2.5)
    core_intervals = normalized[core_mask]
    core_on_1beat = np.sum(
        (core_intervals >= 1.0 - tolerance) & (core_intervals <= 1.0 + tolerance)
    )
    core_total = len(core_intervals)

    return {
        "total_intervals": total,
        "beat_period_ms": beat_period * 1000,
        "normalized_intervals": normalized.tolist(),
        "on_1beat_pct": 100 * on_1beat / total if total > 0 else 0.0,
        "on_2beat_pct": 100 * on_2beat / total if total > 0 else 0.0,
        "on_3beat_pct": 100 * on_3beat / total if total > 0 else 0.0,
        "half_beat_pct": 100 * half_beat / total if total > 0 else 0.0,
        "interval_mean_beats": float(np.mean(normalized)),
        "interval_std_beats": float(np.std(normalized)),
        # Core quality: 1-beat accuracy excluding long gaps
        "core_1beat_pct": 100 * core_on_1beat / core_total if core_total > 0 else 0.0,
        "core_std_beats": float(np.std(core_intervals)) if core_total > 0 else 0.0,
        "core_count": core_total,
        "histogram": histogram,
    }


def evaluate_ground_truth(
    detected_beats: list[float],
    ground_truth: list[float],
    tolerance_ms: float = 50.0,
) -> dict[str, Any]:
    """
    Compare detected beats against ground truth from test_data JSON.

    Args:
        detected_beats: List of detected beat times in seconds
        ground_truth: List of ground truth beat times from rekordbox
        tolerance_ms: Maximum allowed error for a true positive (default 50ms)

    Returns:
        Dict with precision, recall, F1, and timing error stats
    """
    if not detected_beats or not ground_truth:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "true_positives": 0,
            "false_positives": len(detected_beats),
            "missed_beats": len(ground_truth),
            "mean_timing_error_ms": 0.0,
            "max_timing_error_ms": 0.0,
            "std_timing_error_ms": 0.0,
        }

    tolerance_sec = tolerance_ms / 1000.0

    # Track which ground truth beats were matched
    gt_matched = [False] * len(ground_truth)
    true_positives = 0
    timing_errors: list[float] = []

    for detected in detected_beats:
        # Find closest unmatched ground truth beat
        best_idx = None
        best_error = float("inf")

        for i, gt in enumerate(ground_truth):
            if gt_matched[i]:
                continue  # Already matched
            error = abs(gt - detected)
            if error < best_error:
                best_error = error
                best_idx = i

        if best_idx is not None and best_error <= tolerance_sec:
            gt_matched[best_idx] = True
            true_positives += 1
            timing_errors.append(best_error * 1000)  # Convert to ms

    # Calculate metrics
    precision = true_positives / len(detected_beats) if detected_beats else 0.0
    recall = true_positives / len(ground_truth) if ground_truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    false_positives = len(detected_beats) - true_positives
    missed_beats = len(ground_truth) - true_positives

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "missed_beats": missed_beats,
        "mean_timing_error_ms": float(np.mean(timing_errors)) if timing_errors else 0.0,
        "max_timing_error_ms": float(max(timing_errors)) if timing_errors else 0.0,
        "std_timing_error_ms": float(np.std(timing_errors)) if timing_errors else 0.0,
    }


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
    source = FileAudioSource(file_path, block_size=BLOCK_SIZE, simulate_room=simulate_room)
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
    confidence_tracker = ConfidenceTracker()
    peak_picker = PeakPicker(
        samplerate=source.sr,
        hop_length=BLOCK_SIZE,
        tempo_max=bpm_max,
    )
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
        # Current simulated time for this frame (compute early for record_hit)
        current_time = frame_count * BLOCK_SIZE / source.sr

        # Onset envelope - now returns (onset_array, rms)
        onset_result, _rms = onset_tracker.process(chunk)
        onset_val = float(onset_result[0])
        tempogram.update(onset_val)
        bpm, strength = tempogram.estimate_tempo()

        # Default values for when tempo is not valid
        pulse = 0.0
        beat_detected = False
        confidence = 0.0

        if bpm > 0 and strength > 0.1:
            bpm_estimates.append(bpm)
            pulse = plp.update(bpm, strength, onset_val)

            # Check for raw peak (pass onset and phase for combined detection)
            beat_detected = peak_picker.update(
                pulse, bpm, onset_strength=onset_val, phase=plp.phase
            )
            if beat_detected:
                raw_beat_count += 1

            # Update confidence (energy-based model)
            confidence = confidence_tracker.update(pulse, bpm, strength, onset_val)
            confidence_samples.append(confidence)

            if debug and beat_detected:
                print(f"Frame {frame_count}: beat detected, conf={confidence:.3f}, bpm={bpm:.1f}")

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
                "onset": float(onset_val),
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
                "conf_onset": conf_components["onset"],
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
        intervals = np.array([])

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

    # Analyze interval distribution (normalized to beat period)
    interval_analysis = analyze_interval_distribution(beat_times, detected_bpm=detected_bpm)

    # Load ground truth if JSON file exists
    gt_beats: list[float] = []
    json_path = file_path.rsplit(".", 1)[0] + ".json"
    if os.path.exists(json_path):
        with open(json_path) as f:
            ground_truth_data = json.load(f)
        gt_beats = ground_truth_data.get("beats", [])

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
        "interval_analysis": interval_analysis,
    }

    if expected_bpm is not None:
        results["expected_bpm"] = expected_bpm
        results["bpm_error"] = abs(detected_bpm - expected_bpm)
        results["bpm_error_pct"] = abs(detected_bpm - expected_bpm) / expected_bpm * 100

    # Evaluate against ground truth if available
    if gt_beats:
        gt_eval = evaluate_ground_truth(beat_times, gt_beats)
        results["ground_truth_eval"] = gt_eval

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

        # Interval distribution analysis
        if interval_analysis["total_intervals"] > 0:
            print("")
            print("Interval Distribution (normalized to beat period):")
            print(
                f"  1-beat: {interval_analysis['on_1beat_pct']:.1f}% | "
                f"2-beat: {interval_analysis['on_2beat_pct']:.1f}% | "
                f"half-beat: {interval_analysis['half_beat_pct']:.1f}%"
            )
            print(
                f"  Mean: {interval_analysis['interval_mean_beats']:.2f} beats | "
                f"Std: {interval_analysis['interval_std_beats']:.3f} beats"
            )
            # Core quality (excluding outliers) - this is the key metric
            core_std_ms = interval_analysis["core_std_beats"] * interval_analysis["beat_period_ms"]
            print(
                f"  Core quality (0.5-2.5 beats only): "
                f"{interval_analysis['core_1beat_pct']:.1f}% on-beat, "
                f"std={core_std_ms:.1f}ms"
            )
            # Show histogram as ASCII bar chart
            hist = interval_analysis["histogram"]
            if hist:
                max_count = max(hist.values()) if hist else 1
                print("  Histogram:")
                for bucket in sorted(
                    hist.keys(), key=lambda x: float(x) if x != "outliers" else 99
                ):
                    count = hist[bucket]
                    bar_len = int(30 * count / max_count)
                    pct = 100 * count / interval_analysis["total_intervals"]
                    print(f"    {bucket:>7}: {'█' * bar_len} {count} ({pct:.1f}%)")

        # Ground truth evaluation
        if "ground_truth_eval" in results:
            gt = results["ground_truth_eval"]
            print("")
            print("Ground Truth Evaluation:")
            print(
                f"  Precision: {gt['precision']:.1%} "
                f"({gt['true_positives']} TP / {len(beat_times)} detected)"
            )
            print(
                f"  Recall: {gt['recall']:.1%} "
                f"({gt['true_positives']} TP / {len(gt_beats)} ground truth)"
            )
            print(f"  F1 Score: {gt['f1']:.1%}")
            print(f"  False Positives: {gt['false_positives']}")
            print(f"  Missed Beats: {gt['missed_beats']}")
            if gt["mean_timing_error_ms"] > 0:
                print(
                    f"  Mean Timing Error: {gt['mean_timing_error_ms']:.1f} ms "
                    f"(max: {gt['max_timing_error_ms']:.1f} ms)"
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
        "--record",
        "-r",
        type=str,
        metavar="FILE",
        help="Save frame data to JSONL file for visualization comparison",
    )
    parser.add_argument(
        "--simulate-room",
        "-s",
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
