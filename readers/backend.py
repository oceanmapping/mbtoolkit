"""Parser adapter contract and streaming lifecycle, independent of any library."""
from abc import ABC, abstractmethod
from dataclasses import replace

from .model import BackendError, DecodeRequest, FormatError, RecordData, UnsupportedFeatureError
from .stream import file_version, format_major, iter_frames, ping_header_size


class Decoder(ABC):
    """Plugins implement this contract; no library objects escape ``decode``.

    A decoder instance belongs to one reader. ``begin`` starts a fresh pass;
    scale-factor inheritance is private to that pass. Every requested record
    type is decoded in file order. ``close`` must release native handles and
    partially consumed generators. Returned arrays must own their storage.
    """
    info = None

    def begin(self, path, version, request):
        pass

    @abstractmethod
    def decode(self, frame, request):
        """Return RecordData using canonical names and engineering units."""

    def close(self):
        pass


class Reader:
    def __init__(self, path, decoder):
        self.path = str(path)
        self.decoder = decoder
        self.backend = decoder.info
        self.version = file_version(self.path)
        self.ping_header_size = ping_header_size(self.version)
        self._active = None

    def records(self, request=None):
        if self._active is not None:
            raise BackendError("Only one active record iterator is allowed per reader")
        request = request or DecodeRequest()
        unsupported = request.record_types - self.backend.decoded_record_types
        if unsupported:
            raise UnsupportedFeatureError(
                "{} cannot decode record types {}".format(self.backend.name, sorted(unsupported))
            )
        major = format_major(self.version)
        if 2 in request.record_types and major not in self.backend.format_majors:
            raise UnsupportedFeatureError("{} does not decode GSF {}.x pings".format(
                self.backend.name, major))
        self._active = self._records(request)
        return self._active

    def _records(self, request):
        frames = iter_frames(self.path)
        try:
            if request.record_types:
                try:
                    self.decoder.begin(self.path, self.version, request)
                except BackendError:
                    raise
                except Exception as exc:
                    raise BackendError("{} initialization failed: {}".format(
                        self.backend.name, exc)) from exc
            for frame in frames:
                if frame.checksum_valid is False:
                    raise FormatError("Invalid GSF checksum at 0x{:X}".format(frame.offset))
                frame = replace(frame, backend=self.backend)
                if frame.record_id in request.record_types:
                    try:
                        data = self.decoder.decode(frame, request)
                        if not isinstance(data, RecordData):
                            raise BackendError("Decoders must return toolkit RecordData instances")
                    except BackendError:
                        raise
                    except Exception as exc:
                        raise BackendError("{} failed on record {} at 0x{:X}: {}".format(
                            self.backend.name, frame.record_id, frame.offset, exc
                        )) from exc
                    frame = replace(frame, data=data)
                yield frame
        finally:
            try:
                frames.close()
            finally:
                self._active = None
                self.decoder.close()

    def close(self):
        if self._active is not None:
            active, self._active = self._active, None
            active.close()
        self.decoder.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
