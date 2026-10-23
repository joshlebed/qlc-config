`README.md` is the human-facing overview (what this is, setup, usage); open it when a task needs those details.

# agent notes for qlc-config

## deployed on

Two roles: the **server** (a Linux box running the QLC+ daemon headless via
systemd, WebSocket API on `:9999`, USB-DMX attached) and **clients** (any
machine importing the `qlcplus` package — e.g. a keypad service — with
`QLCPLUS_HOST` pointing at the server).

## quick reference

- **Run `make`** to see all available commands.
- **Control lights**: `make red`, `make blue`, `make fade`, `make off`.
- **Service management**: `make start`, `make stop`, `make status`.
- **Development**: `make check` runs linting and type checking.

## key gotchas

1. **WebSocket startup delay**: After `make restart`, wait ~3 seconds before
   sending commands. The WebSocket server takes time to initialize.

2. **Project file reload**: QLC+ only reads `spotlight.qxw` at startup. After
   editing it, run `make restart` to apply changes.

3. **Systemd security**: Don't add `ProtectSystem=strict` or
   `ProtectHome=read-only` to the service file — they break QLC+'s web server
   initialization.

4. **Function IDs**: Defined in `spotlight.qxw`. Use `make list` to see current
   mappings. The `ws_control.py` `MODES` dict must match.

5. **Mutual exclusivity**: QLC+ Solo Frames don't enforce mutual exclusion via
   WebSocket — only via GUI clicks. The client must stop other functions before
   starting a new one. Already handled in `qlcplus/client.py`.

## beat detection (PLP) development

**Status: on hold (2026-06-15).** The `plp-beat` systemd service is stopped and
`disable`d on the server — it won't start on boot, and the deployment's health
probes intentionally skip it so an expected-down service doesn't read as a
failure. Re-enable when resuming: `sudo systemctl enable --now plp-beat`, and
add it back to whatever monitors the server's units.

The `plp_beat_service/` implementation has jitter and BPM accuracy issues.

**Reference implementation** (use as the guide):

```
../real_time_plp/realtimeplp.py
```

If missing, clone it:

```bash
git clone https://github.com/groupmm/real_time_plp.git ../real_time_plp
```

**Current problems in `plp_beat_service/`:**

1. `tempogram.py` uses autocorrelation instead of Fourier tempogram
2. `plp.py` uses phase-advancing oscillator instead of kernel overlap-add
3. Phase correction is heuristic instead of extracted from DFT

**The fix**: port the algorithm from `../real_time_plp/realtimeplp.py` which
implements Fourier tempogram with DFT at tempo frequencies, sinusoidal kernel
synthesis with overlap-add, phase extraction from complex Fourier coefficients,
and the half-window causal constraint for real-time.

## production-critical reminder

The QLC+ server is what the household's keypad service and lighting automations
talk to. Breaking the systemd unit or the
WebSocket port can cascade into "lights stop responding to the keypad / HA".
