"""
Tests for utility functions.
"""
import pytest
import struct
import numpy as np
from tools.utils import (
    missing_subrecords,
    ping_header_size,
    posix_seconds,
    scan_subrecords,
    scan_subrecord_ids,
)


class TestScanSubrecords:
    """Tests for scan_subrecords function."""

    def test_scan_subrecords_basic(self):
        """Test scanning subrecords with basic structure."""
        # Create a mock datagram: size(4) + id(4) + ping_header(60) + subrecords
        ping_header_size = 60
        ping_header = b'\x00' * ping_header_size
        
        # Subrecord 1: ID=1, length=4, payload=4 bytes
        subrecord1 = struct.pack(">B", 1) + struct.pack(">I", 4)[1:] + b"data"
        # Subrecord 2: ID=2, length=3, payload=3 bytes
        subrecord2 = struct.pack(">B", 2) + struct.pack(">I", 3)[1:] + b"xyz"
        
        # Build datagram: size + id (no checksum) + header + subrecords
        datagram_size = 4 + 4 + ping_header_size + len(subrecord1) + len(subrecord2)
        size_word = struct.pack(">I", datagram_size - 4)  # size excludes size word itself
        id_word = struct.pack(">I", 0x00000002)  # Record ID 2, no checksum bit
        
        raw = size_word + id_word + ping_header + subrecord1 + subrecord2
        
        result = scan_subrecords(raw, ping_header_size)
        
        assert len(result) == 2
        assert result[0] == (1, b"data")
        assert result[1] == (2, b"xyz")

    def test_scan_subrecords_empty(self):
        """Test scanning subrecords when there are none."""
        ping_header_size = 60
        ping_header = b'\x00' * ping_header_size
        
        datagram_size = 4 + 4 + ping_header_size
        size_word = struct.pack(">I", datagram_size - 4)
        id_word = struct.pack(">I", 0x00000002)
        
        raw = size_word + id_word + ping_header
        
        result = scan_subrecords(raw, ping_header_size)
        
        assert len(result) == 0
        assert result == []

    def test_scan_subrecords_with_checksum(self):
        """Test scanning subrecords when checksum is present."""
        ping_header_size = 60
        ping_header = b'\x00' * ping_header_size
        
        # Subrecord: ID=100, length=2, payload=2 bytes
        subrecord = struct.pack(">B", 100) + struct.pack(">I", 2)[1:] + b"ab"
        
        # Build datagram with checksum (bit 31 set in id word)
        datagram_size = 4 + 4 + 4 + ping_header_size + len(subrecord)  # +4 for checksum
        size_word = struct.pack(">I", datagram_size - 4)
        id_word = struct.pack(">I", 0x80000002)  # Checksum bit set
        checksum = struct.pack(">I", 0x12345678)
        
        raw = size_word + id_word + checksum + ping_header + subrecord
        
        result = scan_subrecords(raw, ping_header_size)
        
        assert len(result) == 1
        assert result[0] == (100, b"ab")


class TestScanSubrecordIds:
    """Tests for scan_subrecord_ids function."""

    def test_scan_subrecord_ids_basic(self):
        """Test scanning subrecord IDs with basic structure."""
        ping_header_size = 60
        ping_header = b'\x00' * ping_header_size
        
        subrecord1 = struct.pack(">B", 1) + struct.pack(">I", 4)[1:] + b"data"
        subrecord2 = struct.pack(">B", 2) + struct.pack(">I", 3)[1:] + b"xyz"
        
        datagram_size = 4 + 4 + ping_header_size + len(subrecord1) + len(subrecord2)
        size_word = struct.pack(">I", datagram_size - 4)
        id_word = struct.pack(">I", 0x00000002)
        
        raw = size_word + id_word + ping_header + subrecord1 + subrecord2
        
        result = scan_subrecord_ids(raw, ping_header_size)
        
        assert len(result) == 2
        assert result == [1, 2]

    def test_scan_subrecord_ids_empty(self):
        """Test scanning subrecord IDs when there are none."""
        ping_header_size = 60
        ping_header = b'\x00' * ping_header_size
        
        datagram_size = 4 + 4 + ping_header_size
        size_word = struct.pack(">I", datagram_size - 4)
        id_word = struct.pack(">I", 0x00000002)
        
        raw = size_word + id_word + ping_header
        
        result = scan_subrecord_ids(raw, ping_header_size)
        
        assert len(result) == 0
        assert result == []

    def test_scan_subrecord_ids_multiple(self):
        """Test scanning multiple subrecord IDs."""
        ping_header_size = 60
        ping_header = b'\x00' * ping_header_size
        
        subrecords = []
        for i in range(5):
            payload = b"x" * i
            subrecord = struct.pack(">B", i + 10) + struct.pack(">I", len(payload))[1:] + payload
            subrecords.append(subrecord)
        
        total_subrecord_size = sum(len(s) for s in subrecords)
        datagram_size = 4 + 4 + ping_header_size + total_subrecord_size
        size_word = struct.pack(">I", datagram_size - 4)
        id_word = struct.pack(">I", 0x00000002)
        
        raw = size_word + id_word + ping_header + b"".join(subrecords)
        
        result = scan_subrecord_ids(raw, ping_header_size)
        
        assert len(result) == 5
        assert result == [10, 11, 12, 13, 14]


class TestPosixSeconds:
    """Tests for posix_seconds function."""

    def test_iso_string_with_utc_offset(self):
        """Test converting a gsfu PingTime string, which carries a UTC offset."""
        assert posix_seconds("2024-08-26T05:27:53.719285+00:00") == pytest.approx(
            1724650073.719285, abs=1e-6
        )

    def test_datetime64_array(self):
        """Test converting a gsfu attitude Time array, keeping sub-second precision."""
        times = np.array(
            ["1970-01-01T00:00:01.5", "1970-01-01T00:00:02.25"], dtype="datetime64[ns]"
        )

        result = posix_seconds(times)

        assert isinstance(result, np.ndarray)
        assert list(result) == pytest.approx([1.5, 2.25])

    def test_single_datetime64_value(self):
        """Test that a single datetime64 value converts to a plain float."""
        result = posix_seconds(np.datetime64("1970-01-01T00:01:00", "ns"))

        assert isinstance(result, float)
        assert result == 60.0


def ping_record(subrecords, header_size=60):
    """
    Build a raw ping record buffer from (subrecord_id, size_field, payload) tuples.

    Args:
        subrecords: The subrecords to include, in order. The size field is
            given separately so tests can build the intensity series
            subrecord, whose size field also counts its identifier word.
        header_size: The size of the zero-filled ping header.

    Returns:
        The record bytes: size word, identifier word, header, and subrecords.
    """
    body = b"\x00" * header_size
    for sub_id, size_field, payload in subrecords:
        body += struct.pack(">I", (sub_id << 24) | size_field) + payload
    return struct.pack(">II", len(body), 2) + body


class TestIntensitySeriesSubrecord:
    """Tests for scanning past the intensity series subrecord (21)."""

    def test_subrecord_after_intensity_series_is_found(self):
        """Test that the subrecord following an intensity series is read correctly."""
        # The intensity series' size field counts its own 4-byte identifier
        # word, as the GSF reference library writes it.
        raw = ping_record([(21, 8 + 4, b"12345678"), (156, 4, b"abcd")])

        assert scan_subrecord_ids(raw, 60) == [21, 156]
        assert scan_subrecords(raw, 60) == [(21, b"12345678"), (156, b"abcd")]

    def test_zero_size_intensity_series_does_not_stall(self):
        """Test that an intensity series with a zero size field still advances the scan."""
        raw = ping_record([(21, 0, b""), (1, 2, b"xy")])

        assert scan_subrecord_ids(raw, 60) == [21, 1]


class TestPingHeaderSize:
    """Tests for ping_header_size function."""

    def test_version_3_header(self):
        """Test that GSF 3.x pings have the 56-byte header."""
        assert ping_header_size("GSF-v03.09") == 56
        assert ping_header_size("GSF-v03.11") == 56

    def test_version_2_header(self):
        """Test that GSF 2.x pings have the 42-byte header, without the 3.x fields."""
        assert ping_header_size("GSF-v02.09") == 42

    def test_unparseable_version_defaults_to_version_3(self):
        """Test that a missing or malformed version falls back to the 56-byte header."""
        assert ping_header_size(None) == 56
        assert ping_header_size("garbage") == 56


class TestMissingSubrecords:
    """Tests for missing_subrecords function."""

    @staticmethod
    def ping_with(**beams):
        """Return a minimal decoded ping whose 'Beams' table holds the given columns."""
        return {"Beams": {"Depth_m": None, "AlongTrack_m": None, "BeamFlags": None, **beams}}

    def test_beam_arrays_are_judged_by_their_columns(self):
        """Test that a beam array is present exactly when its column is not None."""
        ping = self.ping_with(Depth_m=np.array([1.0]), BeamFlags=np.empty(0))
        required = [(1, "DepthArray"), (3, "AlongTrackArray"), (16, "BeamFlagsArray")]

        result = missing_subrecords(ping, required, lambda: pytest.fail("raw IDs not needed"))

        assert result == [(3, "AlongTrackArray")]

    def test_other_subrecords_are_looked_for_in_the_raw_ids(self):
        """Test that scale factors and other non-array subrecords use the raw subrecord IDs."""
        required = [(100, "ScaleFactors"), (156, "KMALLSpecific")]

        result = missing_subrecords(self.ping_with(), required, lambda: [1, 156])

        assert result == [(100, "ScaleFactors")]

    def test_raw_ids_are_read_at_most_once(self):
        """Test that the raw subrecord IDs are read only once, however many are needed."""
        calls = []

        def read_ids():
            calls.append(1)
            return [100]

        missing_subrecords(self.ping_with(), [(100, "ScaleFactors"), (21, "Intensity")], read_ids)

        assert len(calls) == 1
