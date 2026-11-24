#!/usr/bin/env python3
"""
gsf_info.py - Inspect GSF files and print information based on flags.

This tool provides various options to inspect and analyze GSF (Generic Sensor Format)
files, including datagram summaries, ping headers, depth statistics, and attitude records.
"""

import argparse
import os
import sys
import struct
import numpy as np
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from readers.base import (
    GSFREADER,
    HEADER,
    SWATH_BATHYMETRY,
    ATTITUDE,
    SOUND_VELOCITY_PROFILE,
    PROCESSING_PARAMETERS,
)

# Import utility functions - handle both relative and absolute imports
try:
    from .sensor_specific import (
        is_sensor_subrecord_id,
        print_sensor_specific_report,
        sensor_subrecord_name,
    )
    from .utils import (
        parse_scale_factors,
        scale_factor_fingerprint,
        scan_subrecords,
        SCALED_ARRAY_IDS,
    )
except ImportError:
    # Fallback for when script is run directly
    sys.path.insert(0, str(Path(__file__).parent))
    from sensor_specific import (
        is_sensor_subrecord_id,
        print_sensor_specific_report,
        sensor_subrecord_name,
    )
    from utils import (
        parse_scale_factors,
        scale_factor_fingerprint,
        scan_subrecords,
        SCALED_ARRAY_IDS,
    )

# ------------------------------------------------------------------------------
# Mapping of SWATH_BATHY subrecord IDs → names/attribute keys on datagram
#
# This dictionary maps subrecord ID numbers to their corresponding attribute
# names as used in the bundled GSF reader. Used for displaying subrecord information
# in verbose output modes.
RECORD_NAMES = {
    1:  "HEADER",
    2:  "SWATH_BATHYMETRY",
    3:  "SOUND_VELOCITY_PROFILE",
    4:  "PROCESSING_PARAMETERS",
    5:  "SENSOR_PARAMETERS",
    6:  "COMMENT",
    7:  "HISTORY",
    8:  "NAVIGATION_ERROR",
    9:  "SWATH_BATHY_SUMMARY",
    10: "SINGLE_BEAM_SOUNDING",
    11: "HV_NAVIGATION_ERROR",
    12: "ATTITUDE",
}

# SWATH_BATHY subrecord IDs (GSF 03.11 gsf.h)
subrecord_names = {
    0:   "UNKNOWN",
    100: "SCALE_FACTORS",
    1:   "DEPTH_ARRAY",
    2:   "ACROSS_TRACK_ARRAY",
    3:   "ALONG_TRACK_ARRAY",
    4:   "TRAVEL_TIME_ARRAY",
    5:   "BEAM_ANGLE_ARRAY",
    6:   "MEAN_CAL_AMPLITUDE_ARRAY",
    7:   "MEAN_REL_AMPLITUDE_ARRAY",
    8:   "ECHO_WIDTH_ARRAY",
    9:   "QUALITY_FACTOR_ARRAY",
    10:  "RECEIVE_HEAVE_ARRAY",
    11:  "DEPTH_ERROR_ARRAY",
    12:  "ACROSS_TRACK_ERROR_ARRAY",
    13:  "ALONG_TRACK_ERROR_ARRAY",
    14:  "NOMINAL_DEPTH_ARRAY",
    15:  "QUALITY_FLAGS_ARRAY",
    16:  "BEAM_FLAGS_ARRAY",
    17:  "SIGNAL_TO_NOISE_ARRAY",
    18:  "BEAM_ANGLE_FORWARD_ARRAY",
    19:  "VERTICAL_ERROR_ARRAY",
    20:  "HORIZONTAL_ERROR_ARRAY",
    21:  "INTENSITY_SERIES_ARRAY",
    22:  "SECTOR_NUMBER_ARRAY",
    23:  "DETECTION_INFO_ARRAY",
    24:  "INCIDENT_BEAM_ADJ_ARRAY",
    25:  "SYSTEM_CLEANING_ARRAY",
    26:  "DOPPLER_CORRECTION_ARRAY",
    27:  "SONAR_VERT_UNCERT_ARRAY",
    28:  "SONAR_HORZ_UNCERT_ARRAY",
    29:  "DETECTION_WINDOW_ARRAY",
    30:  "MEAN_ABS_COEF_ARRAY",
    31:  "TVG_ARRAY",
}

ARRAY_SUBRECORD_IDS = set(range(1, 32)) | {100}
SENSOR_SUBRECORD_MIN_ID = 102
KNOWN_SENSOR_SUBRECORD_MAX_ID = 157

KNOWN_FIELD_SIZES = {0x00, 0x10, 0x20, 0x40}


def _subrecord_label(sid: int) -> str:
    if sid in subrecord_names:
        return subrecord_names[sid]
    return sensor_subrecord_name(sid)


def _is_sensor_subrecord(sid: int) -> bool:
    return is_sensor_subrecord_id(sid)


def _format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _pct(count: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * count / total:5.1f}%"


def _detail_mode(args: argparse.Namespace) -> bool:
    return any(
        (
            args.list,
            args.positions,
            args.depths,
            args.depthStats,
            args.attitude,
            args.summary,
            args.pingHeader,
            args.pingHeaderVerbose,
            args.scaleFactors,
            args.sensorSpecific,
        )
    )


def _subrecord_note(sid: int, payload_lens: list, brb_bits: Optional[int]) -> str:
    notes = []
    if sid == 11 or sid == 12 or sid == 13:
        notes.append("obsolete")
    if sid == 21 and brb_bits is not None:
        notes.append(f"{brb_bits}-bit backscatter")
    if sid == 100:
        notes.append("scale/offset table")
    if payload_lens:
        mn, mx = min(payload_lens), max(payload_lens)
        if mn == mx:
            notes.append(f"payload {mn} B")
        else:
            notes.append(f"payload {mn}–{mx} B")
    if sid > KNOWN_SENSOR_SUBRECORD_MAX_ID:
        notes.append("vendor extension")
    return ", ".join(notes)


def print_file_overview(
    filename: str,
    file_size: int,
    gsf_version: Optional[str],
    datagram_counts: dict,
    swath_ping_count: int,
    subrecord_counts: Counter,
    sensor_payload_lens: dict,
    swath_meta: dict,
) -> None:
    """Print the default human-readable GSF file overview."""
    print("=== GSF File Overview ===")
    print(f"File          : {filename}")
    print(f"Size          : {_format_bytes(file_size)}")
    if gsf_version:
        print(f"GSF version   : {gsf_version.strip()}")

    total_dg = sum(datagram_counts.values())
    print(f"Datagrams     : {total_dg:,}")

    print("\n=== Datagram Records ===")
    print(f"  {'Type':32}  {'Count':>10}")
    print(f"  {'-'*32}  {'-'*10}")
    for rid in sorted(datagram_counts):
        name = RECORD_NAMES.get(rid, f"UNKNOWN ({rid})")
        print(f"  {name:32}  {datagram_counts[rid]:>10,}")

    if swath_ping_count:
        print("\n=== Swath Bathymetry ===")
        print(f"  Pings              : {swath_ping_count:,}")
        if swath_meta.get("time_start") and swath_meta.get("time_end"):
            print(
                f"  Time range         : "
                f"{swath_meta['time_start']} .. {swath_meta['time_end']}"
            )
        if swath_meta.get("lat_min") is not None:
            print(
                f"  Latitude  (°)      : "
                f"{swath_meta['lat_min']:.7f} .. {swath_meta['lat_max']:.7f}"
            )
            print(
                f"  Longitude (°)      : "
                f"{swath_meta['lon_min']:.7f} .. {swath_meta['lon_max']:.7f}"
            )
        beams = swath_meta.get("beam_counts", set())
        if beams:
            if len(beams) == 1:
                print(f"  Beams per ping     : {next(iter(beams))}")
            else:
                print(
                    f"  Beams per ping     : "
                    f"{min(beams)} .. {max(beams)} ({len(beams)} distinct)"
                )
        if swath_meta.get("has_checksum") is not None:
            print(
                f"  Datagram checksum  : "
                f"{'yes' if swath_meta['has_checksum'] else 'no'}"
            )
        if swath_meta.get("brb_bits"):
            print(
                f"  Backscatter (BRB)  : present, "
                f"{swath_meta['brb_bits']}-bit samples"
            )
        elif subrecord_counts.get(21):
            print("  Backscatter (BRB)  : present")

    array_ids = sorted(
        sid for sid in subrecord_counts if sid in ARRAY_SUBRECORD_IDS or sid == 0
    )
    if array_ids and swath_ping_count:
        print("\n=== Swath Subrecords (array / metadata) ===")
        print(
            f"  {'ID':>4}  {'Name':36}  {'Count':>8}  "
            f"{'% pings':>8}  Notes"
        )
        print(f"  {'-'*4}  {'-'*36}  {'-'*8}  {'-'*8}  {'-'*20}")
        for sid in array_ids:
            cnt = subrecord_counts[sid]
            note = _subrecord_note(
                sid,
                sensor_payload_lens.get(sid, []),
                swath_meta.get("brb_bits"),
            )
            print(
                f"  {sid:4d}  {_subrecord_label(sid):36}  {cnt:8,}  "
                f"{_pct(cnt, swath_ping_count):>8}  {note}"
            )

    sensor_ids = sorted(
        sid for sid in subrecord_counts
        if _is_sensor_subrecord(sid) and sid not in ARRAY_SUBRECORD_IDS and sid != 0
    )
    if sensor_ids and swath_ping_count:
        print("\n=== Sensor-Specific Subrecords ===")
        print(
            f"  {'ID':>4}  {'Name':36}  {'Count':>8}  "
            f"{'% pings':>8}  Notes"
        )
        print(f"  {'-'*4}  {'-'*36}  {'-'*8}  {'-'*8}  {'-'*20}")
        for sid in sensor_ids:
            cnt = subrecord_counts[sid]
            note = _subrecord_note(sid, sensor_payload_lens.get(sid, []), None)
            print(
                f"  {sid:4d}  {_subrecord_label(sid):36}  {cnt:8,}  "
                f"{_pct(cnt, swath_ping_count):>8}  {note}"
            )

    extras = []
    if datagram_counts.get(ATTITUDE):
        extras.append(f"ATTITUDE samples: {datagram_counts[ATTITUDE]:,}")
    if datagram_counts.get(SOUND_VELOCITY_PROFILE):
        extras.append(
            f"SOUND_VELOCITY_PROFILE: {datagram_counts[SOUND_VELOCITY_PROFILE]}"
        )
    if datagram_counts.get(PROCESSING_PARAMETERS):
        extras.append(
            f"PROCESSING_PARAMETERS: {datagram_counts[PROCESSING_PARAMETERS]}"
        )
    if extras:
        print("\n=== Other Records ===")
        for line in extras:
            print(f"  {line}")


def analyze_scale_factor_set(factors, ping_index: int, file_offset: int) -> list:
    """Return oddity messages for one SCALE_FACTORS payload."""
    oddities = []
    if not factors:
        oddities.append(
            f"ping {ping_index} @0x{file_offset:X}: empty SCALE_FACTORS list"
        )
        return oddities

    seen_ids = set()
    for f in factors:
        sid = f["subrecord_id"]
        name = _subrecord_label(sid)

        if sid in seen_ids:
            oddities.append(
                f"ping {ping_index} @0x{file_offset:X}: duplicate scale factor "
                f"for {name} ({sid})"
            )
        seen_ids.add(sid)

        if f["multiplier"] == 0:
            oddities.append(
                f"ping {ping_index} @0x{file_offset:X}: {name} ({sid}) "
                f"has multiplier=0"
            )
        if f["field_size"] not in KNOWN_FIELD_SIZES:
            oddities.append(
                f"ping {ping_index} @0x{file_offset:X}: {name} ({sid}) "
                f"has unusual field size 0x{f['field_size']:02X}"
            )
        if sid not in subrecord_names and sid < 100:
            oddities.append(
                f"ping {ping_index} @0x{file_offset:X}: scale factor for "
                f"unrecognized array id {sid}"
            )
        # Very large multipliers can indicate bad packing / endian issues.
        if abs(f["multiplier"]) > 1_000_000_000:
            oddities.append(
                f"ping {ping_index} @0x{file_offset:X}: {name} ({sid}) "
                f"has extreme multiplier={f['multiplier']}"
            )
        if abs(f["offset"]) > 1_000_000_000:
            oddities.append(
                f"ping {ping_index} @0x{file_offset:X}: {name} ({sid}) "
                f"has extreme offset={f['offset']}"
            )
    return oddities


def print_scale_factor_analysis(events, total_pings: int, oddities: list) -> None:
    """Pretty-print scale-factor coverage, unique sets, transitions, and oddities."""
    print("\n=== Scale Factor Analysis ===")
    print(f"SWATH_BATHYMETRY pings        : {total_pings}")
    print(f"Pings with SCALE_FACTORS      : {len(events)}")

    if total_pings == 0:
        print("No bathymetry pings found.")
        return

    if not events:
        print("No SCALE_FACTORS subrecords found in any ping.")
        print(
            "NOTE: GSF may omit SCALE_FACTORS after the first occurrence; "
            "absence later is normal. Complete absence is unusual."
        )
        _print_oddity_summary(oddities)
        return

    first_ping = events[0]["ping_index"]
    if first_ping > 1:
        oddities.append(
            f"first SCALE_FACTORS appears at ping {first_ping} "
            f"(pings 1..{first_ping - 1} had none)"
        )

    # Unique fingerprints and coverage spans
    unique = {}
    for ev in events:
        fp = ev["fingerprint"]
        if fp not in unique:
            unique[fp] = {
                "factors": ev["factors"],
                "count": 0,
                "first_ping": ev["ping_index"],
                "last_ping": ev["ping_index"],
                "first_offset": ev["offset"],
            }
        unique[fp]["count"] += 1
        unique[fp]["last_ping"] = ev["ping_index"]

    transitions = sum(
        1 for prev, cur in zip(events, events[1:])
        if prev["fingerprint"] != cur["fingerprint"]
    )
    print(f"Unique SCALE_FACTORS sets     : {len(unique)}")
    print(f"Scale-factor set changes      : {transitions}")

    # Per-id variability across all observed SCALE_FACTORS updates
    by_id = defaultdict(lambda: {"mult": set(), "off": set(), "size": set()})
    for ev in events:
        for f in ev["factors"]:
            sid = f["subrecord_id"]
            by_id[sid]["mult"].add(f["multiplier"])
            by_id[sid]["off"].add(f["offset"])
            by_id[sid]["size"].add(f["field_size_name"])

    print("\n-- Per-array scale-factor summary (across all updates) --")
    print(
        f"  {'ID':>4}  {'Name':32}  {'Size':8}  {'Mult values':>12}  "
        f"{'Offset range / #unique':>28}"
    )
    print(f"  {'-'*4}  {'-'*32}  {'-'*8}  {'-'*12}  {'-'*28}")
    for sid in sorted(by_id):
        info = by_id[sid]
        sizes = ",".join(sorted(info["size"]))
        mults = sorted(info["mult"])
        offs = sorted(info["off"])
        mult_txt = (
            str(mults[0]) if len(mults) == 1
            else f"{len(mults)} values [{mults[0]}..{mults[-1]}]"
        )
        if len(offs) == 1:
            off_txt = f"{offs[0]} (constant)"
        else:
            off_txt = f"{offs[0]}..{offs[-1]} ({len(offs)} unique)"
        print(
            f"  {sid:4d}  {_subrecord_label(sid):32}  {sizes:8}  "
            f"{mult_txt:>12}  {off_txt:>28}"
        )

    # Highlight what is actually changing between unique sets
    varying = [
        sid for sid, info in by_id.items()
        if len(info["mult"]) > 1 or len(info["off"]) > 1 or len(info["size"]) > 1
    ]
    if varying:
        print("\n-- What differs between unique sets --")
        for sid in sorted(varying):
            info = by_id[sid]
            parts = []
            if len(info["mult"]) > 1:
                parts.append(f"{len(info['mult'])} multipliers")
            if len(info["off"]) > 1:
                offs = sorted(info["off"])
                parts.append(
                    f"{len(info['off'])} offsets ({offs[0]}..{offs[-1]})"
                )
            if len(info["size"]) > 1:
                parts.append(f"sizes={sorted(info['size'])}")
            print(f"  {_subrecord_label(sid)} ({sid}): " + ", ".join(parts))
    else:
        print("\nAll unique sets are identical in multipliers/offsets/sizes.")

    # Show one representative full table (first set)
    first = events[0]
    print(
        f"\n-- Representative SCALE_FACTORS table "
        f"(ping {first['ping_index']} @0x{first['offset']:X}) --"
    )
    print(
        f"  {'ID':>4}  {'Name':32}  {'Size':8}  {'Multiplier':>12}  {'Offset':>10}"
    )
    print(f"  {'-'*4}  {'-'*32}  {'-'*8}  {'-'*12}  {'-'*10}")
    for f in first["factors"]:
        print(
            f"  {f['subrecord_id']:4d}  "
            f"{_subrecord_label(f['subrecord_id']):32}  "
            f"{f['field_size_name']:8}  "
            f"{f['multiplier']:12d}  "
            f"{f['offset']:10d}"
        )

    # Presence density
    if len(events) == total_pings:
        print("\nSCALE_FACTORS present on every ping.")
    elif len(events) == 1:
        print(
            f"\nSCALE_FACTORS appears once (ping {events[0]['ping_index']}); "
            "later pings inherit that set (normal GSF behavior)."
        )
    else:
        gaps = [
            cur["ping_index"] - prev["ping_index"] - 1
            for prev, cur in zip(events, events[1:])
        ]
        gaps = [g for g in gaps if g > 0]
        if gaps:
            print(
                f"\nSCALE_FACTORS updates are frequent: "
                f"{len(events)}/{total_pings} pings, "
                f"median gap {sorted(gaps)[len(gaps)//2]} ping(s), "
                f"max gap {max(gaps)} ping(s)."
            )
        else:
            print(
                f"\nSCALE_FACTORS on consecutive pings for a stretch "
                f"({len(events)} updates)."
            )

    # File-level structural notes from the observed ID sets
    print("\n-- Structural notes --")
    notes = 0
    if 1 in by_id and 14 in by_id:
        if by_id[1]["off"] == by_id[14]["off"] and by_id[1]["mult"] == by_id[14]["mult"]:
            print(
                "  DEPTH_ARRAY and NOMINAL_DEPTH_ARRAY always share the same "
                "multiplier and offset in this file."
            )
            notes += 1
    if notes == 0:
        print("  None.")

    _print_oddity_summary(oddities)


def _print_oddity_summary(oddities: list, sample_limit: int = 8) -> None:
    print("\n-- Oddities --")
    if not oddities:
        print("  None detected.")
        return

    def category(msg: str) -> str:
        if "no SCALE_FACTORS seen yet" in msg:
            return "scaled arrays before first SCALE_FACTORS"
        if "arrays without active scale factors" in msg:
            # keep the array names in the category key
            _, _, rest = msg.partition(": arrays without active scale factors: ")
            return f"arrays without active scale factors: {rest}"
        if "multiplier=0" in msg:
            return "zero multiplier"
        if "unusual field size" in msg:
            return "unusual field size"
        if "duplicate scale factor" in msg:
            return "duplicate scale-factor id"
        if "failed to decode" in msg:
            return "SCALE_FACTORS decode failure"
        if "empty SCALE_FACTORS" in msg:
            return "empty SCALE_FACTORS list"
        if "SCALE_FACTORS subrecords in one ping" in msg:
            return "multiple SCALE_FACTORS in one ping"
        if "first SCALE_FACTORS appears" in msg:
            return "late first SCALE_FACTORS"
        return "other"

    counts = Counter(category(m) for m in oddities)
    print(f"  {len(oddities)} finding(s) in {len(counts)} categor(ies):")
    for cat, n in counts.most_common():
        print(f"    - {cat}: {n}")

    print(f"\n  Sample findings (up to {sample_limit}):")
    for msg in oddities[:sample_limit]:
        print(f"    ! {msg}")
    if len(oddities) > sample_limit:
        print(f"    ... and {len(oddities) - sample_limit} more")


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for gsf-info tool.
    
    Returns:
        argparse.Namespace: Parsed command-line arguments containing:
            - filename: Path to the GSF file to inspect
            - list: Flag to list all datagram record types
            - positions: Flag to print timestamp/lat/lon for SWATH_BATHYMETRY
            - depths: Flag to print depth arrays
            - depthStats: Flag to print depth statistics
            - attitude: Flag to print attitude records
            - summary: Flag to print datagram count summary
            - pingHeader: Flag to print ping headers
            - pingHeaderVerbose: Flag to print verbose ping headers with subrecords
    """
    p = argparse.ArgumentParser(
        description=(
            "Inspect GSF files. With no options, prints a readable file overview "
            "(datagram counts, subrecord summary, sensor-specific records)."
        )
    )
    p.add_argument("filename", help="Path to the GSF file")
    p.add_argument("--list", action="store_true", help="List all datagram record types")
    p.add_argument("--positions", action="store_true", help="Print timestamp/lat/lon for SWATH_BATHYMETRY")
    p.add_argument("--depths", action="store_true", help="Print depth arrays from SWATH_BATHYMETRY")
    p.add_argument("--depthStats", action="store_true", help="Print min/max/mean stats and beam flag summary")
    p.add_argument("--attitude", action="store_true", help="Print attitude records")
    p.add_argument("--summary", action="store_true", help="Print summary of datagram counts")
    p.add_argument("--pingHeader", action="store_true", help="Print full SWATH_BATHYMETRY ping headers")
    p.add_argument(
        "--pingHeaderVerbose",
        action="store_true",
        help="Print ping headers + decoded sub‑records payloads"
    )
    p.add_argument(
        "--scaleFactors",
        action="store_true",
        help="Analyze SCALE_FACTORS subrecords across pings and flag oddities",
    )
    p.add_argument(
        "--sensorSpecific",
        action="store_true",
        help=(
            "Decode sensor/vendor-specific subrecords (ID >= 102) and print "
            "field summaries (KMALL, EM3/EM4, R2Sonic, etc.)"
        ),
    )
    return p.parse_args()

def main() -> None:
    """
    Main entry point for gsf-info tool.
    
    Reads a GSF file and prints information based on the provided command-line flags.
    Supports various output modes including datagram summaries, ping headers,
    depth statistics, and attitude records.
    
    Exits with code 1 if the file is not found or if errors occur during reading.
    """
    args = parse_args()
    overview_mode = not _detail_mode(args)

    if not os.path.exists(args.filename):
        print(f"Error: File '{args.filename}' not found.", file=sys.stderr)
        sys.exit(1)

    file_size = os.path.getsize(args.filename)
    fh = open(args.filename, "rb")
    reader = GSFREADER(args.filename)

    datagram_counts = defaultdict(int)
    valid_depth_pings = 0
    empty_depth_pings = 0
    scale_factor_events = []
    scale_factor_oddities = []
    swath_ping_index = 0
    saw_first_sf = False
    active_sf_ids = set()

    sensor_counts = Counter()
    sensor_samples = {}

    gsf_version = None
    overview_swath_count = 0
    subrecord_counts = Counter()
    sensor_payload_lens = defaultdict(list)
    swath_meta = {
        "time_start": None,
        "time_end": None,
        "lat_min": None,
        "lat_max": None,
        "lon_min": None,
        "lon_max": None,
        "beam_counts": set(),
        "has_checksum": None,
        "brb_bits": None,
    }

    # ping header struct (same as in pygsf)
    ping_hdr_fmt = ">llll5hlH3h2Hlllh"
    ping_hdr_size = struct.calcsize(ping_hdr_fmt)

    while reader.moreData():
        try:
            nbytes, recid, dg = reader.readDatagram()
        except Exception as e:
            print(f"Error reading datagram: {e}", file=sys.stderr)
            break

        datagram_counts[recid] += 1
        name = RECORD_NAMES.get(recid, f"UNKNOWN ({recid})")

        if overview_mode and recid == HEADER and gsf_version is None:
            try:
                dg.read()
                gsf_version = dg.version
            except Exception as e:
                print(f"Error reading HEADER: {e}", file=sys.stderr)

        if (overview_mode or args.sensorSpecific) and recid == SWATH_BATHYMETRY:
            overview_swath_count += 1
            fh.seek(dg.offset)
            raw = fh.read(nbytes)
            _, ident = struct.unpack(">II", raw[:8])
            has_checksum = ((ident >> 31) & 1) == 1
            if swath_meta["has_checksum"] is None:
                swath_meta["has_checksum"] = has_checksum

            start = 8 + (4 if has_checksum else 0)
            hdr = struct.unpack(ping_hdr_fmt, raw[start:start + ping_hdr_size])
            t_sec, t_nsec = hdr[0], hdr[1]
            ts = datetime.fromtimestamp(
                t_sec + t_nsec / 1e9, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            lon, lat = hdr[2] / 1e7, hdr[3] / 1e7
            nbeams = hdr[4]

            if swath_meta["time_start"] is None:
                swath_meta["time_start"] = ts
            swath_meta["time_end"] = ts

            swath_meta["beam_counts"].add(nbeams)
            for bound_key, value in (
                ("lat_min", lat),
                ("lat_max", lat),
                ("lon_min", lon),
                ("lon_max", lon),
            ):
                current = swath_meta[bound_key]
                if current is None:
                    swath_meta[bound_key] = value
                elif bound_key.endswith("_min"):
                    swath_meta[bound_key] = min(current, value)
                else:
                    swath_meta[bound_key] = max(current, value)

            for sid, payload in scan_subrecords(raw, ping_hdr_size):
                if overview_mode:
                    subrecord_counts[sid] += 1
                    sensor_payload_lens[sid].append(len(payload))
                    if sid == 21 and swath_meta["brb_bits"] is None and payload:
                        swath_meta["brb_bits"] = payload[0]
                if args.sensorSpecific and is_sensor_subrecord_id(sid):
                    sensor_counts[sid] += 1
                    if sid not in sensor_samples:
                        sensor_samples[sid] = (
                            overview_swath_count,
                            dg.offset,
                            payload,
                        )

        if args.list:
            print(name)

        # --- scale factor analysis ---
        if args.scaleFactors and recid == SWATH_BATHYMETRY:
            swath_ping_index += 1
            fh.seek(dg.offset)
            raw = fh.read(nbytes)
            subs = scan_subrecords(raw, ping_hdr_size)
            sf_payloads = [payload for sid, payload in subs if sid == 100]
            array_ids = {sid for sid, _ in subs if sid in SCALED_ARRAY_IDS}

            if not sf_payloads:
                if not saw_first_sf:
                    if array_ids:
                        scale_factor_oddities.append(
                            f"ping {swath_ping_index} @0x{dg.offset:X}: "
                            f"scaled arrays present "
                            f"({', '.join(_subrecord_label(s) for s in sorted(array_ids))}) "
                            f"but no SCALE_FACTORS seen yet"
                        )
                elif array_ids and not array_ids.issubset(active_sf_ids):
                    missing = sorted(array_ids - active_sf_ids)
                    scale_factor_oddities.append(
                        f"ping {swath_ping_index} @0x{dg.offset:X}: "
                        f"arrays without active scale factors: "
                        f"{', '.join(_subrecord_label(s) for s in missing)}"
                    )
            else:
                if len(sf_payloads) > 1:
                    scale_factor_oddities.append(
                        f"ping {swath_ping_index} @0x{dg.offset:X}: "
                        f"{len(sf_payloads)} SCALE_FACTORS subrecords in one ping"
                    )
                for payload in sf_payloads:
                    try:
                        factors = parse_scale_factors(payload)
                    except ValueError as e:
                        scale_factor_oddities.append(
                            f"ping {swath_ping_index} @0x{dg.offset:X}: "
                            f"failed to decode SCALE_FACTORS: {e}"
                        )
                        continue
                    scale_factor_oddities.extend(
                        analyze_scale_factor_set(factors, swath_ping_index, dg.offset)
                    )
                    scale_factor_events.append(
                        {
                            "ping_index": swath_ping_index,
                            "offset": dg.offset,
                            "factors": factors,
                            "fingerprint": scale_factor_fingerprint(factors),
                        }
                    )
                    active_sf_ids = {f["subrecord_id"] for f in factors}
                    saw_first_sf = True
                    missing = sorted(array_ids - active_sf_ids)
                    if missing:
                        scale_factor_oddities.append(
                            f"ping {swath_ping_index} @0x{dg.offset:X}: "
                            f"arrays without active scale factors: "
                            f"{', '.join(_subrecord_label(s) for s in missing)}"
                        )

        # --- handle pingHeader and pingHeaderVerbose ---
        if recid == SWATH_BATHYMETRY and (args.pingHeader or args.pingHeaderVerbose):
            # read raw bytes for this datagram
            fh.seek(dg.offset)
            raw = fh.read(nbytes)

            # unpack size & id / checksum
            size_word, ident = struct.unpack(">II", raw[:8])
            has_checksum = ((ident >> 31) & 1) == 1

            # unpack ping header
            start = 8 + (4 if has_checksum else 0)
            hdr = struct.unpack(ping_hdr_fmt, raw[start:start+ping_hdr_size])
            t_sec, t_nsec = hdr[0], hdr[1]
            ts = datetime.fromtimestamp(t_sec + t_nsec/1e9, tz=timezone.utc)
            lon, lat = hdr[2]/1e7, hdr[3]/1e7
            nbeams, centre, flags = hdr[4], hdr[5], hdr[6]
            tide, depthCorr = hdr[8]/100, hdr[9]/100
            heading, pitch, roll = hdr[10]/100, hdr[11]/100, hdr[12]/100
            heave, course, speed = hdr[13]/100, hdr[14]/100, hdr[15]/100
            height, sep, gpstc = hdr[16]/100, hdr[17]/100, hdr[18]/100
            reserved, spare = hdr[7], hdr[19]

            # scan subrecords
            subs = scan_subrecords(raw, ping_hdr_size)

            # print header fields
            print("\n=== SWATH_BATHYMETRY Ping Header ===")
            print(f"Timestamp            : {ts.isoformat().replace('+00:00','Z')}")
            print(f"Latitude  (°)        : {lat:.7f}")
            print(f"Longitude (°)        : {lon:.7f}")
            print(f"Num Beams            : {nbeams}")
            print(f"Centre Beam          : {centre}")
            print(f"Usable               : {flags & 1 == 0}")
            print(f"Tide Corrector   (m) : {tide:.2f}")
            print(f"Depth Corrector  (m) : {depthCorr:.2f}")
            print(f"Heading         (°)  : {heading:.2f}")
            print(f"Pitch           (°)  : {pitch:.2f}")
            print(f"Roll            (°)  : {roll:.2f}")
            print(f"Heave           (m)  : {heave:.2f}")
            print(f"Course          (°)  : {course:.2f}")
            print(f"Speed        (knots): {speed:.2f}")
            print(f"Height          (m)  : {height:.3f}")
            print(f"Separation      (m)  : {sep:.3f}")
            print(f"GPS Tide Corr.  (m)  : {gpstc:.3f}")
            print(f"Reserved             : {reserved}")
            print(f"Spare                : {spare}")
            print(f"Subrecords           : {len(subs)}")
            if subs:
                labeled = ", ".join(
                    f"{sid}({subrecord_names.get(sid,'UNKNOWN')})"
                    for sid, _ in subs
                )
                print(f"Subrecord IDs        : {labeled}")

            # decode & print each subrecord’s values
            if args.pingHeaderVerbose and subs:
                # let pygsf decode into dg.*
                reader.scalefactorsd = dg.read(reader.scalefactorsd)
                print("\n  -- Decoded Subrecord Contents --")
                for sid, _ in subs:
                    key = subrecord_names.get(sid)
                    if key and hasattr(dg, key):
                        arr = getattr(dg, key)
                        print(f"  {key:30}: {arr}")
                    else:
                        print(f"  {sid:<3} UNKNOWN or not decoded by base library")

        # --- existing functionality preserved below ---
        if args.positions and recid == SWATH_BATHYMETRY:
            try:
                dg.read(reader.scalefactorsd, headeronly=False)
                print(
                    f"Time: {dg.timestamp:.3f}, "
                    f"Lon: {dg.longitude:.7f}, "
                    f"Lat: {dg.latitude:.7f}"
                )
            except Exception as e:
                print(f"Error reading SWATH_BATHYMETRY position: {e}", file=sys.stderr)

        if (args.depths or args.depthStats) and recid == SWATH_BATHYMETRY:
            try:
                reader.scalefactorsd = dg.read(reader.scalefactorsd)
            except Exception as e:
                print(f"Error reading SWATH_BATHYMETRY datagram: {e}", file=sys.stderr)
                continue

            try:
                depths = np.array(dg.DEPTH_ARRAY)
                if depths.size == 0:
                    empty_depth_pings += 1
                    if args.depthStats:
                        print("Depth Stats – Empty depth array")
                        for fname in [
                            "ACROSS_TRACK_ARRAY", "ALONG_TRACK_ARRAY",
                            "TRAVEL_TIME_ARRAY", "BEAM_FLAGS_ARRAY",
                            "MEAN_CALIBRATED_AMPLITUDE_ARRAY",
                            "QUALITY_FLAGS_ARRAY"
                        ]:
                            if hasattr(dg, fname):
                                arr = getattr(dg, fname)
                                if isinstance(arr, (list, np.ndarray)):
                                    print(f"  {fname:30} len={len(arr)}")
                                else:
                                    print(f"  {fname:30} present but not list/ndarray")
                            else:
                                print(f"  {fname:30} not present")
                    continue

                valid_depth_pings += 1

                if args.depths:
                    print(
                        f"Depths ({depths.size}): "
                        f"{np.array2string(depths, precision=2, threshold=10)}"
                    )

                if args.depthStats:
                    dmin, dmax, dmean = (
                        np.nanmin(depths),
                        np.nanmax(depths),
                        np.nanmean(depths),
                    )
                    print(f"Depth Stats – Min: {dmin:.2f}, Max: {dmax:.2f}, Mean: {dmean:.2f}")
                    flags = np.asarray(getattr(dg, "BEAM_FLAGS_ARRAY", []))
                    if flags.size:
                        total = flags.size
                        bad = np.count_nonzero(flags)
                        good = total - bad
                        print(f"Beam Flags – Total: {total}, Good: {good}, Bad: {bad}")
                    else:
                        print("Beam Flags – Not available")

            except Exception as e:
                print(f"Error reading SWATH_BATHYMETRY depths: {e}", file=sys.stderr)

        if args.attitude and recid == ATTITUDE:
            try:
                dg.read()
                for ts, roll, pitch, heave in zip(dg.ts, dg.roll, dg.pitch, dg.heave):
                    print(f"Time: {ts:.3f}, Roll: {roll:.2f}, Pitch: {pitch:.2f}, Heave: {heave:.2f}")
            except Exception as e:
                print(f"Error reading ATTITUDE: {e}", file=sys.stderr)

    # end while

    if args.summary:
        print("\nDatagram Summary:")
        for rid, cnt in sorted(datagram_counts.items()):
            nm = RECORD_NAMES.get(rid, f"UNKNOWN ({rid})")
            print(f"{nm:30} {cnt}")

    if overview_mode:
        print_file_overview(
            args.filename,
            file_size,
            gsf_version,
            datagram_counts,
            overview_swath_count,
            subrecord_counts,
            sensor_payload_lens,
            swath_meta,
        )

    if args.depthStats:
        print("\nDepth Ping Summary:")
        print(f"Valid pings with depth: {valid_depth_pings}")
        print(f"Empty depth pings:      {empty_depth_pings}")

    if args.scaleFactors:
        print_scale_factor_analysis(
            scale_factor_events, swath_ping_index, scale_factor_oddities
        )

    if args.sensorSpecific:
        print_sensor_specific_report(
            args.filename,
            dict(sensor_counts),
            sensor_samples,
            overview_swath_count,
        )

    fh.close()


if __name__ == "__main__":
    main()
