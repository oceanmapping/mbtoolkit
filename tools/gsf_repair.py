#!/usr/bin/env python3
"""
gsf_repair.py - Repair a GSF file to comply with a minimal profile.

This tool copies a GSF file and reports the swath bathymetry pings that lack
subrecords a profile requires.

Earlier versions padded each such ping with empty (zero-length) subrecords.
The reference GSF library (gsflib 3.11) never writes a zero-length subrecord,
and it reads them wrongly: it ignores one that ends a ping, and with one
inside a ping it either fails to read the ping or returns shifted, wrong
beam values. Since GSF offers no valid empty subrecord, this tool no longer
adds any. It copies the file unchanged and lists every requirement it could
not satisfy.
"""

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict
from typing import Dict, Any

from GSFU import gsf

# Import utility functions - handle both relative and absolute imports
try:
    from .utils import missing_subrecords, ping_header_size, scan_subrecord_ids
except ImportError:
    # Fallback for when script is run directly
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import missing_subrecords, ping_header_size, scan_subrecord_ids

#: The GSF record ID of a swath bathymetry ping (gsf.h: GSF_RECORD_SWATH_BATHYMETRY_PING).
SWATH_BATHYMETRY = 2


def load_profile(path: str) -> Dict[str, Any]:
    """
    Load and parse a GSF profile JSON file.

    Args:
        path: Path to the profile JSON file.

    Returns:
        Dict containing the profile definition.

    Raises:
        FileNotFoundError: If the profile file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    with open(path, 'r') as f:
        j = json.load(f)
    return j['profile']


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for gsf-repair tool.

    Returns:
        argparse.Namespace: Parsed command-line arguments containing:
            - profile: Path to JSON profile file
            - infile: Path to input GSF file
            - out: Path to output repaired GSF file
    """
    p = argparse.ArgumentParser(
        description="Repair a GSF file to comply with a minimal profile (e.g. missing subrecords)."
    )
    p.add_argument("profile", help="JSON profile file")
    p.add_argument("infile",  help="Input GSF file")
    p.add_argument("--out",   "-o", required=True, help="Repaired GSF output")
    return p.parse_args()


def main() -> None:
    """
    Main entry point for gsf-repair tool.

    Copies a GSF file to the output path unchanged, and checks each swath
    bathymetry ping for the subrecords the profile requires, using the same
    rules as gsf-verify. Prints the number of records of each type, and then
    how many pings lack each required subrecord. No subrecords are added,
    because GSF has no valid empty subrecord to add.

    Exits with code 1 if the profile or input file is not found.
    """
    args = parse_args()

    # sanity
    for fn in (args.profile, args.infile):
        if not os.path.exists(fn):
            print(f"Error: '{fn}' not found.", file=sys.stderr)
            sys.exit(1)

    profile = load_profile(args.profile)
    # the ping's required subrecords, as (subrecord_id, name) tuples
    required = []
    for rec in profile.get('required_records', []):
        if rec['record_id'] == SWATH_BATHYMETRY:
            required = [
                (sr['subrecord_id'], sr.get('subrecord_name', str(sr['subrecord_id'])))
                for sr in rec.get('required_subrecords', [])
            ]

    reader = gsf(args.infile)
    reader.index_file()

    # count records of each type, in the order the types first appear
    total_counts = defaultdict(int)
    for recid in reader.Index["RecordID"].tolist():
        total_counts[recid] += 1

    # count the pings that lack each required subrecord
    unrepaired = defaultdict(int)
    if required:
        ping_hdr_size = ping_header_size(reader.gsfVersion)
        record_sizes = dict(
            zip(reader.Index["ByteOffset"].tolist(), reader.Index["TotalBytes"].tolist())
        )
        with open(args.infile, "rb") as fh_in:
            for _record_type, offset, ping in reader.iter_records(SWATH_BATHYMETRY):
                def read_subrecord_ids(offset=offset):
                    fh_in.seek(offset)
                    return scan_subrecord_ids(fh_in.read(record_sizes[offset]), ping_hdr_size)

                for missing in missing_subrecords(ping, required, read_subrecord_ids):
                    unrepaired[missing] += 1
    reader.closeFile()

    # GSF has no valid empty subrecord to add, so the file is copied unchanged.
    shutil.copyfile(args.infile, args.out)

    # summary
    print(f"Repaired GSF written to: {args.out}\n")
    for rid, tot in total_counts.items():
        print(f"  Record {rid:2d}: total={tot:4d}, subrecords fixed={0:4d}")

    if unrepaired:
        print("\nNot repaired, because GSF has no valid empty subrecord to add:")
        for (sid, name), count in sorted(unrepaired.items()):
            print(f"  Record {SWATH_BATHYMETRY:2d}: {count:4d} pings lack '{name}' ({sid})")


if __name__ == "__main__":
    main()
