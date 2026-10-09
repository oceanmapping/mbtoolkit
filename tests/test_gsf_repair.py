"""
Tests for gsf-repair functionality.
"""

import json
import sys

import pytest
from GSFU import gsf

from tests.gsf_files import ping, remove_subrecord
from tools import gsf_repair


def run_repair(monkeypatch, capsys, tmp_path, required_subrecords, gsf_path):
    """
    Run gsf_repair.main() with a profile requiring the given ping subrecords.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        capsys: The pytest capsys fixture.
        tmp_path: A temporary directory for the profile and output files.
        required_subrecords: The ping's required subrecords, as
            (subrecord_id, name) tuples.
        gsf_path: The GSF file to repair.

    Returns:
        A (stdout, output_path) tuple: what the tool printed, and the path
        of the file it wrote.
    """
    profile = {
        "profile": {
            "name": "Repair Test",
            "required_records": [
                {
                    "record_type": "SwathBathymetryPing",
                    "record_id": 2,
                    "required_subrecords": [
                        {"subrecord_name": name, "subrecord_id": sid}
                        for sid, name in required_subrecords
                    ],
                }
            ],
        }
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    out_path = tmp_path / "repaired.gsf"
    monkeypatch.setattr(
        sys, "argv", ["gsf_repair.py", str(profile_path), str(gsf_path), "-o", str(out_path)]
    )
    gsf_repair.main()
    return capsys.readouterr().out, out_path


class TestRepair:
    """End-to-end tests of gsf_repair on synthetic GSF files."""

    def test_compliant_file_is_copied_exactly(self, monkeypatch, capsys, tmp_path, compliant_gsf):
        """Test that a file meeting the profile is written byte for byte, with nothing to report."""
        out, out_path = run_repair(
            monkeypatch, capsys, tmp_path, [(100, "ScaleFactors"), (1, "DepthArray")], compliant_gsf
        )

        assert out_path.read_bytes() == open(compliant_gsf, "rb").read()
        assert "  Record  2: total=   3, subrecords fixed=   0" in out
        assert "  Record 12: total=   2, subrecords fixed=   0" in out
        assert "Not repaired" not in out

    def test_missing_subrecords_are_reported_not_padded(
        self, monkeypatch, capsys, tmp_path, make_gsf
    ):
        """Test that pings lacking required subrecords are counted and left unchanged."""
        # The second ping relies on scale factors carried from the first, a
        # full ping; the third carries only depths.
        path = make_gsf(
            "missing.gsf",
            [ping(1.0), ping(2.0), ping(3.0, beams={"Depth_m": [1.0, 2.0]})],
        )
        remove_subrecord(path, 1, 100)
        required = [(100, "ScaleFactors"), (3, "AlongTrackArray"), (4, "TravelTimeArray")]

        out, out_path = run_repair(monkeypatch, capsys, tmp_path, required, path)

        assert out_path.read_bytes() == open(path, "rb").read()
        assert "Not repaired, because GSF has no valid empty subrecord to add:" in out
        assert "  Record  2:    1 pings lack 'TravelTimeArray' (4)" in out
        assert "  Record  2:    1 pings lack 'AlongTrackArray' (3)" in out
        assert "  Record  2:    1 pings lack 'ScaleFactors' (100)" in out

    def test_output_reads_back_completely(self, monkeypatch, capsys, tmp_path, compliant_gsf):
        """Test that every record of the written file can be read, unlike the padded output."""
        remove_subrecord(compliant_gsf, 1, 100)

        _out, out_path = run_repair(
            monkeypatch, capsys, tmp_path, [(100, "ScaleFactors")], compliant_gsf
        )

        records = list(gsf(str(out_path)).iter_records())
        assert len(records) == 6
        assert all(notes == [] for _, _, r in records for notes in [r.get("Notes", [])])

    def test_missing_input_exits_with_error(self, monkeypatch, capsys, tmp_path):
        """Test that a missing input file prints an error and exits with status 1."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"profile": {"name": "x"}}))
        monkeypatch.setattr(
            sys,
            "argv",
            ["gsf_repair.py", str(profile_path), str(tmp_path / "absent.gsf"), "-o", "out.gsf"],
        )

        with pytest.raises(SystemExit) as excinfo:
            gsf_repair.main()

        assert excinfo.value.code == 1
        assert "not found" in capsys.readouterr().err
