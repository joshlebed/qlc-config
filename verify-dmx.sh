#!/usr/bin/env bash
# verify-dmx.sh — check the QLC+ → USB-DMX → fixture chain end to end.
#
# Run this after reconnecting the FTDI USB-DMX dongle (e.g. following the
# 2026-07 mediaserver hardware migration, where the software chain came over
# on the transplanted boot drive but the physical dongle did not).
#
# Exit 0 = everything the software side can see is healthy. A physical light
# test (`make red` / `make off`) is still the final confirmation.

set -u
FTDI_SERIAL="A402PX50"   # from spotlight.qxw: UID="FT232R USB UART (S/N: A402PX50)"
fail=0

step() { printf '%-34s' "$1"; }
ok()   { echo "OK${1:+ — $1}"; }
bad()  { echo "MISSING${1:+ — $1}"; fail=1; }

echo "=== QLC+ / USB-DMX chain ==="

step "FTDI USB device present"
if lsusb | grep -qi '0403:6001'; then ok "$(lsusb | grep -i '0403:6001')"; else bad "plug in the FTDI USB-DMX dongle"; fi

step "/dev/ttyUSB* node"
if ls /dev/ttyUSB* >/dev/null 2>&1; then ok "$(ls /dev/ttyUSB* | tr '\n' ' ')"; else bad "no serial node — dongle not enumerated"; fi

step "/dev/dmx0 udev symlink"
if [ -e /dev/dmx0 ]; then ok; else bad "udev rule present but no device to match yet"; fi

step "qlcplus.service active"
if systemctl is-active --quiet qlcplus; then ok; else bad "sudo systemctl start qlcplus"; fi

step "WebSocket :9999 listening"
if ss -tln | grep -q ':9999'; then ok; else bad "QLC+ WS not up (wait ~3s after restart)"; fi

echo
if [ "$fail" -eq 0 ]; then
  echo "All checks passed. If the light still doesn't respond, restart QLC+ so"
  echo "it re-binds the output patch, then test the fixture:"
  echo "    sudo systemctl restart qlcplus && sleep 3 && make red && sleep 2 && make off"
else
  echo "One or more checks failed — see notes above. Most common cause after the"
  echo "migration: FTDI dongle not plugged into the new mini PC. After plugging in:"
  echo "    sudo systemctl restart qlcplus && sleep 3 && ./verify-dmx.sh"
fi
exit "$fail"
