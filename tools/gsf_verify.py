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

from typing import Dict, Any, Optional

from GSFU import gsf

# Import utility functions - handle both relative and absolute imports
try:
    from .utils import missing_subrecords, ping_header_size, scan_subrecord_ids
except ImportError:
    # Fallback for when script is run directly
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import missing_subrecords, ping_header_size, scan_subrecord_ids

#: Maps each swath bathymetry ping header field name used in profiles to the
#: key gsfu decodes it into. The reserved and spare fields are part of every
#: ping header but carry no value, so gsfu does not decode them; they map to
#: None and are always present.
PROFILE_FIELD_TO_GSFU = {
    "timestamp": "PingTime",
    "longitude": "Longitude_deg",
    "latitude": "Latitude_deg",
    "num_beams": "NumberBeams",
    "centre_beam": "CenterBeam",
    "ping_flags": "PingFlags",
    "reserved": None,
    "tide_corrector": "TideCorrector_m",
    "depth_corrector": "DepthCorrector_m",
    "heading": "Heading_deg",
    "pitch": "Pitch_deg",
    "roll": "Roll_deg",
    "heave": "Heave_m",
    "course": "Course_deg",
    "speed": "Speed_kn",
    "height": "Height_m",
    "separation": "SEP_m",
    "gps_tide_corrector": "GPSTideCorrector_m",
    "spare": None,
}


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


def gsfu_field(key: str) -> Optional[str]:
    """
    Map a profile field name to the key gsfu decodes that field into.

    Swath bathymetry ping header fields are translated through
    PROFILE_FIELD_TO_GSFU. Any other name, such as a field of another
    record type, is assumed to be gsfu's own key and is returned unchanged.

    Args:
        key: Field name from a profile, for example "num_beams".

    Returns:
        The gsfu key, for example "NumberBeams", or None for a header field
        that gsfu does not decode because it carries no value.

    Example:
        >>> gsfu_field("num_beams")
        'NumberBeams'
        >>> gsfu_field("centre_beam")
        'CenterBeam'
    """
    return PROFILE_FIELD_TO_GSFU.get(key, key)


def field_present(record: Dict[str, Any], key: str) -> bool:
    """
    Report whether a decoded record has the field a profile names.

    Args:
        record: A record as decoded by gsfu.
        key: Field name from a profile.

    Returns:
        True if the record has the field. The reserved and spare ping
        header fields are always present, since every ping header has them.
    """
    field = gsfu_field(key)
    return (key in PROFILE_FIELD_TO_GSFU and field is None) or field in record


def verify(profile_path: str, gsf_file: str) -> None:
    """
    Check a GSF file against a profile and print a validation report.

    The profile lists required record types, and for each one, optionally,
    required header fields, required subrecords, and constraints on field
    values. Every record of a required type is checked against its rules.

    A required beam array subrecord is present when gsfu decodes that array
    for the ping, that is, when the ping's 'Beams' column for it is not
    None. Any other required subrecord, such as the scale factors (100), is
    looked for among the subrecord IDs in the ping's raw bytes.

    Args:
        profile_path: Path to the profile JSON file.
        gsf_file: Path to the GSF file to check.
    """
    profile = load_profile(profile_path)
    required = { r['record_id']: r for r in profile.get('required_records', []) }

    reader = gsf(gsf_file)
    reader.index_file()
    fh = open(gsf_file, 'rb')
    violations = []

    # The fixed ping header's size depends on the file's GSF version.
    ping_hdr_size = ping_header_size(reader.gsfVersion)
    record_sizes = dict(
        zip(reader.Index["ByteOffset"].tolist(), reader.Index["TotalBytes"].tolist())
    )

    seen = reader.Index["RecordID"].value_counts().to_dict()

    # Only record types that carry rules need to be decoded.
    checked = [rid for rid, rule in sorted(required.items())
               if rule.get('constraints') or rule.get('required_header_fields')
               or rule.get('required_subrecords')]

    try:
        for recid in checked:
            rule = required[recid]
            for _record_type, offset, record in reader.iter_records(recid):

                # 1) check constraints
                for key, expect in rule.get('constraints', {}).items():
                    field = gsfu_field(key)
                    actual = record.get(field) if field is not None else None
                    if actual is None:
                        violations.append(
                            f"Record {recid}: missing attribute '{field}' for constraint '{key}'"
                        )
                    elif actual != expect:
                        violations.append(
                            f"Record {recid}: constraint '{key}' expected {expect} but got {actual}"
                        )

                # 2) required header fields
                for key in rule.get('required_header_fields', []):
                    if not field_present(record, key):
                        violations.append(
                            f"Record {recid}: missing required header field '{key}'"
                        )

                # 3) required subrecords
                if 'required_subrecords' in rule:
                    def read_subrecord_ids(offset=offset):
                        fh.seek(offset)
                        return scan_subrecord_ids(fh.read(record_sizes[offset]), ping_hdr_size)

                    wanted = [(sub['subrecord_id'], sub['subrecord_name'])
                              for sub in rule['required_subrecords']]
                    for rid, name in missing_subrecords(record, wanted, read_subrecord_ids):
                        violations.append(
                            f"Rec {recid} @offset {offset}: missing subrecord '{name}' ({rid})"
                        )
    except Exception as e:
        violations.append(f"Error reading datagram: {e}")

    for rid, rule in required.items():
        if seen.get(rid, 0) == 0:
            violations.append(
                f"Missing required record type {rule['record_type']} (ID={rid})"
            )

    print(f"\nValidation report for '{gsf_file}' against profile '{profile_path}':")
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
