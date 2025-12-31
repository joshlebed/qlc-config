# Beat Detection Research

Research notes on improving real-time beat detection for lighting control.

## Executive Summary

Our current system uses aubio onset detection + a custom PLL. Research shows several potential improvements:

1. **Better onset detection** - Use spectral flux or complex domain instead of energy-based
2. **Cumulative Beat Strength Signal (CBSS)** - Reinforce periodic patterns over time
3. **Tempo estimation via autocorrelation/comb filters** - More robust than interval tracking
4. **Consider BeatNet or librosa PLP** - State-of-the-art alternatives to our custom PLL

---

## Current Architecture vs. Research Findings

| Component | Our System | State-of-the-Art |
|-----------|------------|------------------|
| Onset detection | aubio energy-based | Spectral flux, complex domain, neural networks |
| Tempo estimation | Interval median | Autocorrelation + comb filter resonators |
| Phase tracking | Custom PLL with drift correction | Dynamic Bayesian Networks, particle filtering |
| Beat prediction | Linear extrapolation | Cumulative beat strength signal (CBSS) |

---

## Key Algorithms to Consider

### 1. Cumulative Beat Strength Signal (CBSS)

Used in [OBTAIN](https://arxiv.org/pdf/1704.02216) and [BTrack](https://github.com/adamstark/BTrack).

**How it works:**
```
CBSS[n] = (1-α) * OSS[n] + α * Φ[n-period]
```

Where:
- `OSS[n]` = onset strength at frame n
- `Φ[n-period]` = CBSS value from one beat period ago
- `α` = blend factor (higher = more stable, less responsive)

**Why it helps:** Creates a quasi-periodic signal that spikes on beats. Even during weak sections, previous scores carry forward to maintain periodicity. This directly addresses our issue of inconsistent timing.

### 2. Comb Filter / Resonator Bank

Used in [Scheirer's seminal work](https://quod.lib.umich.edu/i/icmc/bbp2372.2011.123/--real-time-visual-beat-tracking-using-a-comb-filter-matrix) and many DJ applications.

**How it works:**
1. Compute onset detection function
2. Pass through bank of comb filters tuned to different tempos (60-180 BPM)
3. The filter with highest energy output indicates the tempo
4. Phase is determined by the filter's output phase

**Why it helps:** More robust tempo estimation than measuring intervals. The resonator "locks" to periodic patterns in the signal.

### 3. Predominant Local Pulse (PLP)

Available in [librosa](https://librosa.org/doc/main/generated/librosa.beat.plp.html) and [real_time_plp](https://github.com/groupmm/real_time_plp).

**How it works:**
1. Compute tempogram (tempo over time)
2. For each frame, find the predominant tempo
3. Synthesize a sinusoidal kernel that best explains local periodic patterns
4. Accumulate kernels to get pulse curve
5. Peaks in pulse curve = beat positions

**Why it helps:**
- Handles tempo variation naturally
- Works in streaming mode (no lookahead required)
- Provides pulse stability measure for confidence tracking

### 4. BeatNet (Neural Network + Particle Filtering)

[State-of-the-art system](https://github.com/mjhydri/BeatNet) from ISMIR 2021.

**How it works:**
1. Neural network (CRNN) produces beat/downbeat activations
2. Particle filter tracks multiple tempo/phase hypotheses
3. Best hypothesis is selected based on activation agreement

**Why it helps:** Neural networks can learn complex rhythmic patterns. Particle filtering handles tempo changes elegantly.

---

## Specific Problems and Potential Solutions

### Problem 1: Inconsistent beat timing (±20-30ms jitter)

**Possible causes:**
- Onset detection picks up snares, hi-hats, or synth stabs in addition to kicks
- aubio's energy-based detection has inherent variance

**Research-backed solutions:**
1. **Multi-band onset detection**: Split audio into frequency bands, weight kick drum band (30-200Hz) more heavily
2. **Spectral flux onset**: More precise than energy-based for percussive onsets
3. **CBSS accumulation**: Reinforces periodic timing, reduces impact of individual onset jitter

### Problem 2: BPM drifts 1-2% from actual tempo

**Possible causes:**
- Interval-based estimation is sensitive to individual beat timing errors
- Median filtering smooths but doesn't lock to true periodicity

**Research-backed solutions:**
1. **Autocorrelation-based tempo**: More robust to individual beat errors
2. **Comb filter resonators**: Lock to the dominant periodicity in the signal
3. **PLP approach**: Uses entire tempogram context, not just intervals

### Problem 3: Off-beat detections

**Possible causes:**
- Snare hits on beats 2 and 4 can be stronger than kicks
- Hi-hats create periodic patterns at double tempo

**Research-backed solutions:**
1. **Metrical hierarchy modeling**: Track beat AND downbeat (madmom DBN approach)
2. **Tempo prior**: Weight expected house/techno tempos (120-160 BPM) more heavily
3. **Multi-hypothesis tracking**: Maintain multiple phase hypotheses, select most consistent

---

## Research Questions to Answer Before Implementing

### Q1: What onset detection method works best for our use case?

**Test plan:**
1. Record test tracks with known BPM and beat positions
2. Compare onset detection methods: `energy`, `hfc`, `complex`, `specflux`
3. Measure: precision, recall, timing accuracy of detected onsets
4. Determine which method gives most consistent kick drum detection

**Resources:**
- [aubio onset methods](https://aubio.org/manual/latest/cli.html)
- [Bello et al. onset detection survey](http://eecs.qmul.ac.uk/~josh/documents/2010/Zhou%20Reiss%20-%20Music%20Onset%20Detection%202010.pdf)

### Q2: Does CBSS improve our timing consistency?

**Test plan:**
1. Implement CBSS accumulation in our PLL
2. Test with same tracks, measure beat timing variance
3. Tune α parameter (stability vs responsiveness)
4. Compare F-measure with ±70ms tolerance

**Key insight from research:**
> "Even when the signal is idle, previous scores could be used to obtain the next beat"

This could help with breakdowns and tempo stability.

### Q3: Should we replace our PLL with autocorrelation + comb filter?

**Test plan:**
1. Implement autocorrelation-based tempo estimation
2. Compare tempo accuracy over time vs our interval median
3. Measure convergence speed on tempo changes
4. Evaluate computational cost

**Resources:**
- [OBTAIN paper](https://arxiv.org/pdf/1704.02216) - detailed CBSS + comb filter approach
- [BTrack implementation](https://github.com/adamstark/BTrack/blob/master/src/BTrack.cpp)

### Q4: Is librosa's PLP suitable for real-time use?

**Test plan:**
1. Test librosa.beat.plp in streaming mode
2. Measure latency and computational cost
3. Compare beat accuracy with our system
4. Evaluate if it can run at 44.1kHz with acceptable CPU usage

**Note:** librosa documentation says PLP is preferable "when beat-tracking long recordings in a streaming setting"

### Q5: Should we consider neural network approaches?

**Test plan:**
1. Install and test BeatNet in real-time mode
2. Measure accuracy on our test tracks
3. Evaluate CPU/GPU requirements
4. Assess if it can run on headless media server

**Considerations:**
- BeatNet is state-of-the-art but may require more compute
- May need GPU for real-time performance
- Model may not generalize well to all techno subgenres

### Q6: How much does the kick drum bandpass filter help?

**Test plan:**
1. Compare onset detection with and without 30-200Hz bandpass
2. Measure reduction in off-beat detections (snare, hi-hat)
3. Test on different genres (minimal techno vs busy house)
4. Tune filter parameters if beneficial

---

## Proposed Research Roadmap

### Phase 1: Baseline Measurement
1. Create test dataset with ground truth beat positions
2. Measure current system's F-measure, tempo accuracy, timing variance
3. Establish baseline metrics to compare against

### Phase 2: Onset Detection Experiments
1. Compare aubio onset methods (energy vs complex vs specflux)
2. Test kick drum bandpass filter effectiveness
3. Evaluate multi-band onset detection

### Phase 3: Tempo Estimation Experiments
1. Implement autocorrelation-based tempo estimation
2. Test comb filter resonator approach
3. Compare with interval-based median

### Phase 4: Beat Prediction Experiments
1. Implement CBSS accumulation
2. Test librosa PLP in streaming mode
3. Evaluate BeatNet if compute resources allow

### Phase 5: Integration
1. Select best approaches from each phase
2. Integrate into unified system
3. Tune parameters for house/techno
4. Final evaluation against baseline

---

## Key Libraries and Tools

| Library | Language | Features | Real-time? |
|---------|----------|----------|------------|
| [aubio](https://aubio.org/) | Python/C | Onset, tempo, beat | Yes |
| [librosa](https://librosa.org/) | Python | PLP, beat_track, tempogram | Partial |
| [madmom](https://github.com/CPJKU/madmom) | Python | DBN, neural nets | Yes (with caveats) |
| [BeatNet](https://github.com/mjhydri/BeatNet) | Python | CRNN + particle filter | Yes |
| [BTrack](https://github.com/adamstark/BTrack) | C++ | CBSS, comb filter | Yes |
| [real_time_plp](https://github.com/groupmm/real_time_plp) | Python | PLP streaming | Yes |

---

## References

### Papers
- [OBTAIN: Real-Time Beat Tracking](https://arxiv.org/pdf/1704.02216) - CBSS approach
- [BeatNet: CRNN and Particle Filtering](https://arxiv.org/abs/2108.03576) - ISMIR 2021
- [Real-Time Beat Tracking with Zero Latency (PLP)](https://transactions.ismir.net/articles/10.5334/tismir.189) - TISMIR 2024
- [Beat Tracking by Dynamic Programming (Ellis)](https://www.ee.columbia.edu/~dpwe/pubs/Ellis07-beattrack.pdf)
- [Evaluation Methods for Beat Tracking](https://www.researchgate.net/publication/228724188_Evaluation_Methods_for_Musical_Audio_Beat_Tracking_Algorithms)

### Tutorials
- [Tempo, Beat and Downbeat Estimation Tutorial](https://tempobeatdownbeat.github.io/tutorial/ch2_basics/baseline.html)
- [FMP Notebooks: Predominant Local Pulse](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C6/C6S3_PredominantLocalPulse.html)
- [Audio Processing: Beat Tracking Explained](https://audioxpress.com/article/audio-processing-beat-tracking-explained)

### GitHub Repositories
- [BTrack](https://github.com/adamstark/BTrack) - C++ real-time beat tracker
- [BeatNet](https://github.com/mjhydri/BeatNet) - Neural network + particle filtering
- [real_time_plp](https://github.com/groupmm/real_time_plp) - 2024 PLP implementation
- [OBTAIN](https://github.com/alimottaghi/obtain) - CBSS-based tracker
- [madmom](https://github.com/CPJKU/madmom) - DBN beat tracking

---

## Next Steps

1. **Create ground truth test dataset** - Essential for comparing approaches
2. **Run onset detection experiments** - Low-hanging fruit, easy to test
3. **Prototype CBSS** - Most likely to improve our current system with minimal changes
4. **Evaluate external libraries** - librosa PLP or BeatNet as potential replacements
