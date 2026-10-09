"""
Shared utility functions for GSF file processing.
"""
import struct
from datetime import datetime
from typing import Any, Callable, Dict, List, Sequence, Tuple, Union

import numpy as np
from GSFU import BEAM_ARRAY_SUBRECORD_IDS

#: Maps each beam array subrecord ID to the gsfu 'Beams' column it is decoded into.
BEAM_ARRAY_LABELS = {sid: label for label, sid in BEAM_ARRAY_SUBRECORD_IDS.items()}


def posix_seconds(value: Union[str, np.datetime64, np.ndarray]) -> Union[float, np.ndarray]:
    """
    Convert a time decoded by gsfu to POSIX seconds.

    gsfu returns a ping's PingTime as an ISO 8601 string with a UTC offset,
    and attitude measurement times as a numpy datetime64 array. The tools
    report times as POSIX seconds, so this converts either form.

    Args:
        value: An ISO 8601 string, a numpy datetime64 value, or a numpy
            datetime64 array.

    Returns:
        The time in POSIX seconds, as a float for a single value or as a
        float64 array for an array.
    """
    if isinstance(value, str):
        return datetime.fromisoformat(value).timestamp()
    nanoseconds = np.asarray(value).astype("datetime64[ns]").astype(np.int64)
    seconds = nanoseconds / 1e9
    return float(seconds) if seconds.ndim == 0 else seconds


#: The swath bathymetry ping subrecord that holds the per-beam intensity
#: time series (gsf.h: GSF_SWATH_BATHY_SUBRECORD_INTENSITY_SERIES_ARRAY).
INTENSITY_SERIES_SUBRECORD = 21


def ping_header_size(gsf_version: str) -> int:
    """
    Return the size of a swath bathymetry ping's fixed header for a GSF version.

    The header precedes the ping's subrecords. GSF 3.x added the height,
    separation, and GPS tide corrector fields, which together with two
    spare bytes grow the header from 42 bytes to 56.

    Args:
        gsf_version: The file's version string, as read from its header
            record, for example "GSF-v03.09". gsfu's index_file() sets it
            on the gsf instance's gsfVersion attribute.

    Returns:
        The header size in bytes: 42 for GSF 2.x files and earlier, and 56
        otherwise, including when the version cannot be parsed.
    """
    try:
        major = int(gsf_version.split("v", 1)[1].split(".", 1)[0])
    except (AttributeError, IndexError, ValueError):
        return 56
    return 42 if major <= 2 else 56


def _subrecord_extent(sub_id: int, length: int) -> Tuple[int, int]:
    """
    Return where a subrecord's payload ends and the next subrecord begins.

    Every subrecord's size field counts only the payload that follows its
    4-byte identifier word, except the intensity series subrecord's. The
    GSF reference library's EncodeBRBIntensity() counts that subrecord's
    own identifier word in its size too.

    Args:
        sub_id: The subrecord's ID.
        length: The value of the subrecord's size field.

    Returns:
        A (payload_length, step) tuple: the number of payload bytes, and the
        number of bytes from the start of this subrecord to the next one.
    """
    if sub_id == INTENSITY_SERIES_SUBRECORD:
        return max(length - 4, 0), max(length, 4)
    return length, 4 + length


def scan_subrecords(raw: bytes, ping_header_size: int) -> List[Tuple[int, bytes]]:
    """
    Scan subrecords from a raw datagram buffer.
    
    Given the raw datagram buffer (size+id(+checksum)+ping header+subrecords),
    return a list of (subrecord_id, payload_bytes) tuples. The buffer must hold exactly one record:
    any bytes past the record's end, such as the start of the next record,
    are scanned as if they were more subrecords.
    
    Args:
        raw: Raw datagram buffer bytes
        ping_header_size: Size of the ping header in bytes, as returned by
            ping_header_size()
        
    Returns:
        List of tuples containing (subrecord_id, payload_bytes)
    """
    _, ident = struct.unpack(">II", raw[:8])
    has_checksum = ((ident >> 31) & 1) == 1
    offset = 8 + (4 if has_checksum else 0) + ping_header_size
    total = len(raw)
    subs = []
    while offset + 4 <= total:
        sub_id = raw[offset]
        length = int.from_bytes(raw[offset+1:offset+4], "big")
        payload_length, step = _subrecord_extent(sub_id, length)
        payload = raw[offset+4:offset+4+payload_length]
        subs.append((sub_id, payload))
        offset += step
    return subs


def scan_subrecord_ids(raw: bytes, ping_header_size: int) -> List[int]:
    """
    Scan subrecord IDs from a raw datagram buffer.
    
    Given the raw datagram buffer (size+id(+checksum)+ping header+subrecords),
    return a list of subrecord IDs only. The buffer must hold exactly one record:
    any bytes past the record's end, such as the start of the next record,
    are scanned as if they were more subrecords.
    
    Args:
        raw: Raw datagram buffer bytes
        ping_header_size: Size of the ping header in bytes, as returned by
            ping_header_size()
        
    Returns:
        List of subrecord IDs
    """
    _, ident = struct.unpack(">II", raw[:8])
    has_checksum = ((ident >> 31) & 1) == 1
    offset = 8 + (4 if has_checksum else 0) + ping_header_size
    subs = []
    total = len(raw)
    while offset + 4 <= total:
        sub_id = raw[offset]
        length = int.from_bytes(raw[offset+1:offset+4], "big")
        subs.append(sub_id)
        offset += _subrecord_extent(sub_id, length)[1]
    return subs


def missing_subrecords(
    ping: Dict[str, Any],
    required: Sequence[Tuple[int, str]],
    read_subrecord_ids: Callable[[], List[int]],
) -> List[Tuple[int, str]]:
    """
    Return the required subrecords a decoded swath bathymetry ping lacks.

    A beam array subrecord is present when gsfu decoded that array, that is,
    when the ping's 'Beams' column for it is not None. Any other subrecord,
    such as the scale factors (100), has no column, so it is looked for among
    the ping's raw subrecord IDs. Those are only read if one is needed.

    Args:
        ping: The ping, as decoded by gsfu.
        required: The required subrecords, as (subrecord_id, name) tuples.
        read_subrecord_ids: A function that returns the subrecord IDs in the
            ping's raw bytes, as scan_subrecord_ids() does.

    Returns:
        The (subrecord_id, name) tuples from `required` that the ping lacks,
        in the same order.
    """
    beams = ping.get("Beams", {})
    raw_ids = None
    missing = []
    for subrecord_id, name in required:
        label = BEAM_ARRAY_LABELS.get(subrecord_id)
        if label is not None:
            present = beams.get(label) is not None
        else:
            if raw_ids is None:
                raw_ids = read_subrecord_ids()
            present = subrecord_id in raw_ids
        if not present:
            missing.append((subrecord_id, name))
    return missing
