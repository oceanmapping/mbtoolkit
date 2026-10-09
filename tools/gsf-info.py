#!/usr/bin/env python3
"""
gsf-info.py - Inspect GSF files and print information based on flags.

This tool provides various options to inspect and analyze GSF (Generic Sensor Format)
files, including datagram summaries, ping headers, depth statistics, and attitude records.
"""

import argparse
import os
import sys
import struct
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from readers.base import GSFREADER, SWATH_BATHYMETRY, ATTITUDE

# Import utility functions - handle both relative and absolute imports
try:
    from .utils import scan_subrecords
except ImportError:
    # Fallback for when script is run directly
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import scan_subrecords

# ------------------------------------------------------------------------------
# Mapping of SWATH_BATHY subrecord IDs → names/attribute keys on datagram
#
# This dictionary maps subrecord ID numbers to their names, which are the
# GSF_SWATH_BATHY_SUBRECORD_* constants in the GSF 3.11 library's gsf.h with
# that prefix removed. The bundled GSF reader uses the same names for the
# attributes it decodes, so they also serve as attribute keys on the datagram.
# Used for displaying subrecord information in verbose output modes.
subrecord_names = {
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
    # sensor‑specific IDs omitted for brevity...
}

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
        description="Inspect GSF files and print information based on flags."
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
    args = p.parse_args()
    if not args.list and not args.positions and not args.depths and not args.depthStats and not args.attitude and not args.summary and not args.pingHeader and not args.pingHeaderVerbose:
        args.summary = True
    return args

def main() -> None:
    """
    Main entry point for gsf-info tool.
    
    Reads a GSF file and prints information based on the provided command-line flags.
    Supports various output modes including datagram summaries, ping headers,
    depth statistics, and attitude records.
    
    Exits with code 1 if the file is not found or if errors occur during reading.
    """
    args = parse_args()

    if not os.path.exists(args.filename):
        print(f"Error: File '{args.filename}' not found.", file=sys.stderr)
        sys.exit(1)

    fh = open(args.filename, "rb")
    reader = GSFREADER(args.filename)

    recordnames = {
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
        12: "ATTITUDE"
    }

    datagram_counts = defaultdict(int)
    valid_depth_pings = 0
    empty_depth_pings = 0

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
        name = recordnames.get(recid, f"UNKNOWN ({recid})")

        if args.list:
            print(name)

        # --- handle pingHeader and pingHeaderVerbose ---
        if recid == SWATH_BATHYMETRY and (args.pingHeader or args.pingHeaderVerbose):
            # read raw bytes for this datagram
            fh.seek(dg.offset)
            raw = fh.read(nbytes + 8)

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
                    if hasattr(dg, 'BEAM_FLAGS_ARRAY') and dg.BEAM_FLAGS_ARRAY:
                        flags = np.array(dg.BEAM_FLAGS_ARRAY)
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
            nm = recordnames.get(rid, f"UNKNOWN ({rid})")
            print(f"{nm:30} {cnt}")

    if args.depthStats:
        print("\nDepth Ping Summary:")
        print(f"Valid pings with depth: {valid_depth_pings}")
        print(f"Empty depth pings:      {empty_depth_pings}")

    fh.close()


if __name__ == "__main__":
    main()
