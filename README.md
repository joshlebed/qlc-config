# QLC+ Lighting Control

Python client library and configuration for controlling QLC+ lighting software via WebSocket API.

## Quick Start

```bash
# Install the package
uv pip install git+https://github.com/joshlebed/qlc-config.git

# Set the QLC+ host
export QLCPLUS_HOST=192.168.0.221

# Control the light
qlc red      # Turn light red
qlc white    # Turn light white
qlc off      # Turn light off
```

## Overview

This repository contains:

| Path | Description |
|------|-------------|
| `qlcplus/` | Python package for WebSocket API control |
| `plp_beat_service/` | **Current** PLP-based beat detection service |
| `test_data/` | Ground-truth beat data from rekordbox (JSON + audio) |
| `sample_data/` | Test audio files with known BPM (118-155 range) |
| `spotlight.qxw` | QLC+ project file (scenes, fixtures, virtual console) |
| `ws_control.py` | CLI tool for controlling lights |
| `qlcplus.service` | Systemd service for QLC+ headless operation |
| `plp-beat.service` | Systemd service for beat detection |
| `beat_to_midi.py` | **Deprecated** - use `plp_beat_service` instead |
| `audio_reactive.py` | **Deprecated** - legacy direct DMX control |
| `osc_control.py` | **Deprecated** - legacy OSC control |

See [BEAT_DETECTION.md](BEAT_DETECTION.md) for technical documentation on the beat detection system.

## Architecture

```
┌─────────────────────┐     WebSocket (9999)     ┌─────────────────┐
│  Keypad Service     │ ────────────────────────▶│  QLC+           │
│  (other server)     │                          │  192.168.0.221  │
└─────────────────────┘                          └────────┬────────┘
                                                          │ DMX512
┌─────────────────────┐     WebSocket (9999)              ▼
│  ws_control.py      │ ────────────────────────▶ ┌───────────────┐
│  (this server)      │                           │ USB-DMX       │
└─────────────────────┘                           │ Interface     │
                                                  └───────┬───────┘
                                                          │
                                                  ┌───────▼───────┐
                                                  │ ADJ Pinspot   │
                                                  │ LED Quad DMX  │
                                                  └───────────────┘
```

## Python Package Usage

### Installation

```bash
# Using uv (recommended)
uv pip install git+https://github.com/joshlebed/qlc-config.git

# Using pip
pip install git+https://github.com/joshlebed/qlc-config.git

# For development
git clone https://github.com/joshlebed/qlc-config.git
cd qlc-config
uv sync --dev
```

### API Reference

```python
from qlcplus import QLCPlusClient

# Connect with context manager (auto-disconnects)
with QLCPlusClient(host="192.168.0.221") as client:
    # Start a function by ID
    client.start_function(2)  # mode_red

    # Stop a function by ID
    client.stop_function(2)

    # Get function status
    status = client.get_function_status(2)  # "Running" or "Stopped"

    # List all functions
    functions = client.get_functions_list()
    # {0: "mode_off", 1: "mode_white", 2: "mode_red", 3: "mode_yellow"}

    # Direct DMX channel control
    client.set_channel(universe=1, channel=1, value=255)
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QLCPLUS_HOST` | `192.168.0.221` | QLC+ server IP address |
| `QLCPLUS_WS_PORT` | `9999` | WebSocket port |

### Function IDs

These IDs are defined in `spotlight.qxw` and correspond to QLC+ Scene functions:

| ID | Name | Description |
|----|------|-------------|
| 0 | `mode_off` | All DMX channels to 0 |
| 1 | `mode_white` | RGBW all at 100%, dimmer 100% |
| 2 | `mode_red` | Red 100%, dimmer 100% |
| 3 | `mode_yellow` | Red + Green 100%, dimmer 100% |

### Mutual Exclusion Pattern

Scenes must be manually exclusive. When setting a mode, stop others first:

```python
MODES = {"off": 0, "white": 1, "red": 2, "yellow": 3}

def set_mode(mode: str) -> None:
    with QLCPlusClient() as client:
        # Stop all other modes
        for name, func_id in MODES.items():
            if name != mode:
                client.stop_function(func_id)
        # Start target mode
        client.start_function(MODES[mode])
```

## Hardware Configuration

### QLC+ Server

- **Host**: `192.168.0.221`
- **WebSocket Port**: `9999`
- **OSC Port**: `7701` (legacy)

### USB-DMX Interface

- **Type**: FTDI FT232R USB UART
- **Vendor ID**: `0403`
- **Product ID**: `6001`
- **Serial**: `A402PX50`
- **Device**: `/dev/ttyUSB0`

### Fixture: ADJ Pinspot LED Quad DMX

- **DMX Mode**: 6 Channel
- **DMX Address**: 1
- **Channels**:
  | Channel | Function | Range |
  |---------|----------|-------|
  | 1 | Red | 0-255 |
  | 2 | Green | 0-255 |
  | 3 | Blue | 0-255 |
  | 4 | White | 0-255 |
  | 5 | Dimmer | 0-255 |
  | 6 | Strobe | 0-255 |

## Server Setup

### Prerequisites

```bash
sudo apt update
sudo apt install -y qlcplus xvfb
```

### Install Python Package

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/joshlebed/qlc-config.git
cd qlc-config
uv sync
```

### USB-DMX Permissions

```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER

# Create udev rule for consistent device naming
sudo tee /etc/udev/rules.d/99-usb-dmx.rules << 'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="dmx0"
EOF
sudo udevadm control --reload-rules

# Log out and back in for group changes
```

### Headless Service (Systemd)

Use the helper script for easy management:

```bash
# One-time setup: install service and symlink project
./qlc-service.sh install

# Start headless QLC+ (WebSocket on port 9999)
./qlc-service.sh start

# Stop service to use GUI
./qlc-service.sh stop

# Check status
./qlc-service.sh status

# View logs
./qlc-service.sh logs

# Stop service and open GUI for editing
./qlc-service.sh gui
```

**Service features:**
- Runs headless with xvfb (no monitor needed)
- WebSocket API enabled on port 9999
- Starts in operate mode (ready to receive commands)
- Auto-restarts on crash (max 3 times per minute)
- Logs to journald

**Important systemd notes:**
- Do NOT use `ProtectSystem=strict` or `ProtectHome=read-only` - they break QLC+'s web server initialization
- The service uses `RuntimeDirectory=qlcplus` to provide a writable XDG_RUNTIME_DIR
- `StartLimitIntervalSec` and `StartLimitBurst` must be in the `[Unit]` section, not `[Service]`

**Manual systemd commands:**
```bash
sudo systemctl start qlcplus    # Start
sudo systemctl stop qlcplus     # Stop
sudo systemctl restart qlcplus  # Restart
sudo systemctl status qlcplus   # Status
journalctl -u qlcplus -f        # Live logs
```

### Beat Detection Service (PLP)

The PLP beat detection service runs as a separate systemd service, detecting beats from audio input and sending MIDI notes to QLC+.

**Makefile commands (recommended):**
```bash
make beat-install    # One-time setup: install systemd service
make beat-start      # Start beat detection
make beat-stop       # Stop beat detection
make beat-restart    # Restart beat detection
make beat-status     # Check service status
make beat-logs       # Tail live logs (Ctrl+C to exit)
make beat-debug      # Show debug console URL
```

**Debug console:**

The service includes a real-time browser-based visualization:
- Open `http://192.168.0.221:8080/debug.html` in a browser
- Shows onset envelope, PLP pulse curve, and confidence metrics
- Displays current BPM, state (SEARCHING/LOCKED/HOLDOVER), and beat count

**Manual testing:**
```bash
make plp             # Run manually with OSC output
make plp-midi        # Run manually with MIDI note output
make plp-devices     # List available audio devices
```

**Manual systemd commands:**
```bash
sudo systemctl start plp-beat    # Start
sudo systemctl stop plp-beat     # Stop
sudo systemctl restart plp-beat  # Restart
sudo systemctl status plp-beat   # Status
journalctl -u plp-beat -f        # Live logs
```

## GUI Configuration

QLC+ requires a GUI session for initial setup. After configuration, it runs headless.

### X11 Forwarding (from macOS)

```bash
# On Mac: Install XQuartz
brew install --cask xquartz

# SSH with X11 forwarding
ssh -Y user@192.168.0.221

# Run QLC+ with web access
qlcplus -w -o /opt/qlcplus/projects/spotlight.qxw
```

### Key GUI Steps

1. **Inputs/Outputs**: Enable DMX USB output on Universe 1
2. **Fixtures**: Add ADJ Pinspot LED Quad DMX at address 1
3. **Functions**: Create scenes (mode_off, mode_red, etc.)
4. **Virtual Console**: Create buttons in Solo Frame (optional for OSC)
5. **Save**: Save to `/opt/qlcplus/projects/spotlight.qxw`

## Integration Options

### Option A: Install from Git (Recommended)

Best for services that need the `qlcplus` package as a dependency.

```bash
# In your other project's pyproject.toml
dependencies = [
    "qlcplus @ git+https://github.com/joshlebed/qlc-config.git",
]

# Or install directly
uv pip install git+https://github.com/joshlebed/qlc-config.git
```

### Option B: Git Submodule

Best if you need to modify the package or want version pinning.

```bash
# In your other project
git submodule add https://github.com/joshlebed/qlc-config.git libs/qlc-config

# Install in editable mode
uv pip install -e libs/qlc-config
```

### Option C: Copy Package Only

Minimal approach for simple integrations.

```bash
# Copy just the package
cp -r qlcplus/ /path/to/your/project/

# Add websocket-client to your dependencies
uv pip install websocket-client
```

## Development

```bash
# Clone and setup
git clone https://github.com/joshlebed/qlc-config.git
cd qlc-config
uv sync --dev

# Run linter
uv run ruff check .
uv run ruff format .

# Run type checker
uv run ty check qlcplus/

# Run tests
uv run pytest
```

## Test Data

### Ground Truth Data (`test_data/`)

The `test_data/` directory contains audio files with **precise beat grid data** from rekordbox analysis:

```bash
# Run benchmark on a single file (--simulate-room required for accurate results)
uv run python -m plp_beat_service.benchmark test_data/narciss_tall_people_140.mp3 -e 140 --simulate-room

# Run on all test files
for f in test_data/*.mp3; do
    bpm=$(echo "$f" | grep -oP '\d+(?=\.mp3)')
    echo "Testing: $f (expected: $bpm BPM)"
    uv run python -m plp_beat_service.benchmark "$f" -e "$bpm" --simulate-room
done
```

**Note**: The `--simulate-room` flag is required for file-based benchmarks to match live microphone performance. It applies room acoustics simulation (lowpass filter, compression, level reduction) that compensates for the difference between direct file input and mic capture.

Each track has a JSON file with ground-truth beat times:
```json
{
  "bpm": 140.0,
  "first_beat_sec": 0.214,
  "beats": [0.214, 0.643, 1.071, ...],
  "audio_file": "narciss_tall_people_140.mp3"
}
```

See `test_data/README.md` for the full format and evaluation code.

### Legacy Sample Data (`sample_data/`)

The `sample_data/` directory contains older test files with BPM in the filename (e.g., `underworld_dark_and_long_135.mp3`).

## Troubleshooting

### WebSocket Connection Failed

```bash
# Check QLC+ is running with web access
ps aux | grep qlcplus
# Should show: qlcplus -w ...

# Check port is listening
ss -tln | grep 9999

# Test connection
curl -s http://192.168.0.221:9999/
```

**After service restart**: The WebSocket server takes ~3 seconds to initialize. If you get "Connection refused" immediately after `make restart`, wait and retry.

### Project File Changes Not Taking Effect

QLC+ loads the project file at startup. After editing `spotlight.qxw`:

```bash
make restart  # Reload the project file
sleep 3       # Wait for WebSocket to initialize
make list     # Verify changes
```

### No DMX Output

```bash
# Check USB device
ls -la /dev/ttyUSB*

# Check permissions
groups | grep dialout

# Check QLC+ output patch in GUI
```

### Function Not Starting

```bash
# List functions to verify IDs
uv run python ws_control.py --list

# Check function status
uv run python ws_control.py --status
```

### Scenes Not Responding (Simple Desk Override)

If scenes activate but the light doesn't change, Simple Desk may be overriding them:

1. Open QLC+ GUI: `make gui`
2. Go to Simple Desk tab
3. Click "Reset universe" to set all channels to 0
4. Save the project

Simple Desk values take priority over scenes when non-zero.

### Buttons Not Working in Virtual Console

Ensure QLC+ is in **Operate Mode**, not Design Mode:
- Press the "play" button in the toolbar, or
- Start with `-p` flag (the systemd service does this)

### Solo Frame Not Working via API

QLC+ Solo Frames only enforce mutual exclusivity for **GUI clicks**, not WebSocket/OSC commands. The client must implement exclusivity:

```python
# Stop all other modes before starting the new one
for func_id in ALL_MODE_IDS:
    if func_id != target_id:
        client.stop_function(func_id)
client.start_function(target_id)
```

This is already handled in `ws_control.py` and the `qlcplus` package.

### Creating Smooth Fade Chasers

For smooth color transitions (not abrupt jumps):

1. Create Scene functions for each color
2. Create a Chaser containing those scenes
3. Set Speed Modes to **"Per Step"** (not "Default" or "Common")
4. Set FadeIn and FadeOut times equal (e.g., both 2000ms)
5. Set Hold time for how long each color stays solid

Example in project file:
```xml
<Function ID="4" Type="Chaser" Name="mode_fade">
  <SpeedModes FadeIn="PerStep" FadeOut="PerStep" Duration="Common"/>
  <Step FadeIn="2000" Hold="1000" FadeOut="2000">2</Step>
  ...
</Function>
```

## File Reference

| File | Purpose |
|------|---------|
| `qlcplus/__init__.py` | Package exports (`QLCPlusClient`, `QLCPlusError`) |
| `qlcplus/client.py` | WebSocket client implementation |
| `qlcplus/py.typed` | PEP 561 marker for type checking |
| `plp_beat_service/` | PLP beat detection service package |
| `plp_beat_service/benchmark.py` | File-based beat detection testing (faster than real-time) |
| `plp_beat_service/debug_server.py` | WebSocket debug server for visualization |
| `plp_beat_service/static/debug.html` | Browser-based debug console |
| `plp-beat.service` | Systemd unit file for beat detection |
| `test_data/` | Ground-truth beat data from rekordbox (JSON + MP3) |
| `preprocess_rekordbox.py` | Generate test_data from rekordbox XML export |
| `ws_control.py` | CLI tool using WebSocket API |
| `spotlight.qxw` | QLC+ project file (XML) |
| `qlcplus.service` | Systemd unit file for QLC+ headless operation |
| `qlc-service.sh` | Helper script for QLC+ service management |
| `pyproject.toml` | Package metadata and tool configuration |
| `uv.lock` | Locked dependencies for reproducible installs |
| `BEAT_DETECTION.md` | Technical docs for beat detection system |
| `beat_to_midi.py` | **Deprecated** - aubio+PLL approach, replaced by plp_beat_service |
| `audio_reactive.py` | **Deprecated** - direct DMX control |
| `osc_control.py` | **Deprecated** - OSC control |

## License

MIT
