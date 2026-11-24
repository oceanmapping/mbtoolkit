"""Optional gsfu adapter. GSFU dictionaries remain inside this module."""
import numpy as np

from ..backend import Decoder
from ..model import AttitudeData, BackendInfo, BackendUnavailableError, RecordData, UnsupportedFeatureError
from ..stream import iter_frames, ping_header_size, timestamp_ns

PING_FIELDS = {
    "longitude": "Longitude_deg", "latitude": "Latitude_deg", "num_beams": "NumberBeams",
    "centre_beam": "CenterBeam", "ping_flags": "PingFlags", "tide_corrector": "TideCorrector_m",
    "depth_corrector": "DepthCorrector_m", "heading": "Heading_deg", "pitch": "Pitch_deg",
    "roll": "Roll_deg", "heave": "Heave_m", "course": "Course_deg", "speed": "Speed_kn",
    "height": "Height_m", "separation": "SEP_m", "gps_tide_corrector": "GPSTideCorrector_m",
}


class GsfuDecoder(Decoder):
    def __init__(self):
        try:
            from GSFU import BEAM_ARRAY_SUBRECORD_IDS, gsf
        except ImportError as exc:
            raise BackendUnavailableError(
                'The gsfu backend requires Python >=3.8 and pip install ".[gsfu]"'
            ) from exc
        try:
            from importlib.metadata import version
        except ImportError:
            from importlib_metadata import version
        self._factory = gsf
        self._arrays = {sid: label for label, sid in BEAM_ARRAY_SUBRECORD_IDS.items()}
        self.info = BackendInfo("gsfu", version("gsfu"), frozenset({1, 2, 12}),
                                frozenset(self._arrays), frozenset({2, 3}))
        self._iterators = {}

    def begin(self, path, version, request):
        import pandas as pd
        self._native = self._factory(path)
        # Framing and unknown-record retention belong to the toolkit. gsfu's
        # indexer rejects unknown IDs before any selected decoder can run.
        # Populate its public Index table with known records at physical offsets.
        columns = {key: [] for key in
                   ("RecordID", "ByteOffset", "RecordSize", "TotalBytes", "ChecksumFlag")}
        for frame in iter_frames(path):
            if frame.record_id in request.record_types:
                for key, value in zip(columns, (frame.record_id, frame.offset,
                                               frame.total_size - frame.header_size,
                                               frame.total_size, frame.header_size == 12)):
                    columns[key].append(value)
        self._native.Index = pd.DataFrame(columns)
        self._native.gsfVersion = version
        self._iterators = {}
        self._ping_header_size = ping_header_size(version)

    def decode(self, frame, request):
        if frame.record_id not in self._iterators:
            self._iterators[frame.record_id] = self._native.iter_records(frame.record_id)
        _rid, offset, native = next(self._iterators[frame.record_id])
        if int(offset) != frame.offset:
            raise ValueError("gsfu record offsets do not match the physical record stream")
        if frame.record_id == 2:
            fields = {name: native[key] for name, key in PING_FIELDS.items() if key in native}
            fields["timestamp_ns"] = timestamp_ns(frame)
            if fields["centre_beam"] >= 32768:
                fields["centre_beam"] -= 65536
            fields["reserved"] = int.from_bytes(
                frame.raw[frame.header_size + 22:frame.header_size + 24], "big", signed=True)
            if self._ping_header_size == 56:
                fields["spare"] = int.from_bytes(
                    frame.raw[frame.header_size + 54:frame.header_size + 56], "big", signed=True)
            else:
                for key in ("height", "separation", "gps_tide_corrector"):
                    fields.pop(key, None)
            arrays = {}
            if request.beam_arrays:
                beams = native.get("Beams", {})
                arrays = {sid: beams[label] for sid, label in self._arrays.items()
                          if beams.get(label) is not None}
            return RecordData(fields, arrays, diagnostics=tuple(native.get("Notes", ())))
        if frame.record_id == 1:
            return RecordData({"version": native["Version"]})
        if frame.record_id == 12:
            # gsfu 0.5.1 converts absolute times through float seconds. Recover
            # exact UTC nanoseconds while normalizing the wire's millisecond offsets.
            count = native["NumMeasurements"]
            offsets = np.frombuffer(frame.raw, dtype=">u2", count=count * 5,
                                    offset=frame.header_size + 10)[0::5].astype(np.int64)
            times = timestamp_ns(frame) + offsets * 1_000_000
            samples = AttitudeData(times, native["Roll_deg"],
                                   native["Pitch_deg"], native["Heave_m"], native["Heading_deg"])
            return RecordData(attitude=samples)
        raise UnsupportedFeatureError("No normalized projection for this record type")

    def close(self):
        for iterator in self._iterators.values():
            iterator.close()
        self._iterators = {}
        native = getattr(self, "_native", None)
        if native is not None and native.FID is not None and not native.FID.closed:
            native.closeFile()
