"""
Tests for gsf-info functionality.
"""

import sys

import pytest

from tests.gsf_files import attitude, ping
from tools import gsf_info


def run_info(monkeypatch, capsys, path, *options):
    """
    Run gsf_info.main() on a file with the given options and return what it printed.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        capsys: The pytest capsys fixture.
        path: The GSF file to inspect.
        *options: Command-line options, such as "--depths".

    Returns:
        The captured standard output, as a string.
    """
    monkeypatch.setattr(sys, "argv", ["gsf_info.py", str(path), *options])
    gsf_info.main()
    return capsys.readouterr().out


class TestSummaryAndList:
    """Tests for the record summary and listing, which come from the file's index."""

    def test_default_prints_record_counts(self, monkeypatch, capsys, compliant_gsf):
        """Test that with no options the tool prints a count of each record type."""
        out = run_info(monkeypatch, capsys, compliant_gsf)

        assert "Datagram Summary:" in out
        assert f"{'HEADER':30} 1" in out
        assert f"{'SWATH_BATHYMETRY':30} 3" in out
        assert f"{'ATTITUDE':30} 2" in out

    def test_list_prints_records_in_file_order(self, monkeypatch, capsys, compliant_gsf):
        """Test that --list names every record, in the order they occur."""
        out = run_info(monkeypatch, capsys, compliant_gsf, "--list")

        assert out.split() == [
            "HEADER",
            "ATTITUDE",
            "SWATH_BATHYMETRY",
            "SWATH_BATHYMETRY",
            "ATTITUDE",
            "SWATH_BATHYMETRY",
        ]


class TestPingOptions:
    """Tests for the options that decode swath bathymetry pings."""

    def test_positions(self, monkeypatch, capsys, compliant_gsf):
        """Test that --positions prints each ping's time and position."""
        out = run_info(monkeypatch, capsys, compliant_gsf, "--positions")

        assert out.splitlines()[0] == "Time: 1700000001.000, Lon: -70.7500000, Lat: 43.0700000"
        assert out.count("Time: ") == 3

    def test_depths(self, monkeypatch, capsys, compliant_gsf):
        """Test that --depths prints each ping's depth array."""
        out = run_info(monkeypatch, capsys, compliant_gsf, "--depths")

        assert out.splitlines()[0] == "Depths (3): [100.   101.5   99.25]"

    def test_depth_stats_and_beam_flags(self, monkeypatch, capsys, compliant_gsf):
        """Test that --depthStats summarizes depths and counts flagged beams."""
        out = run_info(monkeypatch, capsys, compliant_gsf, "--depthStats")

        assert "Depth Stats – Min: 99.25, Max: 101.50, Mean: 100.25" in out
        assert "Beam Flags – Total: 3, Good: 2, Bad: 1" in out
        assert "Valid pings with depth: 3" in out
        assert "Empty depth pings:      0" in out

    def test_ping_without_depths_counts_as_empty(self, monkeypatch, capsys, make_gsf):
        """Test that a ping with no depth array is counted as empty and its arrays are listed."""
        path = make_gsf("no_depth.gsf", [ping(1.0, beams={"AcrossTrack_m": [-1.0, 1.0]})])

        out = run_info(monkeypatch, capsys, path, "--depthStats")

        assert "Depth Stats – Empty depth array" in out
        assert f"  {'AcrossTrack_m':30} len=2" in out
        assert f"  {'AlongTrack_m':30} not present" in out
        assert "Empty depth pings:      1" in out

    def test_ping_header(self, monkeypatch, capsys, make_gsf):
        """Test that --pingHeader prints the decoded header fields and the subrecord IDs."""
        path = make_gsf(
            "header.gsf",
            [ping(1700000001.5, Heading_deg=123.45, Height_m=12.345, PingFlags=1)],
        )

        out = run_info(monkeypatch, capsys, path, "--pingHeader")

        assert "Timestamp            : 2023-11-14T22:13:21.500000Z" in out
        assert "Latitude  (°)        : 43.0700000" in out
        assert "Num Beams            : 3" in out
        assert "Usable               : False" in out
        assert "Heading         (°)  : 123.45" in out
        # Height is stored in millimeters, so it keeps three decimal places.
        assert "Height          (m)  : 12.345" in out
        assert "Subrecords           : 6" in out
        assert "Subrecord IDs        : 100(" in out

    def test_ping_header_verbose_prints_decoded_arrays(self, monkeypatch, capsys, compliant_gsf):
        """Test that --pingHeaderVerbose prints each decoded array under its gsfu label."""
        out = run_info(monkeypatch, capsys, compliant_gsf, "--pingHeaderVerbose")

        assert "-- Decoded Subrecord Contents --" in out
        assert f"  {'Depth_m':30}: [100.   101.5   99.25]" in out
        assert f"  {'BeamFlags':30}: [0 0 1]" in out
        # The scale factors subrecord has no decoded array to print.
        assert "  100 UNKNOWN or not decoded by gsfu" in out


class TestAttitude:
    """Tests for printing attitude records."""

    def test_attitude_prints_every_measurement(self, monkeypatch, capsys, make_gsf):
        """Test that --attitude prints one line per attitude measurement."""
        path = make_gsf("attitude.gsf", [attitude([10.0, 10.25]), attitude([10.5])])

        out = run_info(monkeypatch, capsys, path, "--attitude")

        assert out.splitlines() == [
            "Time: 10.000, Roll: -1.25, Pitch: 0.50, Heave: 0.10",
            "Time: 10.250, Roll: -1.25, Pitch: 0.50, Heave: 0.10",
            "Time: 10.500, Roll: -1.25, Pitch: 0.50, Heave: 0.10",
        ]


def test_missing_file_exits_with_error(monkeypatch, capsys, tmp_path):
    """Test that a missing file prints an error and exits with status 1."""
    monkeypatch.setattr(sys, "argv", ["gsf_info.py", str(tmp_path / "absent.gsf")])

    with pytest.raises(SystemExit) as excinfo:
        gsf_info.main()

    assert excinfo.value.code == 1
    assert "not found" in capsys.readouterr().err
