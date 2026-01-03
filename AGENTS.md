# Agent Instructions

See @README.md for complete project documentation.

## Quick Reference

- **Run `make`** to see all available commands
- **Control lights**: `make red`, `make blue`, `make fade`, `make off`
- **Service management**: `make start`, `make stop`, `make status`
- **Development**: `make check` runs linting and type checking

## Key Gotchas

1. **WebSocket startup delay**: After `make restart`, wait ~3 seconds before running commands. The WebSocket server takes time to initialize.

2. **Project file reload**: QLC+ only reads `spotlight.qxw` at startup. After editing it, run `make restart` to apply changes.

3. **Systemd security**: Don't add `ProtectSystem=strict` or `ProtectHome=read-only` to the service file - they break QLC+'s web server.

4. **Function IDs**: Defined in `spotlight.qxw`. Use `make list` to see current mappings. The `ws_control.py` MODES dict must match.

5. **Mutual exclusivity**: QLC+ Solo Frames don't work via WebSocket. The client must stop other functions before starting a new one (already handled in `qlcplus/client.py`).

## Beat Detection (PLP) Development

The `plp_beat_service/` needs improvement - it has jitter and BPM accuracy issues.

**Reference implementation** (use this as the guide):
```
../real_time_plp/realtimeplp.py   # Correct algorithm implementation
```

If missing, clone it:
```bash
git clone https://github.com/groupmm/real_time_plp.git ../real_time_plp
```

**Current problems in `plp_beat_service/`:**
1. `tempogram.py` uses autocorrelation instead of Fourier tempogram
2. `plp.py` uses phase-advancing oscillator instead of kernel overlap-add
3. Phase correction is heuristic instead of extracted from DFT

**The fix**: Port the algorithm from `../real_time_plp/realtimeplp.py` which implements:
- Fourier tempogram with DFT at tempo frequencies
- Sinusoidal kernel synthesis with overlap-add
- Phase extraction from complex Fourier coefficients
- Half-window causal constraint for real-time
