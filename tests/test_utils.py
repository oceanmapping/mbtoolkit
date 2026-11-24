"""
Tests for utility functions.
"""
import struct
from typing import Optional
from tools.utils import scan_subrecords, scan_subrecord_ids


def _make_swath_datagram(
    ping_header_size: int,
    ping_header: bytes,
    subrecords: bytes = b"",
    *,
    record_id: int = 0x00000002,
    checksum: Optional[int] = None,
    extra_tail: bytes = b"",
) -> bytes:
    """Build a SWATH_BATHYMETRY datagram using the same size-word rules as pygsf."""
    ident = record_id | (0x80000000 if checksum is not None else 0)
    header_after_size = struct.pack(">I", ident)
    if checksum is not None:
        header_after_size += struct.pack(">I", checksum)
    body = ping_header + subrecords
    sizeofdata = len(body)
    return struct.pack(">I", sizeofdata) + header_after_size + body + extra_tail


class TestScanSubrecords:
    """Tests for scan_subrecords function."""

    def test_scan_subrecords_basic(self):
        """Test scanning subrecords with basic structure."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size

        subrecord1 = struct.pack(">B", 1) + struct.pack(">I", 4)[1:] + b"data"
        subrecord2 = struct.pack(">B", 2) + struct.pack(">I", 3)[1:] + b"xyz"
        raw = _make_swath_datagram(
            ping_header_size, ping_header, subrecord1 + subrecord2
        )

        result = scan_subrecords(raw, ping_header_size)

        assert len(result) == 2
        assert result[0] == (1, b"data")
        assert result[1] == (2, b"xyz")

    def test_scan_subrecords_empty(self):
        """Test scanning subrecords when there are none."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size
        raw = _make_swath_datagram(ping_header_size, ping_header)

        result = scan_subrecords(raw, ping_header_size)

        assert result == []

    def test_scan_subrecords_with_checksum(self):
        """Test scanning subrecords when checksum is present."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size
        subrecord = struct.pack(">B", 100) + struct.pack(">I", 2)[1:] + b"ab"
        raw = _make_swath_datagram(
            ping_header_size,
            ping_header,
            subrecord,
            checksum=0x12345678,
        )

        result = scan_subrecords(raw, ping_header_size)

        assert result == [(100, b"ab")]


class TestScanSubrecordIds:
    """Tests for scan_subrecord_ids function."""

    def test_scan_subrecord_ids_basic(self):
        """Test scanning subrecord IDs with basic structure."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size
        subrecord1 = struct.pack(">B", 1) + struct.pack(">I", 4)[1:] + b"data"
        subrecord2 = struct.pack(">B", 2) + struct.pack(">I", 3)[1:] + b"xyz"
        raw = _make_swath_datagram(
            ping_header_size, ping_header, subrecord1 + subrecord2
        )

        result = scan_subrecord_ids(raw, ping_header_size)

        assert result == [1, 2]

    def test_scan_subrecord_ids_empty(self):
        """Test scanning subrecord IDs when there are none."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size
        raw = _make_swath_datagram(ping_header_size, ping_header)

        result = scan_subrecord_ids(raw, ping_header_size)

        assert result == []

    def test_scan_subrecord_ids_multiple(self):
        """Test scanning multiple subrecord IDs."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size

        subrecords = []
        for i in range(5):
            payload = b"x" * i
            subrecord = (
                struct.pack(">B", i + 10)
                + struct.pack(">I", len(payload))[1:]
                + payload
            )
            subrecords.append(subrecord)

        raw = _make_swath_datagram(
            ping_header_size, ping_header, b"".join(subrecords)
        )

        result = scan_subrecord_ids(raw, ping_header_size)

        assert result == [10, 11, 12, 13, 14]

    def test_scan_subrecords_ignores_tail_slack_after_brb(self):
        """Trailing bytes after BRB must not be reported as extra subrecords."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size

        kmall = struct.pack(">B", 156) + struct.pack(">I", 4)[1:] + b"kmal"
        brb_len = 5  # 1 byte bps + 4 bytes sample data; needs 3-byte pad to 8
        brb = struct.pack(">B", 21) + struct.pack(">I", brb_len)[1:] + b"\x10abcd"
        tail = b"\x85\x00\x00\x02\x00"  # would look like EM710_SPECIFIC if scanned

        raw = _make_swath_datagram(
            ping_header_size,
            ping_header,
            kmall + brb + tail,
        )

        result = scan_subrecords(raw, ping_header_size)

        assert [sid for sid, _ in result] == [156, 21]

    def test_scan_subrecords_stops_at_declared_datagram_end(self):
        """Do not read bytes past the declared datagram size word."""
        ping_header_size = 60
        ping_header = b"\x00" * ping_header_size
        subrecord = struct.pack(">B", 1) + struct.pack(">I", 2)[1:] + b"ok"
        raw = _make_swath_datagram(
            ping_header_size,
            ping_header,
            subrecord,
            extra_tail=b"\x99\x00\x00\x02zz",
        )

        result = scan_subrecords(raw, ping_header_size)

        assert result == [(1, b"ok")]
