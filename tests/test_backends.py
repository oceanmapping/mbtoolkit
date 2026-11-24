"""Backend contract tests use independent wire fixtures, not parser writers."""
import importlib.util
import builtins
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
import pytest

import readers
from readers import (
    BackendError, BackendInfo, BackendUnavailableError, DecodeRequest, Decoder,
    FormatError, RecordData, UnsupportedFeatureError, open_reader,
)
from readers.stream import iter_frames

BACKENDS = ["pygsf", pytest.param("gsfu", marks=pytest.mark.skipif(
    importlib.util.find_spec("GSFU") is None, reason="optional gsfu backend not installed")),
    pytest.param("gsflib", marks=pytest.mark.skipif(
        "gsflib" not in readers._plugins(), reason="optional reference C plugin not installed"))]


def record(rid, payload, checksum=False):
    payload += bytes((-len(payload)) % 4)
    header = struct.pack(">II", len(payload), rid | (0x80000000 if checksum else 0))
    if checksum:
        header += struct.pack(">I", sum(payload) & 0xFFFFFFFF)
    return header + payload


def subrecord(sid, payload):
    return bytes([sid]) + len(payload).to_bytes(3, "big") + payload


@pytest.fixture
def make_file(tmp_path):
    def build(checksum=False, unknown=False):
        header = bytearray(56)
        struct.pack_into(">IIii", header, 0, 1_700_000_000, 123_456_789, -630_000_000, 450_000_000)
        struct.pack_into(">hhHh", header, 16, 2, 1, 0, -1)
        struct.pack_into(">iii", header, 42, 1234, -2345, 3456)
        scale_specs = [(1, 0x20, 100), (2, 0x40, 100), (3, 0x20, 100),
                       (16, 0x10, 1), (19, 0x20, 100), (20, 0x20, 100)]
        factors = struct.pack(">I", len(scale_specs)) + b"".join(
            struct.pack(">Iii", sid << 24 | flag << 16, multiplier, 0)
            for sid, flag, multiplier in scale_specs
        )
        arrays = b"".join(subrecord(sid, payload) for sid, payload in [
            (1, struct.pack(">HH", 100, 200)), (2, struct.pack(">ii", -300, 400)),
            (3, struct.pack(">hh", 10, 20)), (16, b"\x00\x01"),
            (19, struct.pack(">HH", 30, 40)), (20, struct.pack(">HH", 50, 60)),
        ])
        first = record(2, bytes(header) + subrecord(100, factors) + arrays, checksum)
        struct.pack_into(">I", header, 0, 1_700_000_001)
        second = record(2, bytes(header) + arrays, checksum)
        attitude = struct.pack(">IIH", 1_700_000_002, 987_654_321, 2)
        attitude += struct.pack(">HhhhH", 5, -123, -345, -12, 35000)
        attitude += struct.pack(">HhhhH", 500, 234, 456, 34, 1234)
        raw = record(1, b"GSF-v03.11\x00\x00", checksum) + first
        if unknown:
            raw += record(177, b"opaque unknown record", checksum)
        raw += second + record(12, attitude, checksum)
        path = tmp_path / ("checked.gsf" if checksum else "sample.gsf")
        path.write_bytes(raw)
        return path
    return build


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("checksum", [False, True])
def test_normalized_values_inheritance_and_owned_arrays(make_file, backend, checksum):
    source = make_file(checksum=checksum)
    with open_reader(source, backend=backend) as reader:
        records = list(reader.records(DecodeRequest(frozenset({1, 2, 12}), True)))
        assert reader.backend.name == backend
        assert reader.version == "GSF-v03.11"
    assert b"".join(r.raw for r in records) == source.read_bytes()
    assert all(r.checksum_valid == (True if checksum else None) for r in records)
    assert all(r.backend.name == backend for r in records)
    first, second = [r.data for r in records if r.record_id == 2]
    for ping in (first, second):
        assert ping.fields["height"] == pytest.approx(1.234)
        assert ping.fields["separation"] == pytest.approx(-2.345)
        assert ping.fields["gps_tide_corrector"] == pytest.approx(3.456)
        assert ping.fields["reserved"] == -1
        np.testing.assert_array_equal(ping.arrays[1], [1, 2])
        np.testing.assert_array_equal(ping.arrays[2], [-3, 4])
        np.testing.assert_array_equal(ping.arrays[16], [0, 1])
        assert ping.arrays[16].dtype.kind in "ui"
        np.testing.assert_allclose(ping.arrays[19], [.3, .4])
        np.testing.assert_allclose(ping.arrays[20], [.5, .6])
    assert first.fields["timestamp_ns"] == 1_700_000_000_123_456_789
    assert second.fields["timestamp_ns"] == 1_700_000_001_123_456_789
    second.arrays[1][0] = 999
    assert first.arrays[1][0] == 1
    samples = records[-1].data.attitude
    np.testing.assert_array_equal(samples.timestamp_ns,
                                  [1_700_000_002_992_654_321, 1_700_000_003_487_654_321])
    np.testing.assert_allclose(samples.heading, [350, 12.34])


@pytest.mark.parametrize("backend", BACKENDS)
def test_metadata_preserves_unknown_records_and_releases_handles(make_file, backend):
    source = make_file(unknown=True)
    with open_reader(source, backend=backend) as reader:
        records = list(reader.records())
        assert [r.record_id for r in records] == [1, 2, 177, 2, 12]
        assert all(r.data is None for r in records)
        assert b"opaque unknown record" in records[2].raw
        assert b"".join(r.raw for r in records) == source.read_bytes()
        iterator = reader.records(DecodeRequest(frozenset({2}), True))
        next(iterator)
    # A second pass starts fresh, and early termination closes the first pass.
    with reader:
        assert len(list(reader.records())) == 5


@pytest.mark.parametrize("backend", BACKENDS)
def test_attitude_time_offsets_preserve_nanoseconds(make_file, backend):
    source = make_file()
    offsets = [1, 7, 29, 57, 1001, 1056, 65001, 65535]
    payload = struct.pack(">IIH", 1_700_000_000, 987_654_321, len(offsets))
    payload += b"".join(struct.pack(">HhhhH", offset, -123, 234, -56, 35000) for offset in offsets)
    source.write_bytes(record(1, b"GSF-v03.11\0\0") + record(12, payload))
    with open_reader(source, backend) as reader:
        attitude = [r.data.attitude for r in reader.records(DecodeRequest(frozenset({12}))) if r.data][0]
    np.testing.assert_array_equal(attitude.timestamp_ns,
                                  [1_700_000_000_987_654_321 + offset * 1_000_000 for offset in offsets])
    np.testing.assert_allclose(attitude.pitch, -1.23)
    np.testing.assert_allclose(attitude.roll, 2.34)
    np.testing.assert_allclose(attitude.heave, -.56)
    np.testing.assert_allclose(attitude.heading, 350)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("checksum", [False, True])
def test_semantic_decoding_preserves_unknown_records(make_file, backend, checksum):
    source = make_file(checksum=checksum, unknown=True)
    with open_reader(source, backend) as reader:
        records = list(reader.records(DecodeRequest(frozenset({1, 2, 12}), True)))
    assert [r.record_id for r in records] == [1, 2, 177, 2, 12]
    assert records[2].data is None
    assert b"".join(r.raw for r in records) == source.read_bytes()
    np.testing.assert_array_equal(records[3].data.arrays[1], [1, 2])


def test_selection_precedence_and_no_fallback(make_file, monkeypatch):
    source = make_file()
    monkeypatch.setenv("MBTOOLKIT_GSF_BACKEND", "does-not-exist")
    with pytest.raises(BackendUnavailableError):
        open_reader(source)
    with open_reader(source, backend="pygsf") as reader:
        assert reader.backend.name == "pygsf"
    monkeypatch.delenv("MBTOOLKIT_GSF_BACKEND")
    assert open_reader(source).backend.name == "pygsf"


def test_third_party_decoder_plugin_is_lazy_and_uses_same_contract(make_file, monkeypatch):
    calls = []

    class Plugin(Decoder):
        info = BackendInfo("test-native", "1", frozenset({2}))

        def decode(self, frame, request):
            return RecordData({"timestamp_ns": 123})

        def close(self):
            calls.append("closed")

    class Entry:
        def load(self):
            calls.append("loaded")
            return Plugin

    monkeypatch.setattr(readers, "_plugins", lambda: {"test-native": Entry()})
    assert readers.available_backends()["test-native"] == "installed plugin"
    assert calls == []
    with open_reader(make_file(), backend="test-native") as reader:
        decoded = [r.data for r in reader.records(DecodeRequest(frozenset({2}))) if r.data]
        assert [data.fields["timestamp_ns"] for data in decoded] == [123, 123]
    assert calls[0] == "loaded" and "closed" in calls


def test_unsupported_features_and_truncated_input_are_explicit(make_file, tmp_path):
    with open_reader(make_file(), backend="pygsf") as reader:
        with pytest.raises(UnsupportedFeatureError, match="record types"):
            reader.records(DecodeRequest(frozenset({7})))
    path = tmp_path / "truncated.gsf"
    path.write_bytes(record(1, b"GSF-v03.11\x00\x00") + b"\x00\x00")
    with pytest.raises(FormatError, match="Truncated"):
        list(iter_frames(path))
    path.write_bytes(struct.pack(">II", 0xFFFFFFFF, 2))
    with pytest.raises(FormatError, match="Truncated"):
        list(iter_frames(path))


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("tool", ["gsf_info", "gsf_verify", "gsf_repair", "gsf_timecheck"])
def test_all_tools_select_backend(make_file, tmp_path, tool, backend):
    source = make_file(checksum=True)
    root = Path(__file__).resolve().parents[1]
    args = [sys.executable, str(root / "tools" / (tool + ".py"))]
    if tool in {"gsf_verify", "gsf_repair"}:
        profile = tmp_path / "profile.json"
        profile.write_text(json.dumps({"profile": {"required_records": [{
            "record_id": 2, "required_header_fields": ["timestamp", "height"],
            "required_subrecords": [{"subrecord_id": 100, "subrecord_name": "ScaleFactors"}],
        }]}}))
        args += [str(profile)]
    args += [str(source), "--backend", backend]
    if tool == "gsf_info":
        args += ["--depthStats", "--positions", "--attitude"]
    if tool == "gsf_repair":
        output = tmp_path / "repaired.gsf"
        args += ["--out", str(output)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    if tool == "gsf_repair":
        repaired = list(iter_frames(output))
        assert all(frame.checksum_valid for frame in repaired)
        assert all(100 in [sid for sid, _ in readers.stream.scan_subrecords(frame.raw, 56)]
                   for frame in repaired if frame.record_id == 2)


@pytest.mark.parametrize("tool", ["gsf_info", "gsf_verify", "gsf_repair", "gsf_timecheck"])
def test_backend_discovery_needs_no_filename(tool):
    script = Path(__file__).resolve().parents[1] / "tools" / (tool + ".py")
    result = subprocess.run([sys.executable, str(script), "--list-backends"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "pygsf: bundled" in result.stdout
    status = "installed plugin" if "gsflib" in readers._plugins() else "not installed"
    assert "gsflib: " + status in result.stdout


def test_gsf2_support_is_explicit_and_optional_backends_use_short_ping_header(make_file):
    source = make_file()
    frames = list(iter_frames(source))
    rewritten = []
    for frame in frames:
        payload = frame.raw[frame.header_size:]
        if frame.record_id == 1:
            payload = b"GSF-v02.10\x00\x00"
        elif frame.record_id == 2:
            payload = payload[:42] + payload[56:]
        rewritten.append(record(frame.record_id, payload))
    source.write_bytes(b"".join(rewritten))
    request = DecodeRequest(frozenset({2}), True)
    with open_reader(source, backend="pygsf") as reader:
        assert reader.ping_header_size == 42
        with pytest.raises(UnsupportedFeatureError, match="2.x"):
            reader.records(request)
    for backend, installed in [("gsfu", importlib.util.find_spec("GSFU") is not None),
                               ("gsflib", "gsflib" in readers._plugins())]:
        if not installed:
            continue
        with open_reader(source, backend=backend) as reader:
            pings = [r.data for r in reader.records(request) if r.data]
            assert len(pings) == 2
            assert "height" not in pings[0].fields
            np.testing.assert_array_equal(pings[0].arrays[1], [1, 2])


def test_plugin_failure_is_reported_without_fallback(make_file, monkeypatch):
    class Broken(Decoder):
        info = BackendInfo("broken", "1", frozenset({2}))

        def decode(self, frame, request):
            raise ValueError("native decode failed")

    class Entry:
        def load(self):
            return Broken

    monkeypatch.setattr(readers, "_plugins", lambda: {"broken": Entry()})
    with open_reader(make_file(), backend="broken") as reader:
        with pytest.raises(BackendError, match="broken failed on record 2.*native decode failed"):
            list(reader.records(DecodeRequest(frozenset({2}))))
        assert len(list(reader.records())) == 4


@pytest.mark.skipif("gsflib" in readers._plugins(), reason="reference C plugin is installed")
def test_missing_reference_c_adapter_is_a_clear_cli_error(make_file):
    script = Path(__file__).resolve().parents[1] / "tools/gsf_info.py"
    result = subprocess.run(
        [sys.executable, str(script), str(make_file()), "--backend", "gsflib"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "unavailable" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
def test_reference_c_interleaved_readers_are_independent(make_file, tmp_path):
    first = make_file()
    second = tmp_path / "other.gsf"
    # Same integers, different inherited depth multiplier in the other file.
    second.write_bytes(first.read_bytes().replace(
        struct.pack(">Iii", 1 << 24 | 0x20 << 16, 100, 0),
        struct.pack(">Iii", 1 << 24 | 0x20 << 16, 200, 0)))
    request = DecodeRequest(frozenset({2}), True)
    with open_reader(first, "gsflib") as a, open_reader(second, "gsflib") as b:
        ia, ib = a.records(request), b.records(request)
        next(ia)  # raw file header
        next(ib)
        pa, pb = next(ia).data, next(ib).data
        np.testing.assert_allclose(pa.arrays[1], [1, 2])
        np.testing.assert_allclose(pb.arrays[1], [.5, 1])
        np.testing.assert_allclose(next(ia).data.arrays[1], [1, 2])
        np.testing.assert_allclose(next(ib).data.arrays[1], [.5, 1])
    # Reopening the same filename also starts an independent native handle.
    with open_reader(first, "gsflib") as a, open_reader(first, "gsflib") as b:
        assert len(list(a.records(request))) == len(list(b.records(request))) == 4
    assert not list(tmp_path.glob("*.nsf"))


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
def test_reference_c_early_exit_threads_and_repeated_passes(make_file):
    from concurrent.futures import ThreadPoolExecutor

    source = make_file()
    request = DecodeRequest(frozenset({2}), True)

    def run(_):
        with open_reader(source, "gsflib") as reader:
            iterator = reader.records(request)
            next(iterator)
            ping = next(iterator).data
            iterator.close()
            assert reader.decoder._session is None
            assert len(list(reader.records(request))) == 4
            np.testing.assert_array_equal(ping.arrays[1], [1, 2])
            return ping.fields["timestamp_ns"]

    # More passes than the library's finite handle table can hold unclosed.
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(run, range(100))) == [1_700_000_000_123_456_789] * 100


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
def test_reference_c_missing_extension_is_explicit(make_file, monkeypatch):
    original = builtins.__import__

    def without_native(name, *args, **kwargs):
        if name == "" and "_native" in (kwargs.get("fromlist") or (args[2] if len(args) > 2 else ())):
            raise ImportError("deliberately unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_native)
    with pytest.raises(BackendUnavailableError, match="compiled mbtoolkit-gsflib"):
        open_reader(make_file(), "gsflib")
    with open_reader(make_file(), "pygsf") as reader:
        assert len(list(reader.records())) == 4


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
def test_reference_c_native_error_closes_handle_without_fallback(make_file, monkeypatch):
    request = DecodeRequest(frozenset({2}), True)
    with open_reader(make_file(), "gsflib") as reader:
        native = reader.decoder._native
        original = native.read

        def fail(*args):
            raise RuntimeError("GSF error: test decode failure")

        monkeypatch.setattr(native, "read", fail)
        with pytest.raises(BackendError, match="gsflib failed on record 2.*test decode failure"):
            list(reader.records(request))
        assert reader.decoder._session is None
        monkeypatch.setattr(native, "read", original)
        assert len(list(reader.records(request))) == 4
    reader.close()


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
def test_reference_c_packed_quality_and_absent_arrays(make_file):
    source = make_file()
    frames = list(iter_frames(source))
    # Independently encoded flags: two 2-bit values, 1 and 3, in the high nibble.
    # Remove this fixture's two original alignment bytes before appending.
    payload = frames[1].raw[8:-2] + subrecord(15, b"\x70")
    header_only = frames[2].raw[8:64]
    source.write_bytes(frames[0].raw + record(2, payload) + record(2, header_only))
    with open_reader(source, "gsflib") as reader:
        pings = [r.data for r in reader.records(DecodeRequest(frozenset({2}), True)) if r.data]
    np.testing.assert_array_equal(pings[0].arrays[15], [1, 3])
    assert pings[1].arrays == {}


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
def test_reference_c_unprojected_brb_preserves_following_scalar_arrays(make_file):
    source = make_file()
    frames = list(iter_frames(source))
    payload = frames[1].raw[8:-2]
    intensity = b"\x08" + bytes(20 + 2 * 12)  # 8-bit, two beams with zero samples
    brb = b"\x15" + (len(intensity) + 4).to_bytes(3, "big") + intensity
    # Put BRB between the 80-byte scale-factor subrecord and the scalar arrays.
    ping = record(2, payload[:136] + brb + payload[136:], checksum=True)
    source.write_bytes(frames[0].raw + ping)
    with open_reader(source, "gsflib") as reader:
        records = list(reader.records(DecodeRequest(frozenset({2}), True)))
    assert records[1].raw == ping
    assert records[1].checksum_valid is True
    assert records[1].data.diagnostics == ("BRB intensity series has no API v1 projection",)
    np.testing.assert_array_equal(records[1].data.arrays[1], [1, 2])
    np.testing.assert_allclose(records[1].data.arrays[20], [.5, .6])


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
@pytest.mark.parametrize("compressed", [False, True])
def test_reference_c_all_advertised_scalar_arrays(make_file, compressed):
    source = make_file()
    frames = list(iter_frames(source))
    ids = set(range(1, 32)) - {21}
    byte_ids = {6, 7, 8, 9, 10, 17, 22, 23, 24, 25, 26}
    signed_ids = {2, 3, 5, 6, 10, 17, 24, 26}
    specs, arrays, expected = [], [], {}
    for sid in sorted(ids):
        values = [-10, 20] if sid in signed_ids else [10, 20]
        flag = 0x10 if sid in byte_ids or sid in {15, 16} else 0x20
        if sid == 15:
            data, values = b"\x70", [1, 3]
        elif sid == 16:
            data = bytes(values)
        elif compressed:
            flag |= 1
            # Compression v1, order zero, Simple-16 selector 13 (two 14-bit
            # values). Sign encoding then RLE's +1 maps [-10,20] to [20,41].
            encoded = [(-2 * value if value < 0 else 2 * value + 1) for value in values]
            data = b"\x20" + struct.pack(">I", 13 << 28 | encoded[0] | encoded[1] << 14)
        else:
            fmt = ("b" if sid in signed_ids else "B") if sid in byte_ids else (
                "h" if sid in signed_ids else "H")
            data = struct.pack(">" + fmt * 2, *values)
        specs.append(struct.pack(">Iii", sid << 24 | flag << 16, 1, 0))
        arrays.append(subrecord(sid, data))
        expected[sid] = values
    factors = subrecord(100, struct.pack(">I", len(specs)) + b"".join(specs))
    source.write_bytes(frames[0].raw + record(2, frames[1].raw[8:64] + factors + b"".join(arrays)))
    with open_reader(source, "gsflib") as reader:
        assert reader.backend.decoded_beam_arrays == ids
        ping = [r.data for r in reader.records(DecodeRequest(frozenset({2}), True)) if r.data][0]
    assert ping.arrays.keys() == ids
    for sid in ids:
        np.testing.assert_allclose(ping.arrays[sid], expected[sid], err_msg="SID {}".format(sid))
    for sid in {15, 16, 22, 23, 25}:
        assert ping.arrays[sid].dtype.kind == "u"


@pytest.mark.skipif("gsflib" not in readers._plugins(), reason="reference C plugin not installed")
@pytest.mark.parametrize("malformation", ["zero_beams", "short_array", "short_attitude", "missing_factors"])
def test_reference_c_rejects_invalid_counts_before_native_decode(make_file, malformation):
    source = make_file()
    frames = list(iter_frames(source))
    if malformation == "short_attitude":
        broken = record(12, frames[-1].raw[8:18])
        types = {12}
    else:
        payload = bytearray(frames[1].raw[8:])
        if malformation == "zero_beams":
            payload[16:18] = bytes(2)
        elif malformation == "short_array":
            payload = payload[:56] + subrecord(1, b"")
        else:
            payload = frames[2].raw[8:]
        broken = record(2, payload)
        types = {2}
    source.write_bytes(frames[0].raw + broken)
    with open_reader(source, "gsflib") as reader:
        with pytest.raises(FormatError):
            list(reader.records(DecodeRequest(frozenset(types), True)))
        assert len(list(reader.records())) == 2


def test_missing_optional_dependency_does_not_affect_pygsf(make_file, monkeypatch):
    original = builtins.__import__

    def without_gsfu(name, *args, **kwargs):
        if name == "GSFU":
            raise ImportError("deliberately unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_gsfu)
    with pytest.raises(BackendUnavailableError, match="gsfu"):
        open_reader(make_file(), backend="gsfu")
    with open_reader(make_file(), backend="pygsf") as reader:
        assert len(list(reader.records())) == 4


@pytest.mark.parametrize("backend", BACKENDS)
def test_checksum_policy_is_shared_across_backends(make_file, backend):
    source = make_file(checksum=True)
    raw = bytearray(source.read_bytes())
    raw[8] ^= 1
    source.write_bytes(raw)
    with open_reader(source, backend=backend) as reader:
        with pytest.raises(FormatError, match="checksum"):
            list(reader.records())
        with pytest.raises(FormatError, match="checksum"):
            list(reader.records(DecodeRequest(frozenset({2}), True)))
