"""Normalize the bundled pygsf reader behind the toolkit's decoder contract."""
import struct

import numpy as np

from ..backend import Decoder
from ..model import AttitudeData, BackendInfo, RecordData, UnsupportedFeatureError
from ..stream import scan_subrecords, timestamp_ns

PING_FIELDS = {
    "longitude": "longitude", "latitude": "latitude", "num_beams": "numbeams",
    "centre_beam": "centrebeam", "ping_flags": "pingflags", "reserved": "reserved",
    "tide_corrector": "tidecorrector", "depth_corrector": "depthcorrector",
    "heading": "heading", "pitch": "pitch", "roll": "roll", "heave": "heave",
    "course": "course", "speed": "speed", "spare": "spare",
}
ARRAY_FIELDS = {
    1: "DEPTH_ARRAY", 2: "ACROSS_TRACK_ARRAY", 3: "ALONG_TRACK_ARRAY",
    4: "TRAVEL_TIME_ARRAY", 5: "BEAM_ANGLE_ARRAY", 6: "MEAN_CAL_AMPLITUDE_ARRAY",
    7: "MEAN_REL_AMPLITUDE_ARRAY", 9: "QUALITY_FACTOR_ARRAY", 15: "QUALITY_FLAGS_ARRAY",
    16: "BEAM_FLAGS_ARRAY", 18: "BEAM_ANGLE_FORWARD_ARRAY", 19: "VERTICAL_ERROR_ARRAY",
    20: "HORIZONTAL_ERROR_ARRAY", 22: "SECTOR_NUMBER_ARRAY",
}


class PygsfDecoder(Decoder):
    info = BackendInfo("pygsf", "bundled", frozenset({1, 2, 12}),
                       frozenset(ARRAY_FIELDS) - {15})

    def begin(self, path, version, request):
        from ..base import _pygsf_module
        self._module = _pygsf_module
        self._stream = open(path, "rb")
        self._factors = {}
        self._compressed = set()

    def decode(self, frame, request):
        classes = {1: "CHEADER", 2: "SWATH_BATHYMETRY_PING", 12: "CATTITUDE"}
        self._stream.seek(frame.offset)
        native = getattr(self._module, classes[frame.record_id])(
            self._stream, frame.total_size, frame.record_id, frame.header_size
        )
        if frame.record_id == 2:
            subs = scan_subrecords(frame.raw, 56)
            present = {sid for sid, _ in subs}
            for sid, payload in subs:
                if sid == 100 and len(payload) >= 4:
                    count = struct.unpack_from(">I", payload)[0]
                    for index in range(min(count, (len(payload) - 4) // 12)):
                        packed = struct.unpack_from(">I", payload, 4 + index * 12)[0]
                        array_id = packed >> 24
                        if (packed >> 16) & 0x0F:
                            self._compressed.add(array_id)
                        else:
                            self._compressed.discard(array_id)
            if request.beam_arrays and present & self._compressed:
                raise UnsupportedFeatureError("pygsf does not decode compressed beam arrays")
            if request.beam_arrays and 15 in present:
                raise UnsupportedFeatureError("pygsf does not decode packed quality flags")
            self._factors = native.read(self._factors, headeronly=not request.beam_arrays) or self._factors
            fields = {name: getattr(native, attr) for name, attr in PING_FIELDS.items()}
            fields["ping_flags"] &= 0xFFFF
            fields["timestamp_ns"] = timestamp_ns(frame)
            # pygsf exposes these three GSF millimetre fields divided by 100.
            fields.update(height=native.height / 10, separation=native.separation / 10,
                          gps_tide_corrector=native.gpstidecorrector / 10)
            arrays = {}
            if request.beam_arrays:
                for sid, attr in ARRAY_FIELDS.items():
                    value = np.asarray(getattr(native, attr, []))
                    if sid in present and (value.size or native.numbeams == 0):
                        arrays[sid] = value
                if 16 in present:
                    payload = next(payload for sid, payload in subs if sid == 16)
                    arrays[16] = np.frombuffer(payload, dtype=np.uint8, count=native.numbeams)
            diagnostics = tuple("Subrecord {} is present but not decoded by pygsf".format(sid)
                                for sid in sorted(present) if 1 <= sid <= 31 and sid not in arrays)
            return RecordData(fields, arrays, diagnostics=diagnostics if request.beam_arrays else ())
        native.read()
        if frame.record_id == 1:
            return RecordData({"version": native.version})
        if frame.record_id == 12:
            base = timestamp_ns(frame)
            offsets = np.asarray(native.attitudearray[0::5]).astype(np.uint16).astype(np.int64)
            heading = np.asarray(native.attitudearray[4::5]).astype(np.uint16) / 100
            samples = AttitudeData(base + offsets * 1_000_000, native.roll, native.pitch,
                                   native.heave, heading)
            return RecordData(attitude=samples)
        raise UnsupportedFeatureError("No normalized projection for this record type")

    def close(self):
        stream = getattr(self, "_stream", None)
        if stream is not None:
            stream.close()
            self._stream = None
