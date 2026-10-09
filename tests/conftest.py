"""
Pytest configuration and shared fixtures.
"""
import pytest
import tempfile
import os

from tests.gsf_files import attitude, ping, write_gsf


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def make_gsf(tmp_path):
    """
    Return a function that writes a synthetic GSF file in a temporary directory.

    The returned function takes a file name and a list of records built with
    tests.gsf_files.ping() and tests.gsf_files.attitude(), writes them after a
    header record, and returns the file's path.
    """

    def _make_gsf(name, records):
        return write_gsf(tmp_path / name, records)

    return _make_gsf


@pytest.fixture
def compliant_gsf(make_gsf):
    """
    Write a well-formed GSF file and return its path.

    The file has three pings carrying every array in
    tests.gsf_files.FULL_BEAMS, and two attitude records, all in
    strictly increasing time order.
    """
    return make_gsf(
        "compliant.gsf",
        [
            attitude([1700000000.0, 1700000000.5]),
            ping(1700000001.0),
            ping(1700000002.0),
            attitude([1700000002.5, 1700000003.0]),
            ping(1700000003.0),
        ],
    )


@pytest.fixture
def sample_profile():
    """Create a sample profile JSON for testing."""
    return {
        "profile": {
            "name": "Test Profile",
            "gsf_version": "03.11",
            "description": "A test profile for unit testing",
            "coordinate_reference": {
                "horizontal_datum": "WGS-84",
                "vertical_datum": "WGS-84 geoid"
            },
            "required_records": [
                {
                    "record_type": "HeaderRecord",
                    "record_id": 1,
                    "description": "GSF file format version tag"
                },
                {
                    "record_type": "SwathBathymetryPing",
                    "record_id": 2,
                    "required_header_fields": [
                        "timestamp",
                        "latitude",
                        "longitude"
                    ],
                    "required_subrecords": [
                        {
                            "subrecord_name": "ScaleFactors",
                            "subrecord_id": 100
                        },
                        {
                            "subrecord_name": "DepthArray",
                            "subrecord_id": 1
                        }
                    ]
                }
            ]
        }
    }

