"""
Tests for the synthetic GSF file helpers in tests/gsf_files.py.
"""

import pytest
from GSFU import gsf

from tests.gsf_files import attitude, insert_subrecord, ping, remove_subrecord, write_gsf
from tools.utils import scan_subrecord_ids


def read_pings(path):
    """Return every decoded swath bathymetry ping in a GSF file, in file order."""
    return [record for _, _, record in gsf(str(path)).iter_records("SWATH_BATHYMETRY_PING")]


def ping_subrecord_ids(path, ping_number):
    """Return the subrecord IDs found in one ping of a GSF file, in file order."""
    reader = gsf(str(path))
    reader.index_file()
    reader.closeFile()
    row = reader.Index[reader.Index["RecordID"] == 2].iloc[ping_number]
    with open(path, "rb") as f:
        f.seek(int(row["ByteOffset"]))
        raw = f.read(int(row["TotalBytes"]))
    return scan_subrecord_ids(raw, 56)


class TestWriteGsf:
    """Tests for building GSF files from ping and attitude descriptions."""

    def test_compliant_file_reads_back(self, compliant_gsf):
        """Test that the compliant fixture holds three full pings and two attitude records."""
        reader = gsf(compliant_gsf)
        reader.index_file()
        counts = reader.Index["RecordID"].value_counts().to_dict()
        assert counts == {1: 1, 2: 3, 12: 2}

        pings = read_pings(compliant_gsf)
        assert [p["NumberBeams"] for p in pings] == [3, 3, 3]
        assert list(pings[0]["Beams"]["Depth_m"]) == pytest.approx([100.0, 101.5, 99.25])

    def test_ping_without_given_array_leaves_it_absent(self, make_gsf):
        """Test that an array left out of a ping description is absent from the file."""
        path = make_gsf("no_along_track.gsf", [ping(1.0, beams={"Depth_m": [10.0, 11.0]})])

        beams = read_pings(path)[0]["Beams"]

        assert list(beams["Depth_m"]) == pytest.approx([10.0, 11.0])
        assert beams["AlongTrack_m"] is None

    def test_attitude_times_round_trip(self, tmp_path):
        """Test that attitude measurement times are written as given."""
        path = write_gsf(tmp_path / "attitude.gsf", [attitude([5.0, 5.25, 5.5])])

        times = gsf(path).read_attitude()["Time"]

        seconds = times.astype("datetime64[ns]").astype("int64") / 1e9
        assert list(seconds) == pytest.approx([5.0, 5.25, 5.5])


class TestRemoveSubrecord:
    """Tests for removing a subrecord from a ping of an existing file."""

    def test_removes_scale_factors_from_one_ping(self, compliant_gsf):
        """Test that only the chosen ping loses the subrecord, and the file stays readable."""
        assert 100 in ping_subrecord_ids(compliant_gsf, 1)

        remove_subrecord(compliant_gsf, 1, 100)

        assert 100 in ping_subrecord_ids(compliant_gsf, 0)
        assert 100 not in ping_subrecord_ids(compliant_gsf, 1)
        assert 100 in ping_subrecord_ids(compliant_gsf, 2)
        # The second ping still decodes, using the scale factors carried
        # forward from the first ping, as GSF allows.
        pings = read_pings(compliant_gsf)
        assert list(pings[1]["Beams"]["Depth_m"]) == pytest.approx([100.0, 101.5, 99.25])

    def test_missing_subrecord_raises(self, compliant_gsf):
        """Test that asking to remove a subrecord the ping lacks raises ValueError."""
        with pytest.raises(ValueError, match="has no subrecord 14"):
            remove_subrecord(compliant_gsf, 0, 14)

    def test_missing_ping_raises(self, compliant_gsf):
        """Test that asking for a ping beyond the last one raises ValueError."""
        with pytest.raises(ValueError, match="only 3 pings"):
            remove_subrecord(compliant_gsf, 3, 100)


class TestInsertSubrecord:
    """Tests for inserting a subrecord into a ping of an existing file."""

    def test_appends_after_the_other_subrecords(self, compliant_gsf):
        """Test that by default the subrecord is added at the end of the chosen ping only."""
        before = ping_subrecord_ids(compliant_gsf, 1)

        insert_subrecord(compliant_gsf, 1, 154, b"abcd")

        assert ping_subrecord_ids(compliant_gsf, 1) == before + [154]
        assert ping_subrecord_ids(compliant_gsf, 0) == before
        assert len(read_pings(compliant_gsf)) == 3

    def test_inserts_before_the_other_subrecords(self, compliant_gsf):
        """Test that first=True puts the subrecord ahead of the scale factors."""
        insert_subrecord(compliant_gsf, 0, 14, first=True)

        assert ping_subrecord_ids(compliant_gsf, 0)[:2] == [14, 100]

    def test_unaligned_payload_raises(self, compliant_gsf):
        """Test that a payload leaving the record off its four-byte boundary is refused."""
        with pytest.raises(ValueError, match="four-byte boundary"):
            insert_subrecord(compliant_gsf, 0, 154, b"abc")
