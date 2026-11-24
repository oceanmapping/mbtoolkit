"""Check default reporting and explicit analysis modes through the CLI."""
import struct
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def sample_gsf(tmp_path, request):
    def subrecord(sid, payload):
        return bytes([sid]) + len(payload).to_bytes(3, "big") + payload

    version = b"GSF-v03.11\x00\x00"
    header = struct.pack(">II", len(version), 1) + version
    ping_header = bytearray(56)
    struct.pack_into(">h", ping_header, 16, 1)
    width = getattr(request, "param", 2)
    flag = 0x20 if width == 2 else 0x40
    factors = struct.pack(">I", 2) + b"".join(
        struct.pack(">Iii", (sid << 24) | (flag << 16), 100, 0) for sid in (1, 2)
    )
    payload = (
        bytes(ping_header)
        + subrecord(100, factors)
        + subrecord(1, struct.pack(">H" if width == 2 else ">I", 100))
        + subrecord(2, struct.pack(">h" if width == 2 else ">i", -200))
        + subrecord(102, b"\x00\x01")
    )
    source = tmp_path / "sample.gsf"
    source.write_bytes(header + struct.pack(">II", len(payload), 2) + payload)
    return source


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
def test_reporting_modes(sample_gsf, options, expected_sections):
    script = Path(__file__).resolve().parents[1] / "tools/gsf_info.py"

    result = subprocess.run(
        [sys.executable, str(script), str(sample_gsf)] + options,
        check=True, capture_output=True, text=True,
    )

    sections = {
        "=== GSF File Overview ===", "=== Datagram Records ===", "Datagram Summary:",
        "=== Scale Factor Analysis ===", "=== Sensor-Specific Subrecord Decode ===",
    }
    assert {section for section in sections if section in result.stdout} == expected_sections
    assert "SWATH_BATHYMETRY" in result.stdout or "Swath pings" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("sample_gsf", [2, 4], indirect=True)
@pytest.mark.parametrize(
    "option, expected",
    [
        ("--positions", "Time: 0.000"),
        ("--depths", "Depths (1): [1.]"),
        ("--depthStats", "Depth Stats – Min: 1.00, Max: 1.00, Mean: 1.00"),
        ("--pingHeaderVerbose", "[-2.]"),
    ],
)
def test_decodes_final_ping_at_eof(sample_gsf, option, expected):
    script = Path(__file__).resolve().parents[1] / "tools/gsf_info.py"
    result = subprocess.run(
        [sys.executable, str(script), str(sample_gsf), option],
        check=True, capture_output=True, text=True,
    )
    assert result.stderr == ""
    assert expected in result.stdout


def test_depth_stats_counts_flags_with_sparse_scale_factors(tmp_path):
    def subrecord(sid, payload):
        return bytes([sid]) + len(payload).to_bytes(3, "big") + payload

    version = b"GSF-v03.11\x00\x00"
    header = struct.pack(">II", len(version), 1) + version
    ping_header = bytearray(56)
    struct.pack_into(">h", ping_header, 16, 2)
    factors = struct.pack(">I", 2) + struct.pack(">IiiIii", 0x01200000, 100, 0, 0x10100000, 1, 0)
    payload = (
        bytes(ping_header)
        + subrecord(100, factors)
        + subrecord(1, struct.pack(">HH", 100, 200))
        + subrecord(16, b"\x00\x01")
    )
    source = tmp_path / "flagged.gsf"
    source.write_bytes(header + struct.pack(">II", len(payload), 2) + payload)
    script = Path(__file__).resolve().parents[1] / "tools/gsf_info.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source), "--depthStats"],
        check=True, capture_output=True, text=True,
    )
    assert result.stderr == ""
    assert "Depth Stats – Min: 1.00, Max: 2.00, Mean: 1.50" in result.stdout
    assert "Beam Flags – Total: 2, Good: 1, Bad: 1" in result.stdout
