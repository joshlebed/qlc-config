.PHONY: help deploy
.PHONY: qlc-install qlc-start qlc-stop qlc-restart qlc-status qlc-logs qlc-gui
.PHONY: install start stop restart status logs gui
.PHONY: beat-install beat-start beat-stop beat-restart beat-status beat-logs beat-debug
.PHONY: plp plp-midi plp-clock plp-devices plp-benchmark
.PHONY: red blue green yellow orange cyan purple pink white off fade reactive list
.PHONY: midi-list midi-connect
.PHONY: sync test lint format check clean

# =============================================================================
# Help
# =============================================================================

help:
	@echo "QLC+ Lighting Control"
	@echo "====================="
	@echo ""
	@echo "PUBLISH (run from laptop):"
	@echo "  make deploy          Push + ssh-pull on mediaserver + restart qlcplus + plp-beat"
	@echo ""
	@echo "SERVICES (systemd, run ON mediaserver):"
	@echo "  make qlc-{install,start,stop,restart,status,logs,gui}"
	@echo "  make beat-{install,start,stop,restart,status,logs,debug}"
	@echo "  (also: make {install,start,stop,restart,status,logs,gui} — standard"
	@echo "         homelab verbs; aliased to qlc-*)"
	@echo ""
	@echo "LIGHT CONTROL:"
	@echo "  make red|blue|green|yellow|orange|cyan|purple|pink|white|off|fade"
	@echo "  make list            List all QLC+ functions"
	@echo "  make reactive        Enable beat-reactive mode in QLC+"
	@echo ""
	@echo "BEAT DETECTION (manual / testing):"
	@echo "  make plp             Run PLP beat tracker (OSC → QLC+, recommended)"
	@echo "  make plp-midi        Run PLP with MIDI note output"
	@echo "  make plp-clock       Run PLP with MIDI clock (24 PPQN)"
	@echo "  make plp-devices     List audio devices"
	@echo "  make plp-benchmark FILE=x.wav  Benchmark on audio file"
	@echo ""
	@echo "MIDI:"
	@echo "  make midi-list       List ALSA MIDI clients"
	@echo "  make midi-connect    Wire beat MIDI port → Midi Through"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make sync            Install dependencies"
	@echo "  make test            Run pytest"
	@echo "  make lint            Run ruff linter"
	@echo "  make format          Format code with ruff"
	@echo "  make check           lint + ty type checker (homelab \"check\" verb)"
	@echo "  make clean           Remove cache files"

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

# Standard homelab verbs (aliased to qlc-*). Lets `make restart` mean "restart
# the service" consistently across child repos.
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
	@echo "Installed. Start with: make beat-start"

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

# =============================================================================
# PLP Beat Detection (manual / testing)
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
		echo "Error: No beat MIDI port found. Start plp-beat first"; \
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
	uv run ty check qlcplus/ plp_beat_service/

clean:
	rm -rf .venv __pycache__ qlcplus/__pycache__ plp_beat_service/__pycache__ .pytest_cache .ty .ruff_cache

# =============================================================================
# Publish — laptop-side: push code, pull on mediaserver, restart services.
# Standard verb across the homelab; see homelab/CLAUDE.md.
# =============================================================================

deploy:
	@echo "→ git push origin main"
	git push origin main
	@echo "→ ssh mediaserver: pull + restart qlcplus + plp-beat"
	ssh mediaserver "cd /home/joshlebed/code/qlc-config && \
	  git pull --rebase origin main && \
	  sudo systemctl restart qlcplus plp-beat && \
	  sleep 3 && \
	  systemctl is-active qlcplus plp-beat"
