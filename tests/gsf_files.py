"""
Helpers that build small, synthetic GSF files for the tests.

The files are written with the gsfu library's public write API, so the
tests need no sample data files. Each ping and attitude record is
described by a small dictionary or list, and anything the tests do not
care about is filled in with a fixed, plausible value.
"""

import struct
from typing import Dict, List, Optional, Sequence

from GSFU import gsf
from GSFU.gsfu import new_attitude, new_swath_bathymetry_ping

#: Size, in bytes, of a GSF record's size and identifier words.
RECORD_FRAMING_SIZE = 8

#: Size, in bytes, of the fixed swath bathymetry ping header that precedes
#: the subrecords, for the GSF 3.x files gsfu writes.
PING_HEADER_SIZE = 56

#: A complete set of beam arrays for a three-beam ping, enough to satisfy
#: every array the toolkit's profiles commonly require.
FULL_BEAMS = {
    "Depth_m": [100.0, 101.5, 99.25],
    "AcrossTrack_m": [-50.0, 0.0, 50.0],
    "AlongTrack_m": [0.5, 0.0, -0.5],
    "TravelTime_s": [0.14, 0.13, 0.14],
    "BeamFlags": [0, 0, 1],
}


def ping(time: float, beams: Optional[Dict[str, Sequence[float]]] = None, **fields) -> dict:
    """
    Describe one swath bathymetry ping for write_gsf().

    Args:
        time: The ping time, in POSIX seconds.
        beams: The ping's beam arrays, keyed by gsfu 'Beams' column label.
            Defaults to FULL_BEAMS.
        **fields: Any other ping header fields to set, using gsfu's field
            names, such as CenterBeam=1.

    Returns:
        A gsfu swath bathymetry ping record, ready to be written.
    """
    beams = FULL_BEAMS if beams is None else beams
    record = new_swath_bathymetry_ping()
    record.update(
        PingTime=time,
        Longitude_deg=-70.75,
        Latitude_deg=43.07,
        NumberBeams=len(next(iter(beams.values()))) if beams else 0,
        CenterBeam=1,
    )
    record.update(fields)
    record["Beams"].update(beams)
    return record


def attitude(times: Sequence[float]) -> dict:
    """
    Describe one attitude record, with one measurement per time, for write_gsf().

    Args:
        times: The measurement times, in POSIX seconds.

    Returns:
        A gsfu attitude record, ready to be written.
    """
    count = len(times)
    record = new_attitude()
    record.update(
        Time=list(times),
        Pitch_deg=[0.5] * count,
        Roll_deg=[-1.25] * count,
        Heave_m=[0.1] * count,
        Heading_deg=[90.0] * count,
    )
    return record


def write_gsf(path, records: List[dict]) -> str:
    """
    Write a GSF file containing a header record followed by the given records.

    Args:
        path: The path of the file to write.
        records: Ping records from ping() and attitude records from
            attitude(), in the order they should appear in the file.

    Returns:
        The path of the written file, as a string.
    """
    path = str(path)
    writer = gsf(path)
    writer.write_header()
    for record in records:
        if "PingTime" in record:
            writer.write_swath_bathymetry_ping(record)
        else:
            writer.write_attitude(record)
    writer.closeFile()
    return path


def remove_subrecord(path, ping_number: int, subrecord_id: int) -> None:
    """
    Remove one subrecord from one ping of an existing GSF file, in place.

    gsfu writes every ping it can describe, so the tests use this to make
    pings it would never write, such as a ping with no scale factors. The
    ping's record size is reduced to match. The file must not use
    checksums, which gsfu does not write by default.

    Args:
        path: The path of the GSF file to modify.
        ping_number: Which swath bathymetry ping to modify, counting from 0.
        subrecord_id: The ID of the subrecord to remove from that ping.

    Raises:
        ValueError: If the file has fewer pings, if the ping has no
            subrecord with that ID, or if removing it would leave the
            record's size off the four-byte boundary GSF records keep.
    """
    offset, size = _ping_location(path, ping_number)

    with open(path, "rb") as f:
        data = f.read()
    start = offset + RECORD_FRAMING_SIZE + PING_HEADER_SIZE
    end = offset + RECORD_FRAMING_SIZE + size
    position = start
    while position + 4 <= end:
        word = struct.unpack(">I", data[position : position + 4])[0]
        length = word & 0x00FFFFFF
        if word >> 24 == subrecord_id:
            removed = 4 + length
            if removed % 4:
                raise ValueError(
                    f"removing subrecord {subrecord_id} ({removed} bytes) would leave "
                    "the record size off its four-byte boundary"
                )
            framing = struct.pack(">I", size - removed) + data[offset + 4 : offset + 8]
            data = (
                data[:offset] + framing + data[offset + 8 : position] + data[position + removed :]
            )
            with open(path, "wb") as f:
                f.write(data)
            return
        position += 4 + length
    raise ValueError(f"ping {ping_number} has no subrecord {subrecord_id}")


def _ping_location(path, ping_number: int):
    """
    Find one swath bathymetry ping in a GSF file.

    Args:
        path: The path of the GSF file.
        ping_number: Which ping to find, counting from 0.

    Returns:
        A (byte_offset, record_size) tuple: where the ping's record starts,
        and the size its size field gives, which excludes the 8 bytes of
        size and identifier words.

    Raises:
        ValueError: If the file has fewer pings.
    """
    reader = gsf(str(path))
    reader.index_file()
    reader.closeFile()
    pings = reader.Index[reader.Index["RecordID"] == 2]
    if ping_number >= len(pings):
        raise ValueError(f"the file has only {len(pings)} pings")
    return int(pings["ByteOffset"].iloc[ping_number]), int(pings["RecordSize"].iloc[ping_number])


def insert_subrecord(
    path, ping_number: int, subrecord_id: int, payload: bytes = b"", first: bool = False
) -> None:
    """
    Insert a subrecord into one ping of an existing GSF file, in place.

    The tests use this to make pings gsfu would never write, such as one
    holding a zero-length subrecord. The ping's record size is increased to
    match. The file must not use checksums, which gsfu does not write by
    default.

    Args:
        path: The path of the GSF file to modify.
        ping_number: Which swath bathymetry ping to modify, counting from 0.
        subrecord_id: The ID of the subrecord to insert.
        payload: The subrecord's contents, after its identifier word.
            Defaults to none, making a zero-length subrecord.
        first: If True, insert the subrecord before all of the ping's other
            subrecords; otherwise append it after them.

    Raises:
        ValueError: If the file has fewer pings, or if the subrecord would
            leave the record's size off the four-byte boundary GSF records keep.
    """
    added = 4 + len(payload)
    if added % 4:
        raise ValueError(
            f"a {added}-byte subrecord would leave the record size off its four-byte boundary"
        )
    offset, size = _ping_location(path, ping_number)
    with open(path, "rb") as f:
        data = f.read()
    if first:
        position = offset + RECORD_FRAMING_SIZE + PING_HEADER_SIZE
    else:
        position = offset + RECORD_FRAMING_SIZE + size
    subrecord = struct.pack(">I", (subrecord_id << 24) | len(payload)) + payload
    framing = struct.pack(">I", size + added) + data[offset + 4 : offset + 8]
    data = data[:offset] + framing + data[offset + 8 : position] + subrecord + data[position:]
    with open(path, "wb") as f:
        f.write(data)
