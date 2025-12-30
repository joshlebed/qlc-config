.PHONY: help install start stop restart status logs gui test lint format check sync clean

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
	uv run ruff check qlcplus/ ws_control.py

format:
	uv run ruff format qlcplus/ ws_control.py
	uv run ruff check --fix qlcplus/ ws_control.py

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
# Cleanup
# =============================================================================

clean:
	rm -rf .venv __pycache__ qlcplus/__pycache__ .pytest_cache .mypy_cache .ruff_cache
