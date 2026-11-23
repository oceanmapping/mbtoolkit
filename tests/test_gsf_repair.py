"""
Tests for gsf-repair functionality.
"""
import pytest
import struct
import tempfile
import os
import json
import subprocess
import sys
from pathlib import Path
from tools.utils import make_empty_subrecord, parse_scale_factors, scan_subrecords


class TestMakeEmptySubrecord:
    """Tests for make_empty_subrecord function."""

    def test_make_empty_subrecord_basic(self):
        """Test creating an empty subrecord."""
        sub_id = 1
        result = make_empty_subrecord(sub_id)
        
        # Should be 4 bytes: 1 byte ID + 3 bytes length (0)
        assert len(result) == 4
        assert result[0] == sub_id
        assert result[1:4] == b"\x00\x00\x00"

    def test_make_empty_subrecord_different_ids(self):
        """Test creating empty subrecords with different IDs."""
        for sub_id in [1, 100, 255]:
            result = make_empty_subrecord(sub_id)
            assert len(result) == 4
            assert result[0] == sub_id
            assert result[1:4] == b"\x00\x00\x00"

    def test_make_empty_subrecord_structure(self):
        """Test that empty subrecord has correct binary structure."""
        sub_id = 42
        result = make_empty_subrecord(sub_id)
        
        # Verify it can be unpacked correctly
        unpacked_id = result[0]
        unpacked_length = int.from_bytes(result[1:4], "big")
        
        assert unpacked_id == sub_id
        assert unpacked_length == 0


@pytest.mark.parametrize(
    "bad_payload, require_sf, expected_updates",
    [(b"", False, 1), (b"\x00\x00\x00\x01", False, 1),
     (None, True, 1), (None, False, 0)],
)
def test_repair_inherited_scale_factors(tmp_path, bad_payload, require_sf, expected_updates):
    def subrecord(sid, payload):
        return bytes([sid]) + len(payload).to_bytes(3, "big") + payload

    def ping(subs):
        # One beam; the remaining ping header fields are zero.
        header = bytearray(56)
        struct.pack_into(">h", header, 16, 1)
        content = bytes(header) + b"".join(subs)
        return struct.pack(">II", len(content), 2) + content

    factors = struct.pack(">I", 1) + b"\x01\x20\x00\x00" + struct.pack(">ii", 100, -500)
    depth = subrecord(1, b"\x00\x64")
    first = ping([subrecord(100, factors), depth])
    second = ping(([subrecord(100, bad_payload)] if bad_payload is not None else []) + [depth])
    source, target, profile = (tmp_path / name for name in ("input.gsf", "output.gsf", "profile.json"))
    source.write_bytes(first + second)
    profile.write_text(json.dumps({"profile": {"required_records": [{
        "record_id": 2,
        "required_subrecords": [{"subrecord_id": 100}] if require_sf else [],
    }]}}))

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "tools/gsf_repair.py"),
         str(profile), str(source), "--out", str(target)],
        capture_output=True, text=True, check=True,
    )

    output = target.read_bytes()
    assert output[:len(first)] == first
    assert "pings updated              : {}".format(expected_updates) in result.stdout
    second_subs = scan_subrecords(output[len(first):], 56)
    assert (1, b"\x00\x64") in second_subs
    if expected_updates:
        repaired_payload = next(payload for sid, payload in second_subs if sid == 100)
        assert repaired_payload == factors
        assert parse_scale_factors(repaired_payload)[0]["offset"] == -500
    else:
        assert output == first + second

