"""
Tests for gsf-timecheck functionality.
"""

import sys

import pytest

from tests.gsf_files import attitude, ping
from tools import gsf_timecheck


def run_timecheck(monkeypatch, capsys, path):
    """
    Run gsf_timecheck.main() on a file and return what it printed.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        capsys: The pytest capsys fixture.
        path: The GSF file to check.

    Returns:
        The captured standard output, as a string.
    """
    monkeypatch.setattr(sys, "argv", ["gsf_timecheck.py", str(path)])
    gsf_timecheck.main()
    return capsys.readouterr().out


class TestTimecheck:
    """End-to-end tests of gsf_timecheck on synthetic GSF files."""

    def test_in_order_file_reports_no_problems(self, monkeypatch, capsys, compliant_gsf):
        """Test that a file with increasing times reports totals, spans, and no problems."""
        out = run_timecheck(monkeypatch, capsys, compliant_gsf)

        assert "[PING]" not in out
        assert "[ATT ]" not in out
        assert "SWATH_BATHYMETRY: total=3, out‑of‑order=0" in out
        assert "span: 1700000001.000000 → 1700000003.000000" in out
        assert "ATTITUDE:          total=2,   out‑of‑order=0" in out
        assert "span: 1700000000.000000 → 1700000003.000000" in out

    def test_ping_that_goes_back_in_time_is_reported(self, monkeypatch, capsys, make_gsf):
        """Test that a ping earlier than the one before it is reported and counted."""
        path = make_gsf("pings.gsf", [ping(10.0), ping(12.0), ping(11.0), ping(13.0)])

        out = run_timecheck(monkeypatch, capsys, path)

        assert "[PING] out‑of‑order: 11.000000 < 12.000000" in out
        assert "SWATH_BATHYMETRY: total=4, out‑of‑order=1" in out

    def test_equal_ping_times_are_not_out_of_order(self, monkeypatch, capsys, make_gsf):
        """Test that two pings with the same time are accepted, as before."""
        path = make_gsf("pings.gsf", [ping(10.0), ping(10.0)])

        out = run_timecheck(monkeypatch, capsys, path)

        assert "SWATH_BATHYMETRY: total=2, out‑of‑order=0" in out

    def test_attitude_record_starting_before_previous_end_is_reported(
        self, monkeypatch, capsys, make_gsf
    ):
        """Test that an attitude record starting before the previous one ends is reported."""
        path = make_gsf(
            "attitude.gsf",
            [attitude([1.0, 2.0]), attitude([1.5, 3.0]), attitude([4.0])],
        )

        out = run_timecheck(monkeypatch, capsys, path)

        assert "[ATT ] out‑of‑order: first=1.500000 < prev_last=2.000000" in out
        assert "ATTITUDE:          total=3,   out‑of‑order=1" in out
        assert "span: 1.000000 → 4.000000" in out

    def test_reports_appear_in_file_order(self, monkeypatch, capsys, make_gsf):
        """Test that ping and attitude reports are interleaved in the order the records occur."""
        path = make_gsf(
            "mixed.gsf",
            [attitude([5.0]), ping(10.0), attitude([4.0]), ping(9.0)],
        )

        out = run_timecheck(monkeypatch, capsys, path)

        assert out.index("[ATT ]") < out.index("[PING]")

    def test_missing_file_exits_with_error(self, monkeypatch, capsys, tmp_path):
        """Test that a missing file prints an error and exits with status 1."""
        monkeypatch.setattr(sys, "argv", ["gsf_timecheck.py", str(tmp_path / "absent.gsf")])

        with pytest.raises(SystemExit) as excinfo:
            gsf_timecheck.main()

        assert excinfo.value.code == 1
        assert "not found" in capsys.readouterr().err
