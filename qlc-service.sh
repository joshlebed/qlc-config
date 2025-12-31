#!/bin/bash
#
# QLC+ Service Management Script
#
# Usage:
#   ./qlc-service.sh install   - Install and enable the systemd service
#   ./qlc-service.sh start     - Start headless QLC+
#   ./qlc-service.sh stop      - Stop headless QLC+ (to use GUI)
#   ./qlc-service.sh restart   - Restart the service
#   ./qlc-service.sh status    - Check service status
#   ./qlc-service.sh logs      - View live logs
#   ./qlc-service.sh gui       - Stop service and launch GUI for editing
#

set -e

SERVICE_NAME="qlcplus"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPO_SERVICE="$(dirname "$0")/qlcplus.service"
PROJECT_FILE="$(dirname "$0")/spotlight.qxw"

case "${1:-help}" in
    install)
        echo "Installing QLC+ service..."

        # Copy service file
        sudo cp "$REPO_SERVICE" "$SERVICE_FILE"
        sudo systemctl daemon-reload
        sudo systemctl enable "$SERVICE_NAME"

        echo "Service installed and enabled."
        echo "Run './qlc-service.sh start' to start."
        ;;

    start)
        echo "Starting QLC+ service..."
        sudo systemctl start "$SERVICE_NAME"
        sleep 2

        # Verify it's running
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            echo "QLC+ is running."
            echo "WebSocket: ws://$(hostname -I | awk '{print $1}'):9999/qlcplusWS"
        else
            echo "Failed to start. Check logs: ./qlc-service.sh logs"
            exit 1
        fi
        ;;

    stop)
        echo "Stopping QLC+ service..."
        sudo systemctl stop "$SERVICE_NAME"
        echo "QLC+ stopped. You can now run the GUI."
        ;;

    restart)
        echo "Restarting QLC+ service..."
        sudo systemctl restart "$SERVICE_NAME"
        sleep 2
        systemctl status "$SERVICE_NAME" --no-pager
        ;;

    status)
        systemctl status "$SERVICE_NAME" --no-pager || true
        echo ""
        echo "WebSocket port check:"
        ss -tln | grep 9999 || echo "  Port 9999 not listening"
        ;;

    logs)
        journalctl -u "$SERVICE_NAME" -f
        ;;

    gui)
        # Check if display is available
        if [ -z "$DISPLAY" ]; then
            echo "Error: No display available."
            echo ""
            echo "To use the GUI, connect with X11 forwarding:"
            echo "  ssh -Y $(whoami)@$(hostname)"
            echo ""
            echo "Or if on macOS, install XQuartz first:"
            echo "  brew install --cask xquartz"
            exit 1
        fi

        echo "Stopping service to launch GUI..."
        sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true

        echo "Launching QLC+ GUI with web access..."
        echo "When done, save and close QLC+, then run: ./qlc-service.sh start"
        echo ""
        qlcplus -w -o "$PROJECT_FILE"
        ;;

    uninstall)
        echo "Uninstalling QLC+ service..."
        sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        sudo rm -f "$SERVICE_FILE"
        sudo systemctl daemon-reload
        echo "Service uninstalled."
        ;;

    *)
        echo "QLC+ Service Manager"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  install   - Install and enable the systemd service"
        echo "  start     - Start headless QLC+ (WebSocket on port 9999)"
        echo "  stop      - Stop the service (to use GUI)"
        echo "  restart   - Restart the service"
        echo "  status    - Check if service is running"
        echo "  logs      - View live logs (Ctrl+C to exit)"
        echo "  gui       - Stop service and launch GUI for editing"
        echo "  uninstall - Remove the systemd service"
        ;;
esac
