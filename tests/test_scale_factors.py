"""
Tests for scale-factor pack/repair helpers used by gsf-repair.
"""
import struct
import pytest

from tools.utils import (
    default_scale_factor,
    is_unreasonable_scale_factor,
    make_scale_factor,
    pack_scale_factors,
    parse_scale_factors,
    repair_scale_factor_set,
    replace_or_insert_scale_factors,
    scan_subrecords,
)


class TestScaleFactorPackParse:
    @pytest.mark.parametrize("flag", [0x00, 0x20, 0x40, 0x41, 0x01])
    def test_reference_wire_flags_survive_repair(self, flag):
        # Literal wire layout: array ID, full compression flag, two reserved bytes.
        payload = struct.pack(">I", 1) + bytes([1, flag, 0, 0]) + struct.pack(">ii", 1000, -602)
        parsed = parse_scale_factors(payload)
        assert parsed[0]["compression_flag"] == flag
        assert parsed[0]["field_size"] == flag & 0xF0
        assert parsed[0]["field_size_name"] == {
            0x00: "DEFAULT", 0x20: "2-byte", 0x40: "4-byte"
        }[flag & 0xF0]
        repaired, changes = repair_scale_factor_set(parsed, [1])
        assert changes == []
        assert pack_scale_factors(repaired) == payload
        assert pack_scale_factors([make_scale_factor(1, 1000, -602, flag)]) == payload

    def test_roundtrip(self):
        factors = [
            make_scale_factor(1, 1000, -602),
            make_scale_factor(2, 100, 0),
        ]
        payload = pack_scale_factors(factors)
        parsed = parse_scale_factors(payload)
        assert len(parsed) == 2
        assert parsed[0]["subrecord_id"] == 1
        assert parsed[0]["multiplier"] == 1000
        assert parsed[0]["offset"] == -602
        assert parsed[1]["subrecord_id"] == 2
        assert parsed[1]["multiplier"] == 100

    def test_unreasonable_zero_multiplier(self):
        bad = make_scale_factor(1, 0, 0)
        assert is_unreasonable_scale_factor(bad) is True
        good = make_scale_factor(1, 1000, 0)
        assert is_unreasonable_scale_factor(good) is False


class TestRepairScaleFactorSet:
    def test_adds_missing_scaled_array(self):
        existing = [make_scale_factor(1, 1000, -500), make_scale_factor(2, 100, 0)]
        repaired, changes = repair_scale_factor_set(existing, needed_array_ids=[1, 2, 5])
        ids = {f["subrecord_id"] for f in repaired}
        assert 5 in ids
        assert any("added missing scale factor for id 5" in c for c in changes)
        # Preserve reasonable existing depth offset
        depth = next(f for f in repaired if f["subrecord_id"] == 1)
        assert depth["offset"] == -500
        assert depth["multiplier"] == 1000

    def test_does_not_add_intensity_scale_factor(self):
        # GSF 3.05 BRB intensity is not scaled via SCALE_FACTORS.
        existing = [make_scale_factor(1, 1000, -500), make_scale_factor(2, 100, 0)]
        repaired, changes = repair_scale_factor_set(existing, needed_array_ids=[1, 2, 21])
        ids = {f["subrecord_id"] for f in repaired}
        assert 21 not in ids
        assert not any("id 21" in c for c in changes)

    def test_replaces_unreasonable(self):
        existing = [make_scale_factor(1, 0, 0)]
        repaired, changes = repair_scale_factor_set(existing, needed_array_ids=[1])
        assert repaired[0]["multiplier"] == default_scale_factor(1)["multiplier"]
        assert any("replaced unreasonable" in c for c in changes)


class TestReplaceOrInsertScaleFactors:
    def _minimal_ping(self, subs):
        """Build a minimal SWATH-like datagram buffer for unit tests."""
        ping_hdr = b"\x00" * 56  # size of >llll5hlH3h2Hlllh
        body = bytearray()
        for sid, payload in subs:
            body.append(sid)
            body.extend(len(payload).to_bytes(3, "big"))
            body.extend(payload)
        # size word excludes the 8-byte header (size + id)
        content = ping_hdr + bytes(body)
        size_word = len(content)
        return struct.pack(">II", size_word, 2) + content, 56

    def test_insert_when_missing(self):
        raw, hdr_size = self._minimal_ping([(1, b"\x00\x01")])
        factors = [make_scale_factor(1, 1000, 0)]
        out = replace_or_insert_scale_factors(raw, hdr_size, factors)
        subs = scan_subrecords(out, hdr_size)
        assert subs[0][0] == 100
        parsed = parse_scale_factors(subs[0][1])
        assert parsed[0]["subrecord_id"] == 1
        # size word updated (excludes 8-byte header)
        assert struct.unpack(">I", out[:4])[0] == len(out) - 8

    def test_replace_existing(self):
        old_payload = pack_scale_factors([make_scale_factor(1, 1000, 0)])
        raw, hdr_size = self._minimal_ping([(100, old_payload), (2, b"\x00\x01")])
        factors = [make_scale_factor(1, 1000, 0), make_scale_factor(2, 100, 0)]
        out = replace_or_insert_scale_factors(raw, hdr_size, factors)
        subs = scan_subrecords(out, hdr_size)
        assert [s for s, _ in subs].count(100) == 1
        parsed = parse_scale_factors(next(p for s, p in subs if s == 100))
        assert {f["subrecord_id"] for f in parsed} == {1, 2}

    @pytest.mark.parametrize("replace_existing", [False, True])
    def test_preserves_brb_padding_and_following_bytes(self, replace_existing):
        # BRB payload, three padding bytes, another subrecord, and trailing slack.
        tail = b"\x15\x00\x00\x05abcde\xa1\xb2\xc3\x02\x00\x00\x02xy\xff"
        old_sf = b"\x64\x00\x00\x00" if replace_existing else b""
        content = bytes(56) + old_sf + tail
        raw = struct.pack(">II", len(content), 2) + content

        out = replace_or_insert_scale_factors(raw, 56, [make_scale_factor(2, 100, 0)])

        assert out.endswith(tail)
        assert scan_subrecords(out, 56)[1:] == [(21, b"abcde"), (2, b"xy")]
        assert struct.unpack_from(">I", out)[0] == len(out) - 8
