# Beat Detection System

Technical documentation for the beat-to-MIDI system in `beat_to_midi.py`.

## Overview

The beat detection system converts audio input into MIDI clock or note signals for driving QLC+ lighting effects. It's designed for house/techno music in the 100-180 BPM range.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Audio Input │────▶│ Kick Filter │────▶│   aubio     │────▶│    PLL      │────▶ MIDI Out
│ (mic/file)  │     │ (optional)  │     │   onset     │     │ (phase lock)│
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Components

| Component | Class | Purpose |
|-----------|-------|---------|
| Kick Filter | `KickFilter` | Bandpass filter (30-200 Hz) to emphasize kick drums |
| Beat Detector | `BeatDetector` | aubio onset detection with debouncing |
| Phase-Locked Loop | `PhaseLockLoop` | Stabilizes tempo, rejects spurious detections |
| MIDI Output | `MIDIOutput` | Virtual MIDI port for clock/notes |

## Phase-Locked Loop (PLL)

The PLL is the core of the system. It maintains stable tempo tracking despite noisy onset detection.

### State Machine

```
                    ┌──────────────┐
                    │  SEARCHING   │◀─────────────────────┐
                    │  (BPM = 0)   │                      │
                    └──────┬───────┘                      │
                           │ 4+ valid intervals          │
                           ▼                              │
                    ┌──────────────┐                      │
                    │   LOCKING    │                      │
                    │ (building    │──────────────────────┤
                    │  confidence) │  tempo change or     │
                    └──────┬───────┘  too many rejections │
                           │ 6 consistent beats           │
                           ▼                              │
                    ┌──────────────┐                      │
                    │   LOCKED     │──────────────────────┘
                    │ (outputting  │  timeout, tempo change,
                    │  MIDI)       │  or lost confidence
                    └──────────────┘
```

### Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MIN_BPM` | 100 | Minimum valid BPM (intervals > 600ms rejected) |
| `MAX_BPM` | 180 | Maximum valid BPM (intervals < 333ms rejected) |
| `BEATS_TO_LOCK` | 6 | Consecutive in-phase beats needed to lock |
| `PHASE_TOLERANCE` | 0.30 | Accept beats within 30% of expected phase |
| `BPM_TOLERANCE` | 0.15 | 15% BPM variation allowed when locked |
| `BEAT_TIMEOUT_BEATS` | 6 | Lose lock after this many missed beats |
| `TEMPO_CHANGE_THRESHOLD` | 0.25 | 25% BPM change triggers reset |
| `TEMPO_CHANGE_BEATS` | 5 | Consecutive different-tempo beats to trigger reset |

### Tempo Tracking

The PLL uses two mechanisms to track tempo:

1. **Interval-based median tracking**: Stores recent beat intervals and uses the median for robustness against outliers.

2. **Drift correction**: Monitors phase errors over time. If 75%+ of recent errors are biased in the same direction, applies a small BPM correction (up to 1% per cycle).

## Known Issues and Solutions

### Issue: Spurious Detections Causing Lock Loss

**Symptom**: System loses lock after detecting a beat with an invalid interval (e.g., 220 BPM when locked at 152 BPM).

**Root Cause**: The tempo change detection was triggering on spurious detections with invalid intervals.

**Solution**: Only check for tempo changes when the interval is valid (within MIN_BPM to MAX_BPM range):
```python
# Check for tempo change - ONLY for valid intervals (not spurious detections)
if valid_interval and instant_bpm > 0 and self.bpm > 0:
    bpm_diff = abs(instant_bpm - self.bpm) / self.bpm
    # ...
```

Also reset `tempo_change_count` when transitioning to LOCKED state.

### Issue: BPM Converges 1-2% Away from Actual Tempo

**Symptom**: Track is 155 BPM but system stabilizes at 152 BPM.

**Root Cause**:
1. Drift correction was too strict (required ALL phase errors to be biased)
2. Tempo update blending was too conservative (80% old, 20% new)

**Solution**:
1. Made drift correction trigger when 75% of errors are biased (not 100%)
2. Increased drift correction strength (10% of drift per cycle, max 1% adjustment)
3. Made tempo blending adaptive based on number of intervals

### Issue: aubio Onset Detection Has Inherent Jitter

**Symptom**: Even with a perfectly steady track, detected intervals vary by 2-3%.

**Root Cause**: This is inherent to onset detection - different kicks have slightly different attack characteristics.

**Mitigation**:
- Use median of intervals (not mean) for robustness
- Only accept intervals within 10% of expected BPM for tempo updates
- Use phase tolerance of 30% to accept slightly off-phase beats

## Testing

### File Playback Mode

Test with audio files for reproducible results:

```bash
# Convert MP3 to WAV (required format)
ffmpeg -i track.mp3 -ar 44100 -ac 1 track.wav

# Run test
make beat-file FILE=track.wav

# Or directly
uv run python beat_to_midi.py --no-filter --file track.wav
```

### Debug Mode

Shows aubio's raw BPM estimates and rejection reasons:

```bash
make beat-debug

# With file
uv run python beat_to_midi.py --no-filter --debug --file track.wav
```

### Key Metrics to Watch

| Metric | Good Value | Concerning |
|--------|------------|------------|
| Acceptance rate | >95% | <90% |
| Lock loss events | 0 per track | >1 per track |
| BPM accuracy | Within 2% | >3% off |
| Time to lock | <15 beats | >30 beats |

### Test Commands

```bash
# Check milestone beats
uv run python beat_to_midi.py --no-filter --file track.wav 2>&1 | \
  grep -E "LOCKED at|Beat.*(100|200|300) |LOST LOCK"

# Check final stats
uv run python beat_to_midi.py --no-filter --file track.wav 2>&1 | tail -10
```

## Tuning Guide

### For Faster Tempo Convergence

Increase drift correction aggressiveness in `apply_drift_correction()`:
```python
correction = mean_error / self.beat_period() * 0.15  # was 0.10
correction = np.clip(correction, -0.02, 0.02)  # was 0.01
```

**Risk**: May cause oscillation if detection is noisy.

### For More Stable Lock

Increase phase tolerance and reduce tempo update blending:
```python
PHASE_TOLERANCE = 0.35  # was 0.30
blend = min(0.20, 0.05 + 0.01 * len(valid))  # was 0.30 max
```

**Risk**: Slower convergence to actual tempo.

### For Faster Tempo Change Detection

Reduce the threshold and beat count:
```python
TEMPO_CHANGE_THRESHOLD = 0.20  # was 0.25
TEMPO_CHANGE_BEATS = 3  # was 5
```

**Risk**: May false-trigger on detection noise.

### For Different Music Genres

| Genre | Suggested Changes |
|-------|-------------------|
| Slower house (115-125 BPM) | Reduce `MIN_BPM` to 90 |
| Fast techno (160-180 BPM) | Increase `MAX_BPM` to 190 |
| Breakbeat/DnB | Disable kick filter, may need different onset method |

## Architecture Decisions

### Why aubio Onset Instead of Tempo?

aubio's `tempo` class has a warm-up period and returns BPM estimates that can lag behind tempo changes. The `onset` class gives immediate beat positions, which we then process through our own PLL for better control.

### Why Not Use madmom?

madmom has excellent beat tracking but has Python 3.11+ compatibility issues. aubio is more portable and sufficient for kick-heavy electronic music.

### Why a Custom PLL Instead of aubio's Built-in Tracking?

The built-in tracking doesn't provide:
- Explicit lock state for MIDI start/stop signals
- Timeout detection for breakdowns
- Fast tempo change detection for DJ transitions
- Rejection of spurious detections

## Further Research

See [BEAT_DETECTION_RESEARCH.md](BEAT_DETECTION_RESEARCH.md) for detailed research on alternative algorithms and potential improvements, including:
- Cumulative Beat Strength Signal (CBSS)
- Comb filter resonator banks
- Predominant Local Pulse (PLP)
- BeatNet neural network approach

## References

- [aubio documentation](https://aubio.org/doc/latest/)
- [Phase-Locked Loop theory](https://en.wikipedia.org/wiki/Phase-locked_loop)
- [MIDI Clock specification](https://www.midi.org/specifications-old/item/table-1-summary-of-midi-message) - 24 PPQN

## Changelog

### 2024-12 - PLL Stability Improvements

- Fixed spurious detection causing lock loss (only check tempo change for valid intervals)
- Improved drift correction (75% bias threshold instead of 100%)
- Added adaptive tempo blending based on interval buffer size
- Reset tempo_change_count when entering LOCKED state
- Result: 98.7% acceptance rate, no lock loss, BPM within 1.2% of actual
