"""
Tests for the bundled validation profiles in profiles/.
"""

import json
from pathlib import Path

import pytest

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"
PROFILE_PATHS = sorted(PROFILES_DIR.glob("*.json"))

# Swath bathymetry ping subrecord IDs, keyed by the subrecord names the
# profiles use. The IDs are the GSF_SWATH_BATHY_SUBRECORD_* constants defined
# in gsf.h of the GSF 3.11 reference library (the comment on each line gives
# the constant's name with that prefix removed).
GSF_SUBRECORD_IDS = {
    "ScaleFactors": 100,  # SCALE_FACTORS
    "DepthArray": 1,  # DEPTH_ARRAY
    "AcrossTrackArray": 2,  # ACROSS_TRACK_ARRAY
    "AlongTrackArray": 3,  # ALONG_TRACK_ARRAY
    "TravelTimeArray": 4,  # TRAVEL_TIME_ARRAY
    "BeamAngleArray": 5,  # BEAM_ANGLE_ARRAY
    "MeanCalibratedAmplitudeArray": 6,  # MEAN_CAL_AMPLITUDE_ARRAY
    "MeanRelativeAmplitudeArray": 7,  # MEAN_REL_AMPLITUDE_ARRAY
    "EchoWidthArray": 8,  # ECHO_WIDTH_ARRAY
    "QualityFactorArray": 9,  # QUALITY_FACTOR_ARRAY
    "ReceiveHeaveArray": 10,  # RECEIVE_HEAVE_ARRAY
    "DepthErrorArray": 11,  # DEPTH_ERROR_ARRAY (obsolete)
    "AcrossTrackErrorArray": 12,  # ACROSS_TRACK_ERROR_ARRAY (obsolete)
    "AlongTrackErrorArray": 13,  # ALONG_TRACK_ERROR_ARRAY (obsolete)
    "NominalDepthArray": 14,  # NOMINAL_DEPTH_ARRAY
    "QualityFlagsArray": 15,  # QUALITY_FLAGS_ARRAY
    "BeamFlagsArray": 16,  # BEAM_FLAGS_ARRAY
    "SignalToNoiseArray": 17,  # SIGNAL_TO_NOISE_ARRAY
    "BeamAngleForwardArray": 18,  # BEAM_ANGLE_FORWARD_ARRAY
    "VerticalErrorArray": 19,  # VERTICAL_ERROR_ARRAY
    "HorizontalErrorArray": 20,  # HORIZONTAL_ERROR_ARRAY
}


def required_subrecords(profile_path):
    """
    Return every required subrecord entry in a profile.

    Args:
        profile_path: Path to the profile JSON file.

    Returns:
        A list of (record_id, subrecord_entry) tuples, one for each entry in
        the required_subrecords list of each required record.
    """
    with open(profile_path, "r") as f:
        profile = json.load(f)["profile"]
    return [
        (record["record_id"], sub)
        for record in profile.get("required_records", [])
        for sub in record.get("required_subrecords", [])
    ]


@pytest.mark.parametrize("profile_path", PROFILE_PATHS, ids=lambda p: p.name)
class TestProfileSubrecordIds:
    """Tests that profile subrecord IDs agree with the GSF specification."""

    def test_profile_parses(self, profile_path):
        """Test that the profile file parses as JSON with a profile object."""
        with open(profile_path, "r") as f:
            assert "profile" in json.load(f)

    def test_subrecord_ids_match_gsf_h(self, profile_path):
        """Test that each required subrecord's ID matches the ID gsf.h gives its name."""
        for record_id, sub in required_subrecords(profile_path):
            name = sub["subrecord_name"]
            assert name in GSF_SUBRECORD_IDS, f"Record {record_id}: unknown subrecord name '{name}'"
            assert sub["subrecord_id"] == GSF_SUBRECORD_IDS[name], (
                f"Record {record_id}: '{name}' has ID {sub['subrecord_id']}, "
                f"but gsf.h defines it as {GSF_SUBRECORD_IDS[name]}"
            )

    def test_subrecord_ids_are_unique(self, profile_path):
        """Test that no subrecord ID is listed twice for the same record."""
        seen = {}
        for record_id, sub in required_subrecords(profile_path):
            ids = seen.setdefault(record_id, [])
            assert (
                sub["subrecord_id"] not in ids
            ), f"Record {record_id}: subrecord ID {sub['subrecord_id']} is listed twice"
            ids.append(sub["subrecord_id"])
