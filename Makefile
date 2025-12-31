.PHONY: help install start stop restart status logs gui test lint format check sync clean audio audio-pulse audio-color beat beat-debug beat-filter beat-note beat-devices beat-file midi-connect reactive reactive-manual beat-service-install beat-service-start beat-service-stop beat-service-status beat-service-logs

# Default target
help:
	@echo "QLC+ Lighting Control - Available Commands"
	@echo ""
	@echo "Service Management:"
	@echo "  make install    - Install systemd service and symlink project"
	@echo "  make start      - Start headless QLC+ service"
	@echo "  make stop       - Stop service (to use GUI)"
	@echo "  make restart    - Restart the service"
	@echo "  make status     - Check service status"
	@echo "  make logs       - View live logs (Ctrl+C to exit)"
	@echo "  make gui        - Stop service and launch GUI for editing"
	@echo ""
	@echo "Development:"
	@echo "  make sync       - Install Python dependencies with uv"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Run linter (ruff)"
	@echo "  make format     - Format code (ruff)"
	@echo "  make check      - Run all checks (lint + format + type check)"
	@echo ""
	@echo "Control:"
	@echo "  make red        - Set light to red"
	@echo "  make blue       - Set light to blue"
	@echo "  make green      - Set light to green"
	@echo "  make white      - Set light to white"
	@echo "  make off        - Turn light off"
	@echo "  make fade       - Start rainbow fade"
	@echo "  make reactive   - Start beat-reactive mode"
	@echo "  make list       - List all QLC+ functions"
	@echo ""
	@echo "Beat Detection (with PLL stabilization):"
	@echo "  make beat         - Beat->MIDI Clock (aubio + PLL)"
	@echo "  make beat-debug   - Same as beat, with debug output"
	@echo "  make beat-filter  - With kick drum bandpass filter"
	@echo "  make beat-note    - Beat->MIDI Notes instead of clock"
	@echo "  make beat-devices - List audio input devices"
	@echo "  make beat-file FILE=test.wav - Test with audio file"
	@echo ""
	@echo "Beat-Reactive Lighting (requires beat service running):"
	@echo "  make beat-service-install  - Install beat detection as systemd service"
	@echo "  make beat-service-start    - Start beat detection service"
	@echo "  make beat-service-stop     - Stop beat detection service"
	@echo "  make beat-service-status   - Check beat detection service status"
	@echo "  make beat-service-logs     - Tail beat detection logs"
	@echo "  make midi-connect          - Connect BeatClock MIDI to Midi Through"
	@echo "  make reactive-manual       - Full manual workflow (no service)"
	@echo ""
	@echo "Audio Reactive (legacy):"
	@echo "  make audio      - Direct DMX control (intensity mode)"
	@echo "  make audio-pulse - Direct DMX with beat flash"
	@echo "  make audio-color - Direct DMX with color cycling"

# =============================================================================
# Service Management
# =============================================================================

install:
	@./qlc-service.sh install

start:
	@./qlc-service.sh start

stop:
	@./qlc-service.sh stop

restart:
	@./qlc-service.sh restart

status:
	@./qlc-service.sh status

logs:
	@./qlc-service.sh logs

gui:
	@./qlc-service.sh gui

# =============================================================================
# Development
# =============================================================================

sync:
	uv sync --dev

test:
	uv run pytest

lint:
	uv run ruff check qlcplus/ ws_control.py audio_reactive.py beat_to_midi.py

format:
	uv run ruff format qlcplus/ ws_control.py audio_reactive.py beat_to_midi.py
	uv run ruff check --fix qlcplus/ ws_control.py audio_reactive.py beat_to_midi.py

check: lint
	uv run mypy qlcplus/

# =============================================================================
# Light Control (shortcuts)
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
# Audio Reactive (legacy - direct DMX control)
# =============================================================================

audio:
	@uv run python audio_reactive.py --mode intensity

audio-pulse:
	@uv run python audio_reactive.py --mode pulse

audio-color:
	@uv run python audio_reactive.py --mode color

# =============================================================================
# Beat Detection (madmom/aubio -> PLL -> MIDI Clock)
# =============================================================================

beat:
	@uv run python beat_to_midi.py --device 5 --no-filter

beat-debug:
	@uv run python beat_to_midi.py --device 5 --no-filter --debug

beat-filter:
	@uv run python beat_to_midi.py --device 5 --debug

beat-note:
	@uv run python beat_to_midi.py --device 5 --no-filter --note-mode

beat-devices:
	@uv run python beat_to_midi.py --list-devices

beat-file:
	@uv run python beat_to_midi.py --no-filter --debug --file $(FILE)

# =============================================================================
# Beat-Reactive Lighting Integration
# =============================================================================

# Connect BeatClock virtual MIDI port to Midi Through (stable bridge to QLC+)
midi-connect:
	@echo "Connecting BeatClock MIDI to Midi Through..."
	@BEATCLOCK=$$(aconnect -l | grep -B1 "BeatClock" | head -1 | sed 's/client \([0-9]*\):.*/\1/'); \
	if [ -n "$$BEATCLOCK" ]; then \
		aconnect $$BEATCLOCK:0 14:0 2>/dev/null && echo "Connected: BeatClock ($$BEATCLOCK) -> Midi Through (14)"; \
	else \
		echo "Error: BeatClock not found. Start beat_to_midi.py with --note-mode first"; \
		exit 1; \
	fi

# Full manual workflow (without using beat-midi service)
reactive-manual:
	@echo "Starting beat-reactive lighting (manual mode)..."
	@uv run python ws_control.py reactive
	@echo "Starting beat detection..."
	@uv run python beat_to_midi.py --device 5 --no-filter --note-mode &
	@BEAT_PID=$$!; \
	for i in 1 2 3 4 5; do sleep 0.5; aconnect -l | grep -q "BeatClock" && break; done; \
	$(MAKE) midi-connect; \
	echo "Beat detection running (Ctrl+C to stop)..."; \
	wait $$BEAT_PID

# =============================================================================
# Beat Detection Service (for always-on operation)
# =============================================================================

beat-service-install:
	@echo "Installing beat-midi service..."
	@sudo cp beat-midi.service /etc/systemd/system/
	@sudo systemctl daemon-reload
	@sudo systemctl enable beat-midi
	@echo "Installed. Start with: make beat-service-start"

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
# Cleanup
# =============================================================================

clean:
	rm -rf .venv __pycache__ qlcplus/__pycache__ .pytest_cache .mypy_cache .ruff_cache
