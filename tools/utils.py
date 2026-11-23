"""
Shared utility functions for GSF file processing.
"""
import struct
from typing import Dict, Iterator, List, Tuple


# GSF field-size encoding in the high nibble of the scale-factor compression flag.
FIELD_SIZE_NAMES = {
    0x00: "DEFAULT",
    0x10: "1-byte",
    0x20: "2-byte",
    0x40: "4-byte",
}

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
    is the number of bytes following the 8-byte size/id header.
    """
    if len(raw) < 8:
        return len(raw)
    size_word, _ = struct.unpack(">II", raw[:8])
    return 8 + size_word


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


def parse_scale_factors(payload: bytes) -> List[Dict]:
    """
    Decode a SCALE_FACTORS (subrecord 100) payload.

    Layout (GSF):
      int32  num_scale_factors
      repeated num_scale_factors times:
        uint32 packed (subrecord_id in first byte, compression flag in second)
        int32  multiplier
        int32  offset

    Returns:
        List of dicts with keys: subrecord_id, field_size, field_size_name,
        multiplier, offset, compression_flag.
    """
    if len(payload) < 4:
        raise ValueError(f"SCALE_FACTORS payload too short ({len(payload)} bytes)")

    (count,) = struct.unpack_from(">i", payload, 0)
    if count < 0:
        raise ValueError(f"Negative scale-factor count: {count}")

    expected = 4 + count * 12
    if len(payload) < expected:
        raise ValueError(
            f"SCALE_FACTORS payload truncated: have {len(payload)} bytes, "
            f"need {expected} for {count} factors"
        )

    factors = []
    for i in range(count):
        packed, multiplier, offset = struct.unpack_from(">Iii", payload, 4 + i * 12)
        subrecord_id = (packed & 0xFF000000) >> 24
        compression_flag = (packed >> 16) & 0xFF
        field_size = compression_flag & 0xF0
        factors.append(
            {
                "subrecord_id": subrecord_id,
                "compression_flag": compression_flag,
                "field_size": field_size,
                "field_size_name": FIELD_SIZE_NAMES.get(
                    field_size, f"UNKNOWN(0x{field_size:02X})"
                ),
                "multiplier": multiplier,
                "offset": offset,
                "packed": packed,
            }
        )
    return factors


def scale_factor_fingerprint(factors: List[Dict]) -> Tuple:
    """Stable fingerprint for comparing scale-factor sets across pings."""
    return tuple(
        (f["subrecord_id"], f["compression_flag"], f["multiplier"], f["offset"])
        for f in factors
    )


# Sensible defaults for arrays that GSF 3.05 Table 4-3 says are scaled before
# storage: (multiplier, offset, compression_flag/field_size).
# INTENSITY_SERIES_ARRAY (21) is intentionally excluded — BRB intensity samples
# are stored as integer dB in a structured subrecord, not via SCALE_FACTORS.
DEFAULT_SCALE_FACTORS = {
    1: (1000, 0, 0x00),    # DEPTH_ARRAY
    2: (100, 0, 0x00),     # ACROSS_TRACK_ARRAY
    3: (100, 0, 0x00),     # ALONG_TRACK_ARRAY
    4: (100000, 0, 0x00),  # TRAVEL_TIME_ARRAY
    5: (100, 0, 0x00),     # BEAM_ANGLE_ARRAY
    6: (1, 0, 0x00),       # MEAN_CALIBRATED_AMPLITUDE_ARRAY
    7: (1, 0, 0x00),       # MEAN_RELATIVE_AMPLITUDE_ARRAY
    8: (100, 0, 0x00),     # ECHO_WIDTH_ARRAY
    10: (100, 0, 0x00),    # RECEIVE_HEAVE_ARRAY
    11: (100, 0, 0x00),    # DEPTH_ERROR_ARRAY (obsolete)
    12: (100, 0, 0x00),    # ACROSS_TRACK_ERROR_ARRAY (obsolete)
    13: (100, 0, 0x00),    # ALONG_TRACK_ERROR_ARRAY (obsolete)
    14: (1000, 0, 0x00),   # NOMINAL_DEPTH_ARRAY
    18: (100, 0, 0x00),    # BEAM_ANGLE_FORWARD_ARRAY
}

# Arrays that require a SCALE_FACTORS entry when present (GSF 3.05 Table 4-3).
REQUIRED_SCALE_FACTOR_ARRAY_IDS = set(DEFAULT_SCALE_FACTORS.keys())
SCALED_ARRAY_IDS = REQUIRED_SCALE_FACTOR_ARRAY_IDS

KNOWN_FIELD_SIZES = {0x00, 0x10, 0x20, 0x40}
SCALE_FACTORS_SUBRECORD_ID = 100


def make_empty_subrecord(sub_id: int) -> bytes:
    """
    Build an empty subrecord with zero-length payload.

    Format: [1-byte subrecord_id][3-byte length=0].
    """
    return struct.pack(">B3s", sub_id & 0xFF, b"\x00\x00\x00")


def make_scale_factor(
    subrecord_id: int,
    multiplier: int,
    offset: int,
    compression_flag: int = 0x00,
) -> Dict:
    """Build a scale-factor dict in the same shape as parse_scale_factors()."""
    field_size = compression_flag & 0xF0
    return {
        "subrecord_id": subrecord_id,
        "compression_flag": compression_flag,
        "field_size": field_size,
        "field_size_name": FIELD_SIZE_NAMES.get(
            field_size, f"UNKNOWN(0x{field_size:02X})"
        ),
        "multiplier": int(multiplier),
        "offset": int(offset),
        "packed": ((subrecord_id & 0xFF) << 24) | ((compression_flag & 0xFF) << 16),
    }


def default_scale_factor(subrecord_id: int) -> Dict:
    """Return a sensible default scale factor for a subrecord id."""
    if subrecord_id in DEFAULT_SCALE_FACTORS:
        mult, off, flag = DEFAULT_SCALE_FACTORS[subrecord_id]
    else:
        mult, off, flag = (1, 0, 0x00)
    return make_scale_factor(subrecord_id, mult, off, flag)


def is_unreasonable_scale_factor(factor: Dict) -> bool:
    """True if multiplier/offset/field-size look invalid or unsafe."""
    if factor.get("multiplier", 0) == 0:
        return True
    if abs(int(factor.get("multiplier", 0))) > 1_000_000_000:
        return True
    if abs(int(factor.get("offset", 0))) > 1_000_000_000:
        return True
    if (int(factor.get("compression_flag", 0)) & 0xF0) not in KNOWN_FIELD_SIZES:
        return True
    return False


def pack_scale_factors(factors: List[Dict]) -> bytes:
    """Serialize scale-factor entries into a SCALE_FACTORS payload."""
    parts = [struct.pack(">i", len(factors))]
    for f in factors:
        sid = int(f["subrecord_id"]) & 0xFF
        flag = int(f.get("compression_flag", 0)) & 0xFF
        packed = (sid << 24) | (flag << 16)
        parts.append(
            struct.pack(
                ">Iii",
                packed,
                int(f["multiplier"]),
                int(f["offset"]),
            )
        )
    return b"".join(parts)


def factors_to_map(factors: List[Dict]) -> Dict[int, Dict]:
    """Index scale factors by subrecord id (last wins)."""
    return {int(f["subrecord_id"]): f for f in factors}


def repair_scale_factor_set(
    existing_factors: List[Dict],
    needed_array_ids: List[int],
) -> Tuple[List[Dict], List[str]]:
    """
    Merge/fix a scale-factor set for the arrays present in a ping.

    Preserves reasonable existing values. Adds defaults for missing ids.
    Replaces unreasonable entries with defaults.

    Returns:
        (repaired_factors_sorted_by_id, list_of_change_descriptions)
    """
    current = factors_to_map(existing_factors)
    changes = []

    for sid, factor in list(current.items()):
        # Only rewrite unreasonable entries for arrays that the spec scales.
        if sid in REQUIRED_SCALE_FACTOR_ARRAY_IDS and is_unreasonable_scale_factor(factor):
            current[sid] = default_scale_factor(sid)
            changes.append(
                f"replaced unreasonable scale factor for id {sid}"
            )

    for sid in sorted(set(needed_array_ids) & REQUIRED_SCALE_FACTOR_ARRAY_IDS):
        if sid not in current:
            current[sid] = default_scale_factor(sid)
            changes.append(f"added missing scale factor for id {sid}")

    repaired = [current[sid] for sid in sorted(current)]
    return repaired, changes


def replace_or_insert_scale_factors(
    raw: bytes,
    ping_header_size: int,
    factors: List[Dict],
) -> bytes:
    """
    Rewrite a SWATH_BATHYMETRY datagram so it contains the given SCALE_FACTORS.

    If a SCALE_FACTORS subrecord already exists, its payload is replaced.
    Otherwise a new SCALE_FACTORS subrecord is inserted at the start of the
    subrecord list. All other bytes, including padding, are preserved. The
    datagram size word is updated.
    """
    size_word, ident = struct.unpack(">II", raw[:8])
    has_checksum = ((ident >> 31) & 1) == 1
    hdr_len = 8 + (4 if has_checksum else 0)
    sub_start = hdr_len + ping_header_size

    payload = pack_scale_factors(factors)
    replacement = bytes([SCALE_FACTORS_SUBRECORD_ID]) + len(payload).to_bytes(3, "big") + payload
    record_end = min(datagram_payload_end(raw), len(raw))
    span = next(
        ((start, end) for sid, start, end in _subrecord_spans(raw, ping_header_size)
         if sid == SCALE_FACTORS_SUBRECORD_ID),
        (sub_start, sub_start),
    )
    start, end = span
    new_raw = bytearray(raw[:start] + replacement + raw[end:record_end])

    # GSF size word is the record length excluding the 8-byte header
    # (size + id). sniffDatagramHeader returns size_word + 8 as nbytes.
    new_size = len(new_raw) - 8
    struct.pack_into(">I", new_raw, 0, new_size)
    return bytes(new_raw)
