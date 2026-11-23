"""Check default reporting and explicit analysis modes through the CLI."""
import struct
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "options, expected_sections",
    [
        ([], {"=== GSF File Overview ===", "=== Datagram Records ==="}),
        (["--summary"], {"Datagram Summary:"}),
        (["--scaleFactors"], {"=== Scale Factor Analysis ==="}),
        (["--sensorSpecific"], {"=== Sensor-Specific Subrecord Decode ==="}),
        (["--scaleFactors", "--sensorSpecific"], {
            "=== Scale Factor Analysis ===", "=== Sensor-Specific Subrecord Decode ==="
        }),
    ],
)
def test_reporting_modes(tmp_path, options, expected_sections):
    def subrecord(sid, payload):
        return bytes([sid]) + len(payload).to_bytes(3, "big") + payload

    version = b"GSF-v03.11\x00\x00"
    header = struct.pack(">II", len(version), 1) + version
    ping_header = bytearray(56)
    struct.pack_into(">h", ping_header, 16, 1)
    factors = struct.pack(">IIii", 1, 0x01200000, 100, 0)
    payload = (
        bytes(ping_header)
        + subrecord(100, factors)
        + subrecord(1, b"\x00\x64")
        + subrecord(102, b"\x00\x01")
    )
    source = tmp_path / "sample.gsf"
    source.write_bytes(header + struct.pack(">II", len(payload), 2) + payload)
    script = Path(__file__).resolve().parents[1] / "tools/gsf-info.py"

    result = subprocess.run(
        [sys.executable, str(script), str(source)] + options,
        check=True, capture_output=True, text=True,
    )

    sections = {
        "=== GSF File Overview ===", "=== Datagram Records ===", "Datagram Summary:",
        "=== Scale Factor Analysis ===", "=== Sensor-Specific Subrecord Decode ===",
    }
    assert {section for section in sections if section in result.stdout} == expected_sections
    assert "SWATH_BATHYMETRY" in result.stdout or "Swath pings" in result.stdout
    assert result.stderr == ""
