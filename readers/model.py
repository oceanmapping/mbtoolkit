"""Toolkit-owned data contracts shared by all GSF parser adapters."""
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

import numpy as np

HEADER = 1
SWATH_BATHYMETRY = 2
SOUND_VELOCITY_PROFILE = 3
PROCESSING_PARAMETERS = 4
SENSOR_PARAMETERS = 5
COMMENT = 6
HISTORY = 7
NAVIGATION_ERROR = 8
SWATH_BATHY_SUMMARY = 9
SINGLE_BEAM_SOUNDING = 10
HV_NAVIGATION_ERROR = 11
ATTITUDE = 12


class BackendError(RuntimeError):
    """A selected backend cannot complete the requested operation."""


class BackendUnavailableError(BackendError):
    pass


class UnsupportedFeatureError(BackendError):
    pass


class FormatError(BackendError):
    pass


@dataclass(frozen=True)
class BackendInfo:
    name: str
    version: str
    decoded_record_types: FrozenSet[int]
    decoded_beam_arrays: FrozenSet[int] = frozenset()
    format_majors: FrozenSet[int] = frozenset({3})
    api_version: int = 1


@dataclass(frozen=True)
class DecodeRequest:
    record_types: FrozenSet[int] = frozenset()
    beam_arrays: bool = False


@dataclass
class AttitudeData:
    """UTC epoch nanoseconds, angles in degrees, and heave in metres."""
    timestamp_ns: np.ndarray
    roll: np.ndarray
    pitch: np.ndarray
    heave: np.ndarray
    heading: np.ndarray

    def __post_init__(self):
        # Native libraries may reuse their buffers on the next read.
        for name in ("timestamp_ns", "roll", "pitch", "heave", "heading"):
            setattr(self, name, np.array(getattr(self, name), copy=True))


@dataclass
class RecordData:
    """Canonical fields, beam arrays by GSF ID, and optional attitude samples.

    Field names follow profile snake_case names. Physical values use GSF
    engineering units (metres, seconds, degrees, knots, and dB); absolute
    timestamps are integer UTC epoch nanoseconds. Missing arrays are absent
    from ``arrays``; an empty array remains distinguishable from absence.
    """
    fields: Dict[str, Any] = field(default_factory=dict)
    arrays: Dict[int, np.ndarray] = field(default_factory=dict)
    attitude: Optional[AttitudeData] = None
    diagnostics: Tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.fields = dict(self.fields)
        self.arrays = {sid: np.array(values, copy=True) for sid, values in self.arrays.items()}

    def value(self, key: str):
        if key == "timestamp" and "timestamp_ns" in self.fields:
            return self.fields["timestamp_ns"] / 1e9
        return self.fields.get(key)

    def has_field(self, key: str) -> bool:
        return key in self.fields or (key == "timestamp" and "timestamp_ns" in self.fields)


@dataclass(frozen=True)
class Record:
    record_id: int
    offset: int
    total_size: int
    header_size: int
    raw: bytes
    checksum_valid: Optional[bool] = None
    data: Optional[RecordData] = None
    backend: Optional[BackendInfo] = None
