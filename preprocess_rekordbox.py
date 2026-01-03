#!/usr/bin/env python3
"""
Preprocess rekordbox export XML to extract beat grid data.

Parses rekordbox_export.xml, filters to high-quality tracks from 4/5-star playlists
with constant BPM, and generates JSON files with ground-truth beat positions.

Usage:
    # First, copy the XML from laptop:
    scp laptop:/Users/joshlebed/Documents/rekordbox/rekordbox_export.xml .

    # Then run preprocessing:
    python preprocess_rekordbox.py rekordbox_export.xml

    # This generates JSON files in test_data/ and prints scp commands for audio
"""

import argparse
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote


def sanitize_filename(name: str) -> str:
    """Convert track name to safe filename."""
    # Lowercase, replace spaces with underscores
    name = name.lower().strip()
    # Remove or replace problematic characters
    name = re.sub(r"['\"]", "", name)
    name = re.sub(r"[^a-z0-9]+", "_", name)
    # Remove leading/trailing underscores
    name = name.strip("_")
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    return name


def parse_rekordbox_xml(xml_path: Path) -> tuple[dict, dict, dict]:
    """
    Parse rekordbox XML and return tracks, playlists, and playlist track mappings.

    Returns:
        tracks: dict mapping TrackID -> track element attributes + TEMPO data
        playlists: dict mapping playlist name -> list of track keys
        ratings: dict mapping TrackID -> rating (0-255)
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Parse all tracks from COLLECTION
    tracks = {}
    collection = root.find("COLLECTION")
    if collection is None:
        print("ERROR: No COLLECTION found in XML", file=sys.stderr)
        sys.exit(1)

    for track in collection.findall("TRACK"):
        track_id = track.get("TrackID")
        if not track_id:
            continue

        # Get TEMPO elements
        tempos = []
        for tempo in track.findall("TEMPO"):
            tempos.append(
                {
                    "inizio": float(tempo.get("Inizio", "0")),
                    "bpm": float(tempo.get("Bpm", "0")),
                    "metro": tempo.get("Metro", "4/4"),
                    "battito": int(tempo.get("Battito", "1")),
                }
            )

        tracks[track_id] = {
            "track_id": track_id,
            "name": track.get("Name", ""),
            "artist": track.get("Artist", ""),
            "average_bpm": float(track.get("AverageBpm", "0")),
            "total_time": int(track.get("TotalTime", "0")),
            "location": track.get("Location", ""),
            "rating": int(track.get("Rating", "0")),
            "tempos": tempos,
        }

    # Parse playlists
    playlists: dict[str, set[str]] = defaultdict(set)

    def traverse_playlists(node: ET.Element, path: str = "") -> None:
        name = node.get("Name", "")
        node_type = node.get("Type", "")

        if node_type == "1":  # Playlist node (contains tracks)
            for track_ref in node.findall("TRACK"):
                key = track_ref.get("Key")
                if key:
                    playlists[name].add(key)
        elif node_type == "0":  # Folder node
            for child in node.findall("NODE"):
                traverse_playlists(child, f"{path}/{name}" if path else name)

    playlists_root = root.find("PLAYLISTS")
    if playlists_root is not None:
        for node in playlists_root.findall("NODE"):
            traverse_playlists(node)

    return tracks, dict(playlists)


def has_constant_bpm(track: dict, tolerance: float = 0.5) -> bool:
    """Check if track has constant BPM (all TEMPO elements within tolerance)."""
    tempos = track.get("tempos", [])
    if not tempos:
        return False
    if len(tempos) == 1:
        return True

    bpms = [t["bpm"] for t in tempos]
    return max(bpms) - min(bpms) <= tolerance


def compute_beats(first_beat: float, bpm: float, duration: float) -> list[float]:
    """Compute all beat positions for a track."""
    if bpm <= 0 or duration <= 0:
        return []

    beat_interval = 60.0 / bpm
    beats = []
    t = first_beat
    while t < duration:
        beats.append(round(t, 4))
        t += beat_interval
    return beats


def get_file_path(location: str) -> str:
    """Extract file path from rekordbox Location URL."""
    # Location format: file://localhost/Users/joshlebed/Music/...
    if location.startswith("file://localhost"):
        return unquote(location.replace("file://localhost", ""))
    return unquote(location)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess rekordbox XML for beat grid data")
    parser.add_argument("xml_path", type=Path, help="Path to rekordbox_export.xml")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("test_data"), help="Output directory for JSON files"
    )
    parser.add_argument("--count", type=int, default=20, help="Number of tracks to select")
    parser.add_argument("--min-bpm", type=float, default=115, help="Minimum BPM to include")
    parser.add_argument("--max-bpm", type=float, default=160, help="Maximum BPM to include")
    parser.add_argument("--bin-size", type=float, default=5, help="BPM bin size for sampling")
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducible sampling"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without writing files"
    )
    args = parser.parse_args()

    random.seed(args.seed)

    if not args.xml_path.exists():
        print(f"ERROR: File not found: {args.xml_path}", file=sys.stderr)
        print("\nTo get the file, run:", file=sys.stderr)
        print(
            "  scp laptop:/Users/joshlebed/Documents/rekordbox/rekordbox_export.xml .",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Parsing {args.xml_path}...")
    tracks, playlists = parse_rekordbox_xml(args.xml_path)
    print(f"Found {len(tracks)} tracks in collection")
    print(f"Found {len(playlists)} playlists")

    # Get tracks from 4-star and 5-star playlists
    target_playlists = ["4 star", "5 star", "4star", "5star"]
    high_rated_ids: set[str] = set()

    for name, track_ids in playlists.items():
        if any(target.lower() in name.lower() for target in target_playlists):
            print(f"  Using playlist '{name}' with {len(track_ids)} tracks")
            high_rated_ids.update(track_ids)

    # Also include tracks with high rating regardless of playlist
    for track_id, track in tracks.items():
        if track["rating"] >= 200:  # 4-star = 200, 5-star = 255
            high_rated_ids.add(track_id)

    print(f"Total high-rated tracks: {len(high_rated_ids)}")

    # Filter to constant BPM and valid range
    candidates = []
    for track_id in high_rated_ids:
        track = tracks.get(track_id)
        if not track:
            continue
        if not has_constant_bpm(track):
            continue
        bpm = track["average_bpm"]
        if not (args.min_bpm <= bpm <= args.max_bpm):
            continue
        if not track["tempos"]:
            continue
        if "soulseek" not in track["location"]:
            # Skip non-soulseek tracks (may not be accessible)
            continue
        candidates.append(track)

    print(
        f"Candidates with constant BPM in range [{args.min_bpm}, {args.max_bpm}]: {len(candidates)}"
    )

    # Bin by BPM and sample
    bins: dict[int, list[dict]] = defaultdict(list)
    for track in candidates:
        bin_idx = int(track["average_bpm"] // args.bin_size)
        bins[bin_idx].append(track)

    print(f"\nBPM distribution (bin size {args.bin_size}):")
    for bin_idx in sorted(bins.keys()):
        bin_start = bin_idx * args.bin_size
        bin_end = bin_start + args.bin_size
        print(f"  {bin_start:.0f}-{bin_end:.0f}: {len(bins[bin_idx])} tracks")

    # Sample from each bin
    selected = []
    tracks_per_bin = max(1, args.count // len(bins)) if bins else 0

    for bin_idx in sorted(bins.keys()):
        bin_tracks = bins[bin_idx]
        random.shuffle(bin_tracks)
        selected.extend(bin_tracks[:tracks_per_bin])

    # If we need more, sample randomly from remaining
    if len(selected) < args.count:
        remaining = [t for t in candidates if t not in selected]
        random.shuffle(remaining)
        selected.extend(remaining[: args.count - len(selected)])

    # Trim if we have too many
    selected = selected[: args.count]
    selected.sort(key=lambda t: t["average_bpm"])

    print(f"\nSelected {len(selected)} tracks:")
    for track in selected:
        print(f"  {track['average_bpm']:.0f} BPM: {track['artist']} - {track['name']}")

    # Create output directory
    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    # Generate JSON files and scp commands
    scp_commands = []
    for track in selected:
        bpm = round(track["average_bpm"])
        safe_artist = sanitize_filename(track["artist"])
        safe_name = sanitize_filename(track["name"])
        base_name = f"{safe_artist}_{safe_name}_{bpm}"

        # Get first beat position
        first_tempo = track["tempos"][0]
        first_beat = first_tempo["inizio"]
        tempo_bpm = first_tempo["bpm"]
        metro = first_tempo["metro"]

        # Compute all beats
        duration = track["total_time"]
        beats = compute_beats(first_beat, tempo_bpm, duration)

        # Build JSON data
        original_path = get_file_path(track["location"])
        audio_filename = f"{base_name}.mp3"

        data = {
            "name": track["name"],
            "artist": track["artist"],
            "bpm": tempo_bpm,
            "duration_sec": duration,
            "time_signature": metro,
            "first_beat_sec": first_beat,
            "beat_interval_sec": round(60.0 / tempo_bpm, 6),
            "total_beats": len(beats),
            "beats": beats,
            "audio_file": audio_filename,
            "source": {
                "track_id": track["track_id"],
                "original_path": original_path,
            },
        }

        json_path = args.output_dir / f"{base_name}.json"
        audio_path = args.output_dir / audio_filename

        if args.dry_run:
            print(f"\nWould write: {json_path}")
            print(f"  {len(beats)} beats from {first_beat:.3f}s to {beats[-1]:.3f}s")
        else:
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Wrote: {json_path}")

        # Generate scp command
        scp_cmd = f'scp "laptop:{original_path}" "{audio_path}"'
        scp_commands.append(scp_cmd)

    # Print scp commands
    print("\n" + "=" * 60)
    print("Run these commands to copy audio files:")
    print("=" * 60 + "\n")
    for cmd in scp_commands:
        print(cmd)

    # Also write a script
    if not args.dry_run:
        script_path = args.output_dir / "fetch_audio.sh"
        with open(script_path, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("# Fetch audio files from laptop\n")
            f.write("# Run: bash test_data/fetch_audio.sh\n\n")
            f.write("set -e\n\n")
            for cmd in scp_commands:
                f.write(cmd + "\n")
            f.write('\necho "Done! Fetched all audio files."\n')
        script_path.chmod(0o755)
        print(f"\nAlso wrote: {script_path}")
        print("Run with: bash test_data/fetch_audio.sh")


if __name__ == "__main__":
    main()
