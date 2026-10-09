#!/usr/bin/env python3
"""
gsf_repair.py - Repair a GSF file to comply with a minimal profile.

This tool repairs GSF files by adding missing required subrecords as empty
subrecords, ensuring the file complies with a specified profile definition.
"""

import argparse
import json
import os
import struct
import sys
from typing import Dict, Any
from collections import defaultdict
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from readers.base import GSFREADER, SWATH_BATHYMETRY

# Import utility functions - handle both relative and absolute imports
try:
    from .utils import scan_subrecord_ids
except ImportError:
    # Fallback for when script is run directly
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import scan_subrecord_ids

def make_empty_subrecord(sub_id: int) -> bytes:
    """
    Build an empty subrecord with zero-length payload.
    
    Creates a subrecord structure with the specified ID but no payload data.
    Format: [1-byte subrecord_id][3-byte length=0].
    
    Args:
        sub_id: Subrecord ID (0-255).
        
    Returns:
        bytes: 4-byte subrecord structure with zero length.
        
    Example:
        >>> result = make_empty_subrecord(100)
        >>> len(result)
        4
        >>> result[0]
        100
    """
    return struct.pack(">B3s", sub_id, b"\x00\x00\x00")

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
    
    Repairs a GSF file by adding missing required subrecords as empty subrecords.
    Reads the input file, checks for missing subrecords according to the profile,
    adds empty subrecords where needed, and writes the repaired file.
    
    Prints a summary of repairs made. Exits with code 1 if files are not found
    or if errors occur during processing.
    """
    args = parse_args()

    # sanity
    for fn in (args.profile, args.infile):
        if not os.path.exists(fn):
            print(f"Error: '{fn}' not found.", file=sys.stderr)
            sys.exit(1)

    profile = load_profile(args.profile)
    # build a quick map: record_id -> list of required subrecord_ids
    ping_rules = {}
    for rec in profile.get('required_records', []):
        if rec['record_id'] == SWATH_BATHYMETRY:
            ping_rules[SWATH_BATHYMETRY] = [
                (sr['subrecord_id'], sr.get('subrecord_name', str(sr['subrecord_id'])))
                for sr in rec.get('required_subrecords', [])
            ]

    # set up reader & raw I/O
    reader = GSFREADER(args.infile)
    fh_in  = open(args.infile, "rb")
    fh_out = open(args.out,    "wb")

    # ping header size for raw-scan:
    ping_hdr_fmt  = ">llll5hlH3h2Hlllh"
    ping_hdr_size = struct.calcsize(ping_hdr_fmt)

    # track how many we fixed
    fixed_counts = defaultdict(int)
    total_counts = defaultdict(int)

    # iterate
    while reader.moreData():
        try:
            nbytes, recid, dg = reader.readDatagram()
        except Exception as e:
            print(f"[ERROR] reading datagram: {e}", file=sys.stderr)
            break

        total_counts[recid] += 1

        # pull raw bytes
        fh_in.seek(dg.offset)
        raw = fh_in.read(nbytes + 8)  # size-word + id-word + data

        # only repair swath bathy pings
        if recid == SWATH_BATHYMETRY and SWATH_BATHYMETRY in ping_rules:
            required = ping_rules[SWATH_BATHYMETRY]
            subs = scan_subrecord_ids(raw, ping_hdr_size)
            missing = [ (sid,name) for sid,name in required if sid not in subs ]
            if missing:
                # append empty subrecords
                for sid, name in missing:
                    raw += make_empty_subrecord(sid)
                # fix size word (first 4 bytes) to reflect the added length
                old_size = struct.unpack(">I", raw[:4])[0]
                new_size = old_size + 4*len(missing)
                raw = struct.pack(">I", new_size) + raw[4:]
                fixed_counts[recid] += len(missing)

        # write the (possibly modified) raw datagram out
        fh_out.write(raw)

    fh_in .close()
    fh_out.close()

    # summary
    print(f"Repaired GSF written to: {args.out}\n")
    for rid, tot in total_counts.items():
        fixed = fixed_counts.get(rid, 0)
        print(f"  Record {rid:2d}: total={tot:4d}, subrecords fixed={fixed:4d}")

if __name__ == "__main__":
    main()
