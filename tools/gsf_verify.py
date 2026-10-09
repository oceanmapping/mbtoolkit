#!/usr/bin/env python3
"""
gsf_verify.py - Validate a GSF file against a profile JSON.

This tool validates GSF files against JSON profile definitions, checking for
required records, header fields, subrecords, and constraints.
"""

import argparse
import json
import os
import sys
import struct
from pathlib import Path

from typing import Dict, Any
from collections import defaultdict
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from readers.base import GSFREADER
    
# Import utility functions - handle both relative and absolute imports
try:
    from .utils import scan_subrecord_ids
except ImportError:
    # Fallback for when script is run directly
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import scan_subrecord_ids

def load_profile(path: str) -> Dict[str, Any]:
    """
    Load and parse a GSF profile JSON file.
    
    Args:
        path: Path to the profile JSON file.
        
    Returns:
        Dict containing the profile definition with keys such as:
            - name: Profile name
            - gsf_version: GSF version string
            - required_records: List of required record definitions
            - optional_records: List of optional record definitions
            
    Raises:
        FileNotFoundError: If the profile file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    with open(path, 'r') as f:
        return json.load(f)['profile']

def attr_map(key: str) -> str:
    """
    Map a profile field name to a datagram attribute name.
    
    Converts underscore-separated field names (e.g., "num_beams") to
    attribute names without underscores (e.g., "numbeams") as used by
    the bundled GSF reader library.
    
    Args:
        key: Field name from profile (may contain underscores).
        
    Returns:
        Attribute name without underscores.
        
    Example:
        >>> attr_map("num_beams")
        'numbeams'
        >>> attr_map("centre_beam")
        'centrebeam'
    """
    return key.replace("_", "")

def verify(profile: str, gsf_file: str) -> None:
    profile = load_profile(profile)
    required = { r['record_id']: r for r in profile.get('required_records', []) }

    reader = GSFREADER(gsf_file)
    fh = open(gsf_file, 'rb')
    violations = []

    # precompute ping header size
    ping_hdr_fmt = ">llll5hlH3h2Hlllh"
    ping_hdr_size = struct.calcsize(ping_hdr_fmt)

    seen = defaultdict(int)

    while reader.moreData():
        try:
            nbytes, recid, dg = reader.readDatagram()
        except Exception as e:
            violations.append(f"Error reading datagram: {e}")
            break

        seen[recid] += 1

        if recid in required:
            rule = required[recid]
            # attempt header-only read, with fallbacks
            try:
                dg.read(reader.scalefactorsd, headeronly=True)
            except TypeError:
                try:
                    dg.read(reader.scalefactorsd)
                except TypeError:
                    dg.read()

            # 1) check constraints
            for key, expect in rule.get('constraints', {}).items():
                attr = attr_map(key)
                actual = getattr(dg, attr, None)
                if actual is None:
                    violations.append(
                        f"Record {recid}: missing attribute '{attr}' for constraint '{key}'"
                    )
                elif actual != expect:
                    violations.append(
                        f"Record {recid}: constraint '{key}' expected {expect} but got {actual}"
                    )

            # 2) required header fields
            for key in rule.get('required_header_fields', []):
                attr = attr_map(key)
                if not hasattr(dg, attr):
                    violations.append(
                        f"Record {recid}: missing required header field '{key}'"
                    )

            # 3) required subrecords
            if 'required_subrecords' in rule:
                fh.seek(dg.offset)
                raw = fh.read(nbytes + 8)
                subs = scan_subrecord_ids(raw, ping_hdr_size)
                for sub in rule['required_subrecords']:
                    rid = sub['subrecord_id']
                    if rid not in subs:
                        violations.append(
                            f"Rec {recid} @offset {dg.offset}: missing subrecord '{sub['subrecord_name']}' ({rid})"
                        )

    for rid, rule in required.items():
        if seen[rid] == 0:
            violations.append(
                f"Missing required record type {rule['record_type']} (ID={rid})"
            )

    print(f"\nValidation report for '{gsf_file}' against profile '{profile}':")
    if not violations:
        print("  ✅ All checks passed. GSF file is compliant.")
    else:
        print("  ❌ Found violations:")
        for v in violations:
            print("   -", v)

    fh.close()

def main() -> None:
    """
    Main entry point for gsf-verify tool.
    
    Validates a GSF file against a profile JSON definition, checking:
    - Required record types are present
    - Required header fields exist
    - Required subrecords are present
    - Constraints are satisfied
    
    Prints a validation report indicating compliance or listing violations.
    Exits with code 1 if files are not found or if errors occur.
    """
    p = argparse.ArgumentParser(
        description="Validate a GSF file against a profile JSON."
    )
    p.add_argument("profile", help="Profile JSON file")
    p.add_argument("gsf_file", help="GSF file to validate")
    args = p.parse_args()

    if not os.path.exists(args.profile):
        print(f"Profile '{args.profile}' not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.gsf_file):
        print(f"GSF file '{args.gsf_file}' not found.", file=sys.stderr)
        sys.exit(1)
    
    verify(args.profile, args.gsf_file)

if __name__ == "__main__":
    main()
