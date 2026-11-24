"""Optional reference-C decoder; native objects never leave this adapter."""
import os
import re
import struct

import numpy as np

from readers import (
    AttitudeData, BackendInfo, BackendUnavailableError, Decoder, FormatError,
    RecordData, UnsupportedFeatureError,
)
from readers.stream import iter_frames, ping_header_size

# Uncompressed widths actually consumed by the reference decoder for each SID.
ARRAY_WIDTHS = {
    1: (2, 4), 2: (2, 4), 3: (2, 4), 4: (2, 4), 5: (2,),
    6: (1, 2), 7: (1, 2), 8: (1, 2), 9: (1,), 10: (1,),
    11: (2,), 12: (2,), 13: (2,), 14: (2, 4), 17: (1,),
    18: (2,), 19: (2,), 20: (2,), 22: (1,), 23: (1,), 24: (1,),
    25: (1,), 26: (1,), 27: (2,), 28: (2,), 29: (1, 2, 4),
    30: (1, 2, 4), 31: (1, 2, 4),
}


def _compressed_extent_valid(data, beams):
    if len(data) < 5 or (len(data) - 1) % 4:
        return False
    order, version = data[0] & 31, data[0] >> 5
    if version > 1:
        raise UnsupportedFeatureError("Unsupported GSF compression version {}".format(version))
    words = np.frombuffer(data, dtype=">u4", offset=1)
    if order > 3 or order > beams or order > len(words):
        return False
    # Simple-16 expands into a fixed native buffer before RLE decoding. Bound
    # that intermediate output as well as the final declared beam count.
    counts = (14, 12, 10, 9, 8, 8, 7, 6, 6, 5, 5, 4, 3, 2, 2, 1)
    return sum(counts[int(word) >> 28] for word in words[order:]) <= beams - order


class GsflibDecoder(Decoder):
    def __init__(self):
        try:
            from . import _native
        except ImportError as exc:
            raise BackendUnavailableError(
                "gsflib requires the compiled mbtoolkit-gsflib plugin and matching GSF library"
            ) from exc
        self._native = _native
        self._session = None
        self.info = BackendInfo("gsflib", _native.version, frozenset({1, 2, 12}),
                                frozenset(set(range(1, 32)) - {21}), frozenset({2, 3}))

    def begin(self, path, version, request):
        self.close()
        if not version:
            raise UnsupportedFeatureError("gsflib requires a GSF file header")
        self._header_size = ping_header_size(version)
        self._factors = {}
        # gsfOpen reads the first header itself. Apply the shared framing and
        # checksum rules before that native read, as for all later records.
        frames = iter_frames(path)
        try:
            header = next(frames)
        finally:
            frames.close()
        if header.checksum_valid is False:
            raise FormatError("Invalid GSF checksum at 0x{:X}".format(header.offset))
        if header.record_id != 1 or len(header.raw) - header.header_size < 12:
            raise FormatError("gsflib requires a complete initial GSF header")
        match = re.fullmatch(r"GSF-v(\d+)\.(\d+)", version)
        if match is None:
            raise UnsupportedFeatureError("Unrecognized GSF version header")
        self._session = self._native.open(os.fsencode(path), int(match[1]), int(match[2]))

    def _validate(self, frame):
        """Check variable counts and array extents before entering the C decoder."""
        payload = frame.raw[frame.header_size:]
        brb = False
        if frame.record_id == 1:
            if len(payload) < 12:
                raise FormatError("Truncated GSF file header")
        elif frame.record_id == 12:
            if len(payload) < 10:
                raise FormatError("Truncated attitude header")
            count = int.from_bytes(payload[8:10], "big")
            if count > 32767 or 10 + count * 10 > len(payload):
                raise FormatError("Invalid attitude measurement count")
        elif frame.record_id == 2:
            if len(payload) < self._header_size:
                raise FormatError("Truncated ping header")
            beams = int.from_bytes(payload[16:18], "big", signed=True)
            if beams <= 0:
                raise FormatError("gsflib requires a positive beam count")
            pos = self._header_size
            projected = [payload[:pos]]
            while len(payload) - pos >= 4:
                if len(payload) - pos == 4 and payload[pos:] == bytes(4):  # null sensor identifier
                    break
                sid, size = payload[pos], int.from_bytes(payload[pos + 1:pos + 4], "big")
                pos += 4
                # Reference BRB lengths include their own four-byte subrecord header.
                length = size - 4 if sid == 21 else size
                if not sid or length < 0 or pos + length > len(payload):
                    raise FormatError("Invalid ping subrecord extent")
                data = payload[pos:pos + length]
                if sid == 21:
                    brb = True
                else:
                    projected.append(payload[pos - 4:pos + length])
                if sid == 100:
                    if length < 4:
                        raise FormatError("Truncated scale factors")
                    count = int.from_bytes(data[:4], "big")
                    if not 1 <= count <= 31 or length != 4 + count * 12:
                        raise FormatError("Invalid scale-factor count")
                    for index in range(count):
                        ident, multiplier, _offset = struct.unpack_from(">IIi", data, 4 + index * 12)
                        array_id, flag = ident >> 24, (ident >> 16) & 255
                        if not 1 <= array_id <= 31 or multiplier <= 0:
                            raise FormatError("Invalid array scale factor")
                        self._factors[array_id] = flag
                elif 1 <= sid <= 31 and sid != 21:
                    if sid == 15:
                        valid = length == (beams + 3) // 4
                    elif sid == 16:
                        valid = length == beams
                    else:
                        if sid not in self._factors:
                            raise FormatError("Missing scale factor for array {}".format(sid))
                        flag = self._factors[sid]
                        if flag & 15:
                            if flag & 15 != 1:
                                raise UnsupportedFeatureError("Unsupported GSF compression flag")
                            valid = _compressed_extent_valid(data, beams)
                        else:
                            valid = length in tuple(beams * width for width in ARRAY_WIDTHS[sid])
                    if not valid:
                        raise FormatError("Invalid array {} size for {} beams".format(sid, beams))
                pos += length
            if len(payload) - pos < 4 and any(payload[pos:]):
                raise FormatError("Nonzero ping padding")
            if brb:
                # API v1 has no structured intensity projection. Keep BRB in
                # Record.raw, but avoid allocating its nested native buffers.
                payload = b"".join(projected)
                payload += bytes((-len(payload)) % 4)
        return payload, brb

    def decode(self, frame, request):
        payload, brb = self._validate(frame)
        fields, buffers, samples = self._native.read(
            self._session, frame.record_id, payload, request.beam_arrays)
        if frame.record_id == 2:
            if self._header_size == 56:
                fields["spare"] = int.from_bytes(payload[54:56], "big", signed=True)
            else:
                for key in ("height", "separation", "gps_tide_corrector"):
                    fields.pop(key, None)
        arrays = {sid: np.frombuffer(data, dtype=dtype) for sid, (dtype, data) in buffers.items()}
        attitude = None
        if samples is not None:
            attitude = AttitudeData(np.frombuffer(samples[0], dtype="=i8"),
                                    *(np.frombuffer(data, dtype="=f8") for data in samples[1:]))
        diagnostics = ("BRB intensity series has no API v1 projection",) if brb else ()
        return RecordData(fields, arrays, attitude, diagnostics)

    def close(self):
        if self._session is not None:
            session, self._session = self._session, None
            self._native.close(session)
