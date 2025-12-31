"""PLP-based beat tracking service for lighting control."""

from plp_beat_service.osc import OSCOutput
from plp_beat_service.service import BeatEvent, PLPBeatService
from plp_beat_service.state import LockState

# Optional MIDI support
try:
    from plp_beat_service.midi import MIDIOutput
except ImportError:
    MIDIOutput = None  # type: ignore

__all__ = ["PLPBeatService", "OSCOutput", "MIDIOutput", "BeatEvent", "LockState"]
