"""Tests for sensor-specific subrecord decoding."""
import struct

from tools.sensor_specific import (
    decode_sensor_subrecord,
    sensor_subrecord_name,
)


def test_sensor_subrecord_name_known_and_vendor():
    assert sensor_subrecord_name(156) == "KMALL_SPECIFIC"
    assert sensor_subrecord_name(200) == "VENDOR_200"


def test_decode_kmall_from_em304_fixture():
    # Minimal KMALL header bytes from a real EM304 ping (truncated payload).
    payload = bytes.fromhex(
        "0001033c0130"
        "0000000000000000"
        "000c67a70200"
        "0200000100000000"
        "0000000000000000"
        "00009800001db1"
    )
    # Pad to allow sector/rx parsing without truncation
    payload += b"\x00" * 600

    result = decode_sensor_subrecord(156, payload)
    fields = dict(result.fields)
    assert result.decoder.startswith("KMALL")
    assert fields["echoSounderID"] == "304"
    assert fields["dgmType"].startswith("1")


def test_decode_generic_vendor():
    result = decode_sensor_subrecord(185, b"\x00\x02")
    assert result.decoder == "generic"
    assert any("vendor extension" in w for w in result.warnings)


def test_decode_em3_minimal():
    payload = struct.pack(">HHHHhhHhbI", 3000, 42, 100, 1500, 1234, 400, 8000, 0, 0, 0)
    result = decode_sensor_subrecord(118, payload)
    fields = dict(result.fields)
    assert "EM3" in result.decoder
    assert fields["model_number"] == "3000"
    assert fields["ping_number"] == "42"


def test_decode_reson8100_reference_field_widths():
    # Latency (u16), ping/sonar IDs (u32), model/frequency/sound speed (u16).
    payload = struct.pack(">HIIHHH", 1, 42, 123, 8101, 200, 15000)
    result = decode_sensor_subrecord(122, payload)
    assert dict(result.fields) == {
        "latency_ms": "1",
        "ping_number": "42",
        "sonar_id": "123",
        "sonar_model": "8101",
        "frequency_kHz": "200",
        "surface_velocity_mps": "1500.0",
    }
    assert result.bytes_consumed == len(payload)
    assert result.warnings == []
