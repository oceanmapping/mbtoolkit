"""Exact GSF record framing; semantic decoding belongs to parser adapters."""
import re
import struct
import os
from typing import Iterator, List, Tuple

from .model import FormatError, Record


def format_major(version: str) -> int:
    match = re.search(r"v(\d+)\.", version or "")
    return int(match.group(1)) if match else 3


def ping_header_size(version: str) -> int:
    return 42 if format_major(version) < 3 else 56


def timestamp_ns(frame):
    seconds, nanos = struct.unpack_from(">II", frame.raw, frame.header_size)
    return seconds * 1_000_000_000 + nanos


def iter_frames(path):
    with open(path, "rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        while True:
            offset = stream.tell()
            head = stream.read(8)
            if not head:
                return
            if len(head) != 8:
                raise FormatError("Truncated GSF record header at 0x{:X}".format(offset))
            size, ident = struct.unpack(">II", head)
            has_checksum = bool(ident & 0x80000000)
            if stream.tell() + size + (4 if has_checksum else 0) > file_size:
                raise FormatError("Truncated GSF record at 0x{:X}".format(offset))
            checksum = stream.read(4) if has_checksum else b""
            payload = stream.read(size)
            if (has_checksum and len(checksum) != 4) or len(payload) != size:
                raise FormatError("Truncated GSF record at 0x{:X}".format(offset))
            raw = head + checksum + payload
            checksum_valid = None
            if has_checksum:
                checksum_valid = struct.unpack(">I", checksum)[0] == (sum(payload) & 0xFFFFFFFF)
            yield Record(ident & 0x003FFFFF, offset, len(raw), 12 if has_checksum else 8,
                         raw, checksum_valid)


def file_version(path):
    frames = iter_frames(path)
    try:
        first = next(frames, None)
        if first and first.record_id == 1:
            try:
                return first.raw[first.header_size:].split(b"\0", 1)[0].decode("ascii")
            except UnicodeDecodeError as exc:
                raise FormatError("Invalid GSF version header") from exc
        return ""
    finally:
        frames.close()


INTENSITY_SERIES_SUBRECORD_ID = 21


def datagram_header_size(raw: bytes) -> int:
    """Return byte length of the GSF datagram header (size+id, plus checksum if set)."""
    if len(raw) < 8:
        return 8
    _, ident = struct.unpack(">II", raw[:8])
    has_checksum = ((ident >> 31) & 1) == 1
    return 12 if has_checksum else 8


def datagram_payload_end(raw: bytes) -> int:
    """
    Return the byte offset where this datagram ends in ``raw``.

    ``raw`` is expected to start at the datagram size word. The GSF size word
    is the payload size, excluding the size/id header and optional checksum.
    """
    if len(raw) < 8:
        return len(raw)
    size_word, _ = struct.unpack(">II", raw[:8])
    return datagram_header_size(raw) + size_word


def update_datagram_header(raw: bytes) -> bytes:
    """Update a rewritten record's payload size and optional checksum."""
    header_size = datagram_header_size(raw)
    result = bytearray(raw)
    struct.pack_into(">I", result, 0, len(result) - header_size)
    if header_size == 12:
        struct.pack_into(">I", result, 8, sum(result[12:]) & 0xFFFFFFFF)
    return bytes(result)


def _subrecord_spans(raw: bytes, ping_header_size: int) -> Iterator[Tuple[int, int, int]]:
    """Yield (id, header start, payload end), respecting record bounds and BRB padding."""
    hdr_len = datagram_header_size(raw)
    sub_end = datagram_payload_end(raw)
    offset = hdr_len + ping_header_size
    while offset + 4 <= sub_end:
        if offset + 4 > len(raw):
            break
        sub_id = raw[offset]
        length = int.from_bytes(raw[offset + 1:offset + 4], "big")
        payload_start = offset + 4
        payload_end = min(payload_start + length, sub_end, len(raw))
        if length > 0 and payload_end <= payload_start:
            break
        yield sub_id, offset, payload_end
        if payload_end < payload_start + length:
            break
        offset = payload_start + length
        if sub_id == INTENSITY_SERIES_SUBRECORD_ID and length % 4 > 0:
            offset += 4 - (length % 4)
            if offset > sub_end:
                break


def scan_subrecords(raw: bytes, ping_header_size: int) -> List[Tuple[int, bytes]]:
    """
    Scan subrecords from a raw SWATH_BATHYMETRY datagram buffer.

    Matches the bundled GSF reader (pygsf): stops at the declared datagram
    boundary, does not read past truncated payloads, and applies 4-byte padding
    after INTENSITY_SERIES (subrecord 21).

    Args:
        raw: Raw datagram buffer bytes starting at the datagram size word
        ping_header_size: Size of the ping header in bytes

    Returns:
        List of tuples containing (subrecord_id, payload_bytes)
    """
    return [
        (sid, raw[start + 4:end])
        for sid, start, end in _subrecord_spans(raw, ping_header_size)
    ]


def scan_subrecord_ids(raw: bytes, ping_header_size: int) -> List[int]:
    """
    Scan subrecord IDs from a raw datagram buffer.

    Args:
        raw: Raw datagram buffer bytes starting at the datagram size word
        ping_header_size: Size of the ping header in bytes

    Returns:
        List of subrecord IDs
    """
    return [sid for sid, _ in scan_subrecords(raw, ping_header_size)]
