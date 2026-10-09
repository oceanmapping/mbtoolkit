#!/usr/bin/env python3
"""
gsf_info.py - Inspect GSF files and print information based on flags.

This tool provides various options to inspect and analyze GSF (Generic Sensor Format)
files, including datagram summaries, ping headers, depth statistics, and attitude records.
"""

import argparse
import os
import sys
import numpy as np
from collections import defaultdict

from GSFU import BEAM_ARRAY_SUBRECORD_IDS, RecordType, gsf

# Import utility functions - handle both relative and absolute imports
try:
    from .utils import ping_header_size, posix_seconds, scan_subrecords
except ImportError:
    # Fallback for when script is run directly
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import ping_header_size, posix_seconds, scan_subrecords

# ------------------------------------------------------------------------------
# Mapping of SWATH_BATHY subrecord IDs → names/attribute keys on datagram
#
# This dictionary maps subrecord ID numbers to their corresponding attribute
# names as used in the bundled GSF reader. Used for displaying subrecord information
# in verbose output modes.
subrecord_names = {
    100: "SCALE_FACTORS",
    1:   "DEPTH_ARRAY",
    2:   "NOMINAL_DEPTH_ARRAY",
    3:   "ACROSS_TRACK_ARRAY",
    4:   "ALONG_TRACK_ARRAY",
    5:   "TRAVEL_TIME_ARRAY",
    6:   "BEAM_ANGLE_ARRAY",
    7:   "MEAN_CALIBRATED_AMPLITUDE_ARRAY",
    8:   "MEAN_RELATIVE_AMPLITUDE_ARRAY",
    9:   "ECHO_WIDTH_ARRAY",
    10:  "QUALITY_FACTOR_ARRAY",
    11:  "RECEIVE_HEAVE_ARRAY",
    12:  "DEPTH_ERROR_ARRAY",
    13:  "ACROSS_TRACK_ERROR_ARRAY",
    14:  "ALONG_TRACK_ERROR_ARRAY",
    15:  "BEAM_FLAGS_ARRAY",
    16:  "QUALITY_FLAGS_ARRAY",
    17:  "SIGNAL_TO_NOISE_ARRAY",
    18:  "BEAM_ANGLE_FORWARD_ARRAY",
    19:  "VERTICAL_ERROR_ARRAY",
    20:  "HORIZONTAL_ERROR_ARRAY",
    21:  "SECTOR_NUMBER_ARRAY",
    22:  "DETECTION_INFO_ARRAY",
    23:  "INCIDENT_BEAM_ADJUSTMENT_ARRAY",
    24:  "SYSTEM_CLEANING_ARRAY",
    25:  "DOPPLER_CORRECTION_ARRAY",
    26:  "SONAR_VERTICAL_UNCERTAINTY_ARRAY",
    27:  "SONAR_HORIZONTAL_UNCERTAINTY_ARRAY",
    28:  "DETECTION_WINDOW_ARRAY",
    29:  "MEAN_ABS_COEFF_ARRAY",
    30:  "TVG_DB_ARRAY",
    # sensor‑specific IDs omitted for brevity...
}

# Maps each beam array subrecord ID to the gsfu 'Beams' column it is decoded
# into, for printing decoded subrecord contents in verbose output modes.
beam_array_labels = {sid: label for label, sid in BEAM_ARRAY_SUBRECORD_IDS.items()}


def records_in_file_order(reader, decoded_types):
    """
    Yield every record of an indexed GSF file in file order, decoding only some types.

    Decoding every record can be slow; a file of high-rate attitude data can
    hold hundreds of thousands of attitude records. This decodes only the
    record types asked for, and yields every other record without its
    contents, in the same order the records appear in the file.

    Args:
        reader: A gsfu gsf instance whose index_file() has been called.
        decoded_types: The RecordType values whose records to decode.

    Yields:
        (record_type, byte_offset, record) tuples, where record is the
        record as decoded by gsfu, or None for a type not in decoded_types.
    """
    decoders = {rtype: reader.iter_records(rtype) for rtype in decoded_types}
    index = zip(reader.Index["RecordID"].tolist(), reader.Index["ByteOffset"].tolist())
    for recid, offset in index:
        record_type = RecordType(recid)
        if record_type in decoders:
            _type, offset, record = next(decoders[record_type])
            yield record_type, offset, record
        else:
            yield record_type, offset, None


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
    reader = gsf(args.filename)
    reader.index_file()
    record_sizes = dict(
        zip(reader.Index["ByteOffset"].tolist(), reader.Index["TotalBytes"].tolist())
    )

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
    for recid in reader.Index["RecordID"].tolist():
        datagram_counts[recid] += 1
    valid_depth_pings = 0
    empty_depth_pings = 0

    # The fixed ping header's size depends on the file's GSF version.
    ping_hdr_size = ping_header_size(reader.gsfVersion)

    # Only the record types an option needs are decoded; the summary and
    # --list come straight from the index, and every other record is passed
    # through undecoded, so that output stays in file order.
    decoded_types = set()
    if (args.positions or args.depths or args.depthStats
            or args.pingHeader or args.pingHeaderVerbose):
        decoded_types.add(RecordType.GSF_RECORD_SWATH_BATHYMETRY_PING)
    if args.attitude:
        decoded_types.add(RecordType.GSF_RECORD_ATTITUDE)
    records = records_in_file_order(reader, decoded_types)

    while True:
        try:
            record_type, offset, record = next(records)
        except StopIteration:
            break
        except Exception as e:
            print(f"Error reading datagram: {e}", file=sys.stderr)
            break

        recid = int(record_type)
        is_ping = recid == RecordType.GSF_RECORD_SWATH_BATHYMETRY_PING
        name = recordnames.get(recid, f"UNKNOWN ({recid})")

        if args.list:
            print(name)

        if is_ping and record is not None:
            beams = record["Beams"]

        # --- handle pingHeader and pingHeaderVerbose ---
        if is_ping and (args.pingHeader or args.pingHeaderVerbose):
            # read exactly this record's raw bytes, to list its subrecords
            fh.seek(offset)
            raw = fh.read(record_sizes[offset])
            subs = scan_subrecords(raw, ping_hdr_size)

            # print header fields
            print("\n=== SWATH_BATHYMETRY Ping Header ===")
            print(f"Timestamp            : {record['PingTime'].replace('+00:00', 'Z')}")
            print(f"Latitude  (°)        : {record['Latitude_deg']:.7f}")
            print(f"Longitude (°)        : {record['Longitude_deg']:.7f}")
            print(f"Num Beams            : {record['NumberBeams']}")
            print(f"Centre Beam          : {record['CenterBeam']}")
            print(f"Usable               : {record['PingFlags'] & 1 == 0}")
            print(f"Tide Corrector   (m) : {record['TideCorrector_m']:.2f}")
            print(f"Depth Corrector  (m) : {record['DepthCorrector_m']:.2f}")
            print(f"Heading         (°)  : {record['Heading_deg']:.2f}")
            print(f"Pitch           (°)  : {record['Pitch_deg']:.2f}")
            print(f"Roll            (°)  : {record['Roll_deg']:.2f}")
            print(f"Heave           (m)  : {record['Heave_m']:.2f}")
            print(f"Course          (°)  : {record['Course_deg']:.2f}")
            print(f"Speed        (knots): {record['Speed_kn']:.2f}")
            print(f"Height          (m)  : {record['Height_m']:.3f}")
            print(f"Separation      (m)  : {record['SEP_m']:.3f}")
            print(f"GPS Tide Corr.  (m)  : {record['GPSTideCorrector_m']:.3f}")
            print(f"Subrecords           : {len(subs)}")
            if subs:
                labeled = ", ".join(
                    f"{sid}({subrecord_names.get(sid,'UNKNOWN')})"
                    for sid, _ in subs
                )
                print(f"Subrecord IDs        : {labeled}")

            # print each decoded beam array, under its gsfu column label
            if args.pingHeaderVerbose and subs:
                print("\n  -- Decoded Subrecord Contents --")
                for sid, _ in subs:
                    label = beam_array_labels.get(sid)
                    if label is not None and beams[label] is not None:
                        print(f"  {label:30}: {beams[label]}")
                    else:
                        print(f"  {sid:<3} UNKNOWN or not decoded by gsfu")

        # --- existing functionality preserved below ---
        if args.positions and is_ping:
            print(
                f"Time: {posix_seconds(record['PingTime']):.3f}, "
                f"Lon: {record['Longitude_deg']:.7f}, "
                f"Lat: {record['Latitude_deg']:.7f}"
            )

        if (args.depths or args.depthStats) and is_ping:
            # A ping without a depth array is counted as an empty one.
            depths = beams["Depth_m"] if beams["Depth_m"] is not None else np.array([])
            if depths.size == 0:
                empty_depth_pings += 1
                if args.depthStats:
                    print("Depth Stats – Empty depth array")
                    for fname in [
                        "AcrossTrack_m", "AlongTrack_m",
                        "TravelTime_s", "BeamFlags",
                        "MeanCalAmplitude_dB",
                        "QualityFlags"
                    ]:
                        if beams[fname] is not None:
                            print(f"  {fname:30} len={len(beams[fname])}")
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
                flags = beams["BeamFlags"]
                if flags is not None and len(flags) > 0:
                    total = flags.size
                    bad = np.count_nonzero(flags)
                    good = total - bad
                    print(f"Beam Flags – Total: {total}, Good: {good}, Bad: {bad}")
                else:
                    print("Beam Flags – Not available")

        if args.attitude and recid == RecordType.GSF_RECORD_ATTITUDE:
            times = posix_seconds(record["Time"])
            for ts, roll, pitch, heave in zip(
                times, record["Roll_deg"], record["Pitch_deg"], record["Heave_m"]
            ):
                print(f"Time: {ts:.3f}, Roll: {roll:.2f}, Pitch: {pitch:.2f}, Heave: {heave:.2f}")

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
