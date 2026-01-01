"""CLI entry point for PLP Beat Service."""

import argparse
import sys

import sounddevice as sd

from plp_beat_service.service import PLPBeatService


def list_devices() -> None:
    """List available audio devices."""
    print("Available audio devices:")
    print("-" * 60)
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        input_ch = dev["max_input_channels"]
        if input_ch > 0:  # Only show input devices
            default = ""
            if i == sd.default.device[0]:
                default = " (default)"
            print(f"  {i}: {dev['name']} ({input_ch} ch){default}")
    print("-" * 60)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PLP-based beat tracking service for lighting control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  plp-beat                       # Run with OSC output (default)
  plp-beat -l                    # List audio devices
  plp-beat -d 2                  # Use audio device 2
  plp-beat --midi                # Enable MIDI note output
  plp-beat --midi --clock        # Enable MIDI clock (24 PPQN)
  plp-beat --no-osc --midi       # MIDI only (drop-in for beat_to_midi.py)
  plp-beat --bpm-min 120         # Set minimum BPM
  plp-beat --debug-server        # Enable visual debug console
  plp-beat --record mic.jsonl    # Record frames for comparison

Output modes:
  OSC (default): Sends /beat, /bpm, /confidence to QLC+
  MIDI Note: Sends MIDI notes on each beat
  MIDI Clock: Sends MIDI Clock (24 PPQN) with Start/Stop

Debug server:
  --debug-server opens a browser-accessible debug console at http://<ip>:8080/debug.html
  with real-time visualization of onset, pulse, and beat detection signals.
""",
    )

    # Audio device
    parser.add_argument(
        "-l",
        "--list-devices",
        action="store_true",
        help="List available audio input devices",
    )
    parser.add_argument(
        "-d",
        "--device",
        type=int,
        default=None,
        help="Audio device index (use -l to list)",
    )

    # BPM range
    parser.add_argument(
        "--bpm-min",
        type=int,
        default=115,
        help="Minimum BPM to detect (default: 115)",
    )
    parser.add_argument(
        "--bpm-max",
        type=int,
        default=165,
        help="Maximum BPM to detect (default: 165)",
    )

    # OSC output
    parser.add_argument(
        "--osc-host",
        type=str,
        default="127.0.0.1",
        help="OSC destination host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--osc-port",
        type=int,
        default=7701,
        help="OSC destination port (default: 7701)",
    )
    parser.add_argument(
        "--no-osc",
        action="store_true",
        help="Disable OSC output",
    )

    # MIDI output
    parser.add_argument(
        "--midi",
        action="store_true",
        help="Enable MIDI output (note mode by default)",
    )
    parser.add_argument(
        "--clock",
        action="store_true",
        help="Use MIDI Clock mode instead of notes (requires --midi)",
    )
    parser.add_argument(
        "--midi-port",
        type=str,
        default="PLPBeat",
        help="MIDI virtual port name (default: PLPBeat)",
    )

    # Compatibility aliases for beat_to_midi.py
    parser.add_argument(
        "--note-mode",
        action="store_true",
        help="Alias for --midi (compatibility with beat_to_midi.py)",
    )

    # Debug mode
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (tempo, pulse, peaks)",
    )

    # Debug server
    parser.add_argument(
        "--debug-server",
        action="store_true",
        default=True,
        help="Enable debug WebSocket server for visualization (default: enabled)",
    )
    parser.add_argument(
        "--no-debug-server",
        action="store_true",
        help="Disable debug WebSocket server",
    )
    parser.add_argument(
        "--debug-ws-port",
        type=int,
        default=9998,
        help="Debug WebSocket port (default: 9998)",
    )
    parser.add_argument(
        "--debug-http-port",
        type=int,
        default=8080,
        help="Debug HTTP server port (default: 8080)",
    )

    # Recording
    parser.add_argument(
        "--record",
        "-r",
        type=str,
        metavar="FILE",
        help="Record frame data to JSONL file for comparison with benchmark",
    )

    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return 0

    # Handle compatibility aliases
    enable_midi = args.midi or args.note_mode
    midi_note_mode = not args.clock

    try:
        service = PLPBeatService(
            device=args.device,
            bpm_min=args.bpm_min,
            bpm_max=args.bpm_max,
            osc_host=args.osc_host,
            osc_port=args.osc_port,
            enable_osc=not args.no_osc,
            enable_midi=enable_midi,
            midi_note_mode=midi_note_mode,
            midi_port_name=args.midi_port,
            debug=args.debug,
            enable_debug_server=args.debug_server and not args.no_debug_server,
            debug_ws_port=args.debug_ws_port,
            debug_http_port=args.debug_http_port,
            record_path=args.record,
        )
        service.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
