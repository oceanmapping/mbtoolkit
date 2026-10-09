"""
Tests for gsf-verify functionality.
"""
import pytest
import json
import os
import tempfile
from pathlib import Path

from GSFU.gsfu import new_swath_bathymetry_ping

from tests.gsf_files import insert_subrecord, ping, remove_subrecord
from tools.gsf_verify import gsfu_field, load_profile, verify

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"


class TestLoadProfile:
    """Tests for load_profile function."""

    def test_load_profile_basic(self):
        """Test loading a basic profile JSON."""
        profile_data = {
            "profile": {
                "name": "Test Profile",
                "gsf_version": "03.11",
                "required_records": [
                    {
                        "record_type": "HeaderRecord",
                        "record_id": 1
                    }
                ]
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(profile_data, f)
            temp_path = f.name
        
        try:
            result = load_profile(temp_path)
            assert result["name"] == "Test Profile"
            assert result["gsf_version"] == "03.11"
            assert len(result["required_records"]) == 1
        finally:
            os.unlink(temp_path)

    def test_load_profile_missing_file(self):
        """Test that loading a non-existent file raises an error."""
        with pytest.raises(FileNotFoundError):
            load_profile("/nonexistent/path/profile.json")

    def test_load_profile_invalid_json(self):
        """Test that invalid JSON raises an error."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json {")
            temp_path = f.name
        
        try:
            with pytest.raises(json.JSONDecodeError):
                load_profile(temp_path)
        finally:
            os.unlink(temp_path)


class TestGsfuField:
    """Tests for mapping profile field names to gsfu record keys."""

    def test_every_profile_header_field_maps_to_a_gsfu_ping_field(self):
        """Test that each ping header field in the bundled profiles has a gsfu key."""
        ping_fields = set(new_swath_bathymetry_ping())
        for profile_path in sorted(PROFILES_DIR.glob("*.json")):
            for record in load_profile(str(profile_path)).get("required_records", []):
                for key in record.get("required_header_fields", []):
                    field = gsfu_field(key)
                    assert field is None or field in ping_fields, (profile_path.name, key)

    def test_ping_header_fields(self):
        """Test the mapping of a few ping header fields."""
        assert gsfu_field("timestamp") == "PingTime"
        assert gsfu_field("num_beams") == "NumberBeams"
        assert gsfu_field("centre_beam") == "CenterBeam"
        assert gsfu_field("separation") == "SEP_m"

    def test_reserved_and_spare_have_no_gsfu_field(self):
        """Test that the valueless reserved and spare fields map to None."""
        assert gsfu_field("reserved") is None
        assert gsfu_field("spare") is None

    def test_other_names_pass_through(self):
        """Test that a name that is not a ping header field is returned unchanged."""
        assert gsfu_field("Comment") == "Comment"
        assert gsfu_field("") == ""


class TestVerifyReport:
    """Tests for the validation report gsf_verify prints."""

    def test_report_names_the_profile_file(self, capsys, compliant_gsf, tmp_path, sample_profile):
        """Test that the report header names the profile file rather than printing its contents."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(sample_profile))

        verify(str(profile_path), compliant_gsf)

        out = capsys.readouterr().out
        assert f"against profile '{profile_path}':" in out
        assert "Test Profile" not in out


def ping_rule(**rule):
    """
    Return a profile requiring a header record and swath bathymetry pings with the given rules.

    Args:
        **rule: Rules for the ping record, such as required_subrecords=[...].

    Returns:
        A profile dictionary, in the same form as the files in profiles/.
    """
    return {
        "profile": {
            "name": "Ping Rules",
            "required_records": [
                {"record_type": "HeaderRecord", "record_id": 1},
                {"record_type": "SwathBathymetryPing", "record_id": 2, **rule},
            ],
        }
    }


def violations(capsys, tmp_path, profile, gsf_path):
    """
    Run verify() and return the violations it reports.

    Args:
        capsys: The pytest capsys fixture.
        tmp_path: A temporary directory for the profile file.
        profile: The profile dictionary to check against.
        gsf_path: The GSF file to check.

    Returns:
        The reported violation lines, with their leading "   - " removed, or
        an empty list if every check passed.
    """
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    verify(str(profile_path), gsf_path)
    out = capsys.readouterr().out
    if "All checks passed" in out:
        return []
    return [line[len("   - "):] for line in out.splitlines() if line.startswith("   - ")]


def subrecord(name, subrecord_id):
    """Return a required_subrecords entry."""
    return {"subrecord_name": name, "subrecord_id": subrecord_id}


class TestVerifySubrecords:
    """Tests for the required subrecord checks."""

    def test_compliant_file_passes(self, capsys, tmp_path, compliant_gsf):
        """Test that a file with every required subrecord passes."""
        profile = ping_rule(required_subrecords=[
            subrecord("ScaleFactors", 100), subrecord("DepthArray", 1),
            subrecord("AcrossTrackArray", 2), subrecord("AlongTrackArray", 3),
            subrecord("BeamFlagsArray", 16),
        ])

        assert violations(capsys, tmp_path, profile, compliant_gsf) == []

    def test_missing_beam_array_is_reported(self, capsys, tmp_path, make_gsf):
        """Test that a ping without a required beam array is reported, once per ping."""
        path = make_gsf("no_along.gsf", [ping(1.0), ping(2.0, beams={"Depth_m": [1.0, 2.0]})])
        profile = ping_rule(required_subrecords=[subrecord("AlongTrackArray", 3)])

        found = violations(capsys, tmp_path, profile, path)

        assert len(found) == 1
        assert found[0].startswith("Rec 2 @offset ")
        assert found[0].endswith(": missing subrecord 'AlongTrackArray' (3)")

    def test_empty_beam_array_counts_as_present(self, capsys, tmp_path, make_gsf):
        """Test that a zero-length array subrecord inside the ping satisfies the requirement."""
        path = make_gsf("empty_along.gsf", [ping(1.0)])
        remove_subrecord(path, 0, 3)
        insert_subrecord(path, 0, 3, first=True)
        profile = ping_rule(required_subrecords=[subrecord("AlongTrackArray", 3)])

        assert violations(capsys, tmp_path, profile, path) == []

    def test_empty_beam_array_ending_the_ping_is_missing(self, capsys, tmp_path, make_gsf):
        """Test that a zero-length subrecord ending the ping is missing, as gsflib sees it."""
        # The reference gsflib library stops reading a ping's subrecords
        # before a zero-length one at its end, so the array is absent.
        path = make_gsf("trailing_along.gsf", [ping(1.0)])
        remove_subrecord(path, 0, 3)
        insert_subrecord(path, 0, 3)
        profile = ping_rule(required_subrecords=[subrecord("AlongTrackArray", 3)])

        found = violations(capsys, tmp_path, profile, path)

        assert len(found) == 1
        assert found[0].endswith(": missing subrecord 'AlongTrackArray' (3)")

    def test_missing_scale_factors_are_reported(self, capsys, tmp_path, compliant_gsf):
        """Test that the scale factors requirement is checked in each ping's raw subrecords."""
        remove_subrecord(compliant_gsf, 1, 100)
        profile = ping_rule(required_subrecords=[subrecord("ScaleFactors", 100)])

        found = violations(capsys, tmp_path, profile, compliant_gsf)

        assert len(found) == 1
        assert found[0].endswith(": missing subrecord 'ScaleFactors' (100)")


class TestVerifyFieldsAndRecords:
    """Tests for the header field, constraint, and record type checks."""

    def test_header_fields_are_found(self, capsys, tmp_path, compliant_gsf):
        """Test that every ping header field the multibeam profile requires is found."""
        multibeam = load_profile(str(PROFILES_DIR / "multibeam.json"))
        fields = next(
            r["required_header_fields"] for r in multibeam["required_records"]
            if r["record_id"] == 2
        )
        profile = ping_rule(required_header_fields=fields)

        assert violations(capsys, tmp_path, profile, compliant_gsf) == []

    def test_unknown_header_field_is_reported(self, capsys, tmp_path, compliant_gsf):
        """Test that a header field name with no matching field is reported in every ping."""
        profile = ping_rule(required_header_fields=["tide_corecter"])

        found = violations(capsys, tmp_path, profile, compliant_gsf)

        assert found == ["Record 2: missing required header field 'tide_corecter'"] * 3

    def test_constraint_mismatch_is_reported(self, capsys, tmp_path, compliant_gsf):
        """Test that a field value different from a constraint's is reported with both values."""
        profile = ping_rule(constraints={"num_beams": 1, "centre_beam": 1})

        found = violations(capsys, tmp_path, profile, compliant_gsf)

        assert found == ["Record 2: constraint 'num_beams' expected 1 but got 3"] * 3

    def test_missing_record_type_is_reported(self, capsys, tmp_path, compliant_gsf):
        """Test that a required record type absent from the file is reported."""
        profile = ping_rule()
        profile["profile"]["required_records"].append(
            {"record_type": "SwathBathySummary", "record_id": 9}
        )

        found = violations(capsys, tmp_path, profile, compliant_gsf)

        assert found == ["Missing required record type SwathBathySummary (ID=9)"]
