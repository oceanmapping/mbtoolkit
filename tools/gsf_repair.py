#!/usr/bin/env python3
"""
gsf_repair.py - Repair a GSF file to comply with a minimal profile.

This tool repairs GSF files by:
  - adding missing required subrecords as empty subrecords (profile-driven)
      - detecting missing or unreasonable SCALE_FACTORS entries for beam
        arrays that GSF 3.05 scales, and rewriting them with sensible defaults
"""

import argparse
import json
import os
import struct
import sys
from typing import Dict, Any, List
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from readers.base import GSFREADER, SWATH_BATHYMETRY

try:
    from .utils import (
        REQUIRED_SCALE_FACTOR_ARRAY_IDS,
        datagram_header_size,
        factors_to_map,
        make_empty_subrecord,
        parse_scale_factors,
        repair_scale_factor_set,
        replace_or_insert_scale_factors,
        scale_factor_fingerprint,
        scan_subrecords,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import (
        REQUIRED_SCALE_FACTOR_ARRAY_IDS,
        datagram_header_size,
        factors_to_map,
        make_empty_subrecord,
        parse_scale_factors,
        repair_scale_factor_set,
        replace_or_insert_scale_factors,
        scale_factor_fingerprint,
        scan_subrecords,
    )


def load_profile(path: str) -> Dict[str, Any]:
    """Load and parse a GSF profile JSON file."""
    with open(path, "r") as f:
        j = json.load(f)
    return j["profile"]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for gsf-repair tool."""
    p = argparse.ArgumentParser(
        description=(
            "Repair a GSF file: add missing profile subrecords and "
            "fix/add missing or unreasonable SCALE_FACTORS."
        )
    )
    p.add_argument("profile", help="JSON profile file")
    p.add_argument("infile", help="Input GSF file")
    p.add_argument("--out", "-o", required=True, help="Repaired GSF output")
    p.add_argument(
        "--fix-scale-factors",
        dest="fix_scale_factors",
        action="store_true",
        default=True,
        help="Fix missing/unreasonable SCALE_FACTORS (default: on)",
    )
    p.add_argument(
        "--no-fix-scale-factors",
        dest="fix_scale_factors",
        action="store_false",
        help="Disable SCALE_FACTORS repair",
    )
    return p.parse_args()


def _needed_array_ids(subs: List) -> List[int]:
    """Return scaled-array subrecord IDs present in a ping."""
    return sorted(
        {
            sid
            for sid, _ in subs
            if sid in REQUIRED_SCALE_FACTOR_ARRAY_IDS
        }
    )


def main() -> None:
    """
    Main entry point for gsf-repair tool.

    Repairs a GSF file by adding missing required subrecords and repairing
    SCALE_FACTORS. Prints a summary of repairs made.
    """
    args = parse_args()

    for fn in (args.profile, args.infile):
        if not os.path.exists(fn):
            print(f"Error: '{fn}' not found.", file=sys.stderr)
            sys.exit(1)

    profile = load_profile(args.profile)
    ping_rules = {}
    for rec in profile.get("required_records", []):
        if rec["record_id"] == SWATH_BATHYMETRY:
            ping_rules[SWATH_BATHYMETRY] = [
                (sr["subrecord_id"], sr.get("subrecord_name", str(sr["subrecord_id"])))
                for sr in rec.get("required_subrecords", [])
            ]

    reader = GSFREADER(args.infile)
    fh_in = open(args.infile, "rb")
    fh_out = open(args.out, "wb")

    ping_hdr_fmt = ">llll5hlH3h2Hlllh"
    ping_hdr_size = struct.calcsize(ping_hdr_fmt)

    fixed_counts = defaultdict(int)
    total_counts = defaultdict(int)
    sf_pings_touched = 0
    sf_entries_added = 0
    sf_entries_replaced = 0
    sf_subrecords_inserted = 0
    active_factors = []  # inherited SCALE_FACTORS across pings

    while reader.moreData():
        try:
            nbytes, recid, dg = reader.readDatagram()
        except Exception as e:
            print(f"[ERROR] reading datagram: {e}", file=sys.stderr)
            break

        total_counts[recid] += 1

        fh_in.seek(dg.offset)
        # nbytes from the reader is the full record length (size_word + 8).
        # Do not read past the record or the next header gets spliced in.
        raw = fh_in.read(nbytes)

        if recid == SWATH_BATHYMETRY:
            # --- profile-driven empty subrecord repair ---
            if SWATH_BATHYMETRY in ping_rules:
                required = ping_rules[SWATH_BATHYMETRY]
                present_subs = scan_subrecords(raw, ping_hdr_size)
                present_ids = {sid for sid, _ in present_subs}
                missing = [
                    (sid, name) for sid, name in required if sid not in present_ids
                ]
                if missing:
                    # Insert before arrays and trailing padding. Appending at the
                    # record end can hide new headers in padding or extend a
                    # terminal subrecord whose declared size exceeds the record.
                    insert_at = datagram_header_size(raw) + ping_hdr_size
                    if present_subs and present_subs[0][0] == 100:
                        insert_at += 4 + len(present_subs[0][1])
                    additions = b"".join(make_empty_subrecord(sid) for sid, _name in missing)
                    raw = raw[:insert_at] + additions + raw[insert_at:]
                    old_size = struct.unpack(">I", raw[:4])[0]
                    # size word excludes the 8-byte header; raw grew by 4*len(missing)
                    new_size = old_size + 4 * len(missing)
                    raw = struct.pack(">I", new_size) + raw[4:]
                    fixed_counts[recid] += len(missing)

            # --- SCALE_FACTORS repair ---
            if args.fix_scale_factors:
                subs = scan_subrecords(raw, ping_hdr_size)
                needed = _needed_array_ids(subs)
                sf_payloads = [pl for sid, pl in subs if sid == 100]

                sf_parse_failed = False
                if sf_payloads:
                    try:
                        existing = parse_scale_factors(sf_payloads[0])
                    except ValueError:
                        sf_parse_failed = True
                        existing = list(active_factors)
                        sf_entries_replaced += 1  # whole payload treated as bad
                else:
                    existing = list(active_factors)

                repaired, changes = repair_scale_factor_set(existing, needed)

                # Track add vs replace from change messages
                for msg in changes:
                    if msg.startswith("added"):
                        sf_entries_added += 1
                    elif msg.startswith("replaced"):
                        sf_entries_replaced += 1

                before_fp = scale_factor_fingerprint(
                    sorted(existing, key=lambda f: f["subrecord_id"])
                ) if existing else tuple()
                after_fp = scale_factor_fingerprint(repaired)

                needs_write = False
                if sf_parse_failed or changes:
                    needs_write = True
                elif sf_payloads and before_fp != after_fp:
                    needs_write = True
                elif (not sf_payloads) and needed and (
                    not factors_to_map(active_factors).keys()
                    >= set(needed)
                ):
                    # Inherited set does not cover arrays in this ping.
                    needs_write = True

                if needs_write:
                    had_sf = any(sid == 100 for sid, _ in subs)
                    raw = replace_or_insert_scale_factors(
                        raw, ping_hdr_size, repaired
                    )
                    sf_pings_touched += 1
                    if not had_sf:
                        sf_subrecords_inserted += 1

                active_factors = repaired

        fh_out.write(raw)

    fh_in.close()
    fh_out.close()

    print(f"Repaired GSF written to: {args.out}\n")
    for rid, tot in total_counts.items():
        fixed = fixed_counts.get(rid, 0)
        print(f"  Record {rid:2d}: total={tot:4d}, empty subrecords added={fixed:4d}")

    if args.fix_scale_factors:
        print("\nSCALE_FACTORS repair:")
        print(f"  pings updated              : {sf_pings_touched}")
        print(f"  SCALE_FACTORS inserted     : {sf_subrecords_inserted}")
        print(f"  scale-factor entries added : {sf_entries_added}")
        print(f"  unreasonable entries fixed : {sf_entries_replaced}")


if __name__ == "__main__":
    main()
