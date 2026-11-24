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

from readers import BackendError, DecodeRequest, add_backend_arguments, open_reader
    
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

def verify(profile: str, gsf_file: str, backend=None) -> None:
    profile = load_profile(profile)
    required = { r['record_id']: r for r in profile.get('required_records', []) }

    violations = []

    seen = defaultdict(int)

    decoded_types = frozenset(
        rid for rid, rule in required.items()
        if rule.get('constraints') or rule.get('required_header_fields')
    )
    with open_reader(gsf_file, backend=backend) as reader:
        _verify_records(reader, DecodeRequest(decoded_types), required, seen, violations)

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


def _verify_records(reader, request, required, seen, violations):
    for record in reader.records(request):
        recid = record.record_id
        seen[recid] += 1

        if recid in required:
            rule = required[recid]
            data = record.data

            # 1) check constraints
            for key, expect in rule.get('constraints', {}).items():
                actual = data.value(key) if data is not None else None
                if actual is None:
                    violations.append(
                        f"Record {recid}: missing field '{key}' for constraint '{key}'"
                    )
                elif actual != expect:
                    violations.append(
                        f"Record {recid}: constraint '{key}' expected {expect} but got {actual}"
                    )

            # 2) required header fields
            for key in rule.get('required_header_fields', []):
                if data is None or not data.has_field(key):
                    violations.append(
                        f"Record {recid}: missing required header field '{key}'"
                    )

            # 3) required subrecords
            if 'required_subrecords' in rule:
                subs = scan_subrecord_ids(record.raw, reader.ping_header_size)
                for sub in rule['required_subrecords']:
                    rid = sub['subrecord_id']
                    if rid not in subs:
                        violations.append(
                            f"Rec {recid} @offset {record.offset}: missing subrecord '{sub['subrecord_name']}' ({rid})"
                        )

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
    add_backend_arguments(p)
    args = p.parse_args()

    if not os.path.exists(args.profile):
        print(f"Profile '{args.profile}' not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.gsf_file):
        print(f"GSF file '{args.gsf_file}' not found.", file=sys.stderr)
        sys.exit(1)
    
    try:
        verify(args.profile, args.gsf_file, backend=args.backend)
    except (BackendError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
