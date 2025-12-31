.PHONY: help
.PHONY: qlc-install qlc-start qlc-stop qlc-restart qlc-status qlc-logs qlc-gui
.PHONY: beat-install beat-start beat-stop beat-restart beat-status beat-logs beat-debug
.PHONY: plp plp-midi plp-clock plp-devices plp-benchmark
.PHONY: aubio aubio-debug aubio-note aubio-devices aubio-file
.PHONY: red blue green yellow orange cyan purple pink white off fade reactive list
.PHONY: sync test lint format check clean

# =============================================================================
# Help
# =============================================================================

help:
	@echo "QLC+ Lighting Control"
	@echo "====================="
	@echo ""
	@echo "SERVICES (systemd):"
	@echo "  make qlc-install     Install QLC+ systemd service"
	@echo "  make qlc-start       Start QLC+ lighting daemon"
	@echo "  make qlc-stop        Stop QLC+ daemon"
	@echo "  make qlc-restart     Restart QLC+ daemon"
	@echo "  make qlc-status      Check QLC+ status"
	@echo "  make qlc-logs        Tail QLC+ logs"
	@echo "  make qlc-gui         Stop daemon and open GUI"
	@echo ""
	@echo "  make beat-install    Install PLP beat detection service"
	@echo "  make beat-start      Start beat detection service"
	@echo "  make beat-stop       Stop beat detection service"
	@echo "  make beat-restart    Restart beat detection service"
	@echo "  make beat-status     Check beat detection status"
	@echo "  make beat-logs       Tail beat detection logs"
	@echo "  make beat-debug      Show debug console URL"
	@echo ""
	@echo "LIGHT CONTROL:"
	@echo "  make red|blue|green|white|off|fade|..."
	@echo "  make list            List all QLC+ functions"
	@echo "  make reactive        Enable beat-reactive mode in QLC+"
	@echo ""
	@echo "BEAT DETECTION (manual/testing):"
	@echo "  make plp             Run PLP beat tracker (OSC output)"
	@echo "  make plp-midi        Run PLP with MIDI note output"
	@echo "  make plp-devices     List audio devices"
	@echo "  make plp-benchmark FILE=x.wav  Benchmark on audio file"
	@echo ""
	@echo "  make aubio           Run legacy aubio detector (MIDI clock)"
	@echo "  make aubio-note      Run legacy aubio (MIDI notes)"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make sync            Install dependencies"
	@echo "  make check           Run linter + type checker"
	@echo ""
	@echo "Run 'make help-full' for all targets"

help-full: help
	@echo ""
	@echo "ALL TARGETS:"
	@echo ""
	@echo "QLC+ Service:"
	@echo "  qlc-install    Install QLC+ systemd service"
	@echo "  qlc-start      Start QLC+ service"
	@echo "  qlc-stop       Stop QLC+ service"
	@echo "  qlc-restart    Restart QLC+ service"
	@echo "  qlc-status     Show QLC+ service status"
	@echo "  qlc-logs       Tail QLC+ logs (Ctrl+C to exit)"
	@echo "  qlc-gui        Stop service and open QLC+ GUI"
	@echo ""
	@echo "Beat Detection Service:"
	@echo "  beat-install   Install PLP beat service (replaces legacy)"
	@echo "  beat-start     Start beat detection service"
	@echo "  beat-stop      Stop beat detection service"
	@echo "  beat-restart   Restart beat detection service"
	@echo "  beat-status    Show beat service status"
	@echo "  beat-logs      Tail beat detection logs"
	@echo ""
	@echo "PLP Beat Detection (manual):"
	@echo "  plp            OSC output to QLC+ (recommended)"
	@echo "  plp-midi       MIDI note output"
	@echo "  plp-clock      MIDI clock (24 PPQN)"
	@echo "  plp-devices    List audio input devices"
	@echo "  plp-benchmark  Test with audio file (FILE=path.wav)"
	@echo ""
	@echo "Legacy Aubio Beat Detection (manual):"
	@echo "  aubio          MIDI clock output"
	@echo "  aubio-debug    With debug output"
	@echo "  aubio-filter   With kick drum filter"
	@echo "  aubio-note     MIDI note output"
	@echo "  aubio-devices  List audio devices"
	@echo "  aubio-file     Test with file (FILE=path.wav)"
	@echo ""
	@echo "Light Control:"
	@echo "  red, blue, green, yellow, orange, cyan, purple, pink, white"
	@echo "  off            Turn light off"
	@echo "  fade           Rainbow fade effect"
	@echo "  reactive       Beat-reactive mode"
	@echo "  list           List QLC+ functions"
	@echo ""
	@echo "Development:"
	@echo "  sync           Install Python dependencies"
	@echo "  test           Run pytest"
	@echo "  lint           Run ruff linter"
	@echo "  format         Format code with ruff"
	@echo "  check          Run lint + mypy"
	@echo "  clean          Remove cache files"

# =============================================================================
# QLC+ Service Management
# =============================================================================

qlc-install:
	@./qlc-service.sh install

qlc-start:
	@./qlc-service.sh start

qlc-stop:
	@./qlc-service.sh stop

qlc-restart:
	@./qlc-service.sh restart

qlc-status:
	@./qlc-service.sh status

qlc-logs:
	@./qlc-service.sh logs

qlc-gui:
	@./qlc-service.sh gui

# Legacy aliases (for backwards compatibility)
install: qlc-install
start: qlc-start
stop: qlc-stop
restart: qlc-restart
status: qlc-status
logs: qlc-logs
gui: qlc-gui

# =============================================================================
# Beat Detection Service Management
# =============================================================================

beat-install:
	@echo "Installing PLP beat detection service..."
	@sudo cp plp-beat.service /etc/systemd/system/
	@sudo systemctl daemon-reload
	@sudo systemctl enable plp-beat
	@echo ""
	@echo "Installed. Disabling legacy beat-midi service if present..."
	@sudo systemctl disable beat-midi 2>/dev/null || true
	@echo ""
	@echo "Start with: make beat-start"

beat-start:
	@sudo systemctl start plp-beat
	@sleep 2
	@sudo systemctl status plp-beat --no-pager | head -12

beat-stop:
	@sudo systemctl stop plp-beat

beat-restart:
	@sudo systemctl restart plp-beat
	@sleep 2
	@sudo systemctl status plp-beat --no-pager | head -12

beat-status:
	@sudo systemctl status plp-beat --no-pager

beat-logs:
	@journalctl -u plp-beat -f

beat-debug:
	@echo ""
	@echo "PLP Beat Debug Console"
	@echo "======================"
	@echo ""
	@echo "Open in browser: http://192.168.0.221:8080/debug.html"
	@echo ""
	@echo "Shows real-time:"
	@echo "  - Onset envelope (transient detection)"
	@echo "  - PLP pulse curve (beat probability)"
	@echo "  - Confidence components (pulse/tempo/raw)"
	@echo "  - State machine status (SEARCHING/LOCKED/HOLDOVER)"
	@echo ""
	@systemctl is-active plp-beat >/dev/null 2>&1 || echo "WARNING: plp-beat service is not running. Start with: make beat-start"
	@echo ""

# Legacy beat service (for reference - prefer beat-* targets above)
beat-service-install:
	@echo "NOTE: Use 'make beat-install' for PLP service instead"
	@echo "Installing legacy beat-midi service..."
	@sudo cp beat-midi.service /etc/systemd/system/
	@sudo systemctl daemon-reload
	@sudo systemctl enable beat-midi

beat-service-start:
	@sudo systemctl start beat-midi
	@sleep 2
	@sudo systemctl status beat-midi --no-pager | head -10

beat-service-stop:
	@sudo systemctl stop beat-midi

beat-service-status:
	@sudo systemctl status beat-midi --no-pager

beat-service-logs:
	@journalctl -u beat-midi -f

# =============================================================================
# PLP Beat Detection (manual/testing)
# =============================================================================

plp:
	@uv run plp-beat --device 5

plp-midi:
	@uv run plp-beat --device 5 --no-osc --midi

plp-clock:
	@uv run plp-beat --device 5 --no-osc --midi --clock

plp-devices:
	@uv run plp-beat --list-devices

plp-benchmark:
	@uv run python -m plp_beat_service.benchmark $(FILE)

# =============================================================================
# Legacy Aubio Beat Detection (manual/testing)
# =============================================================================

aubio:
	@uv run python beat_to_midi.py --device 5 --no-filter

aubio-debug:
	@uv run python beat_to_midi.py --device 5 --no-filter --debug

aubio-filter:
	@uv run python beat_to_midi.py --device 5 --debug

aubio-note:
	@uv run python beat_to_midi.py --device 5 --no-filter --note-mode

aubio-devices:
	@uv run python beat_to_midi.py --list-devices

aubio-file:
	@uv run python beat_to_midi.py --no-filter --debug --file $(FILE)

# Legacy aliases
beat: aubio
beat-debug: aubio-debug
beat-filter: aubio-filter
beat-note: aubio-note
beat-devices: aubio-devices
beat-file: aubio-file

# =============================================================================
# Light Control
# =============================================================================

red:
	@uv run python ws_control.py red

blue:
	@uv run python ws_control.py blue

green:
	@uv run python ws_control.py green

yellow:
	@uv run python ws_control.py yellow

orange:
	@uv run python ws_control.py orange

cyan:
	@uv run python ws_control.py cyan

purple:
	@uv run python ws_control.py purple

pink:
	@uv run python ws_control.py pink

white:
	@uv run python ws_control.py white

off:
	@uv run python ws_control.py off

fade:
	@uv run python ws_control.py fade

reactive:
	@uv run python ws_control.py reactive

list:
	@uv run python ws_control.py --list

# =============================================================================
# MIDI Utilities
# =============================================================================

midi-list:
	@aconnect -l

midi-connect:
	@echo "Connecting beat MIDI port to Midi Through..."
	@PORT=$$(aconnect -l | grep -E "PLPBeat|BeatClock" | head -1 | sed 's/client \([0-9]*\):.*/\1/'); \
	if [ -n "$$PORT" ]; then \
		aconnect $$PORT:0 14:0 2>/dev/null && echo "Connected: $$PORT -> Midi Through (14)"; \
	else \
		echo "Error: No beat MIDI port found. Start plp-beat or beat_to_midi.py first"; \
		exit 1; \
	fi

# =============================================================================
# Development
# =============================================================================

sync:
	uv sync --dev --all-extras

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

check: lint
	uv run mypy qlcplus/ plp_beat_service/

# =============================================================================
# Legacy Audio Reactive (direct DMX - rarely used)
# =============================================================================

audio:
	@uv run python audio_reactive.py --mode intensity

audio-pulse:
	@uv run python audio_reactive.py --mode pulse

audio-color:
	@uv run python audio_reactive.py --mode color

# =============================================================================
# Cleanup
# =============================================================================

clean:
	rm -rf .venv __pycache__ qlcplus/__pycache__ plp_beat_service/__pycache__ .pytest_cache .mypy_cache .ruff_cache
