read @README.md for high level context on the repo.

# agent notes for qlc-config

Cross-cutting infra docs (network, hosts, dev workflow, safety rails) live in the sibling [`homelab-infra`](https://github.com/joshlebed/homelab-infra) repo. If `~/code/homelab-infra` (or `/home/pi/code/homelab-infra` on the Pi, `/home/joshlebed/code/homelab-infra` on mediaserver) doesn't exist, clone it:

```bash
git clone git@github.com:joshlebed/homelab-infra.git ../homelab-infra
```

## deployed on

Cloned on both `pi` (lighting client) and `mediaserver` (QLC+ headless server at `192.168.0.221`). The QLC+ daemon runs on mediaserver via systemd and listens on the WebSocket API at `:9999`. Other repos in the homelab (notably `volume-control` on the Pi) use this package as a Python client.

## quick reference

- **Run `make`** to see all available commands.
- **Control lights**: `make red`, `make blue`, `make fade`, `make off`.
- **Service management**: `make start`, `make stop`, `make status`.
- **Development**: `make check` runs linting and type checking.

## key gotchas

1. **WebSocket startup delay**: After `make restart`, wait ~3 seconds before sending commands. The WebSocket server takes time to initialize.

2. **Project file reload**: QLC+ only reads `spotlight.qxw` at startup. After editing it, run `make restart` to apply changes.

3. **Systemd security**: Don't add `ProtectSystem=strict` or `ProtectHome=read-only` to the service file — they break QLC+'s web server initialization.

4. **Function IDs**: Defined in `spotlight.qxw`. Use `make list` to see current mappings. The `ws_control.py` `MODES` dict must match.

5. **Mutual exclusivity**: QLC+ Solo Frames don't enforce mutual exclusion via WebSocket — only via GUI clicks. The client must stop other functions before starting a new one. Already handled in `qlcplus/client.py`.

## beat detection (PLP) development

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

**The fix**: port the algorithm from `../real_time_plp/realtimeplp.py` which implements Fourier tempogram with DFT at tempo frequencies, sinusoidal kernel synthesis with overlap-add, phase extraction from complex Fourier coefficients, and the half-window causal constraint for real-time.

## production-critical reminder

The QLC+ server is reachable from the Pi's `volume-control` service and from any HA automation that triggers a lighting scene. Breaking the systemd unit or the WebSocket port can cascade into "lights stop responding to the keypad / HA". See `../homelab-infra/CLAUDE.md` for the full safety-rail policy.
