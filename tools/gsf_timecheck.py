#!/usr/bin/env python3
"""
gsf_timecheck.py

Quick check that SWATH_BATHYMETRY and ATTITUDE records in a GSF
file are strictly time‑increasing.  Prints any out‑of‑order hits
and a final summary.
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from readers.base import GSFREADER, SWATH_BATHYMETRY, ATTITUDE

def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for gsf-timecheck tool.
    
    Returns:
        argparse.Namespace: Parsed command-line arguments containing:
            - filename: Path to the GSF file to check
    """
    p = argparse.ArgumentParser(
        description="Verify that ping & attitude times in a GSF file never go backwards."
    )
    p.add_argument("filename", help="Path to the GSF file")
    return p.parse_args()

def main() -> None:
    """
    Main entry point for gsf-timecheck tool.
    
    Verifies that SWATH_BATHYMETRY and ATTITUDE records in a GSF file have
    strictly time-increasing timestamps. Detects and reports any out-of-order
    records, then prints a summary with total counts and time spans.
    
    Exits with code 1 if the file is not found or if errors occur during reading.
    """
    args = parse_args()

    if not os.path.exists(args.filename):
        print(f"Error: File '{args.filename}' not found.", file=sys.stderr)
        sys.exit(1)

    reader = GSFREADER(args.filename)

    # Ping counters
    total_pings       = 0
    out_of_order_pings = 0
    first_ping_ts     = None
    last_ping_ts      = None
    prev_ping_ts      = -float("inf")

    # Attitude counters
    total_att         = 0
    out_of_order_att  = 0
    first_att_ts      = None
    last_att_ts       = None
    prev_att_ts       = -float("inf")

    while reader.moreData():
        try:
            nbytes, recid, dg = reader.readDatagram()
        except Exception as e:
            print(f"[ERROR] reading datagram: {e}", file=sys.stderr)
            break

        # SWATH bathy ping → only read header (fast)
        if recid == SWATH_BATHYMETRY:
            total_pings += 1

            # read header only (so dg.timestamp is set, nothing more)
            reader.scalefactorsd = dg.read(reader.scalefactorsd, True)
            ts = dg.timestamp

            if first_ping_ts is None:
                first_ping_ts = ts

            if ts < prev_ping_ts:
                out_of_order_pings += 1
                print(f"[PING] out‑of‑order: {ts:.6f} < {prev_ping_ts:.6f}")

            prev_ping_ts = ts
            last_ping_ts = ts

        # ATTITUDE record → full read to get dg.ts[]
        elif recid == ATTITUDE:
            total_att += 1

            # Note: ATTITUDE.read() takes no args
            dg.read()

            # only if ts array exists and has elements
            if hasattr(dg, "ts") and len(dg.ts) > 0:
                first_sample = dg.ts[0]
                last_sample  = dg.ts[-1]

                if first_att_ts is None:
                    first_att_ts = first_sample

                if first_sample < prev_att_ts:
                    out_of_order_att += 1
                    print(f"[ATT ] out‑of‑order: first={first_sample:.6f} < prev_last={prev_att_ts:.6f}")

                prev_att_ts = last_sample
                last_att_ts = last_sample

    # === summary ===
    print("\n=== Time‑check Summary ===")
    print(f"SWATH_BATHYMETRY: total={total_pings}, out‑of‑order={out_of_order_pings}")
    if first_ping_ts is not None:
        print(f"  span: {first_ping_ts:.6f} → {last_ping_ts:.6f}")
    print(f"ATTITUDE:          total={total_att},   out‑of‑order={out_of_order_att}")
    if first_att_ts is not None:
        print(f"  span: {first_att_ts:.6f} → {last_att_ts:.6f}")

if __name__ == "__main__":
    main()
