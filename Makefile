.PHONY: help install start stop restart status logs gui test lint format check sync clean audio audio-pulse audio-color beat beat-debug beat-filter beat-note beat-devices beat-file midi-connect reactive reactive-start

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
	@echo "Beat-Reactive Lighting:"
	@echo "  make reactive       - Full beat-reactive show (MIDI->QLC+ Cue List)"
	@echo "  make reactive-start - Start reactive chaser (no beat detection)"
	@echo "  make midi-connect   - Connect BeatClock MIDI to QLC+"
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
	uv run ruff check qlcplus/ ws_control.py audio_reactive.py

format:
	uv run ruff format qlcplus/ ws_control.py audio_reactive.py
	uv run ruff check --fix qlcplus/ ws_control.py audio_reactive.py

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

# Connect BeatClock virtual MIDI port to QLC+ MIDI input
midi-connect:
	@echo "Connecting BeatClock MIDI to QLC+..."
	@aconnect -x 2>/dev/null || true
	@sleep 0.5
	@BEATCLOCK=$$(aconnect -l | grep -B1 "BeatClock" | head -1 | sed 's/client \([0-9]*\):.*/\1/'); \
	QLC=$$(aconnect -l | grep -B1 "__QLC__" | head -1 | sed 's/client \([0-9]*\):.*/\1/'); \
	if [ -n "$$BEATCLOCK" ] && [ -n "$$QLC" ]; then \
		aconnect $$BEATCLOCK:0 $$QLC:0 && echo "Connected: BeatClock ($$BEATCLOCK) -> QLC+ ($$QLC)"; \
	else \
		echo "Error: Could not find BeatClock or QLC+ MIDI ports"; \
		echo "Make sure beat_to_midi.py is running (--note-mode) and QLC+ is started"; \
		aconnect -l; \
		exit 1; \
	fi

# Start only the reactive show chaser (for manual testing or external MIDI)
reactive-start:
	@uv run python ws_control.py reactive

# Full beat-reactive workflow:
# 1. Start reactive chaser in QLC+
# 2. Run beat detection with note mode
# Note: MIDI auto-connects because QLC+ sees the virtual port
reactive:
	@echo "Starting beat-reactive lighting show..."
	@echo "Pattern: FLASH -> base -> PUNCH -> base (4-beat loop)"
	@echo ""
	@uv run python ws_control.py reactive
	@sleep 1
	@$(MAKE) midi-connect 2>/dev/null || true
	@echo ""
	@echo "Starting beat detection (Ctrl+C to stop)..."
	@uv run python beat_to_midi.py --device 5 --no-filter --note-mode

# =============================================================================
# Cleanup
# =============================================================================

clean:
	rm -rf .venv __pycache__ qlcplus/__pycache__ .pytest_cache .mypy_cache .ruff_cache
