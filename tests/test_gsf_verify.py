"""
Tests for gsf-verify functionality.
"""
import pytest
import json
import os
import tempfile
from tools.gsf_verify import load_profile, attr_map


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


class TestAttrMap:
    """Tests for attr_map function."""

    def test_attr_map_basic(self):
        """Test basic attribute name mapping."""
        assert attr_map("timestamp") == "timestamp"
        assert attr_map("num_beams") == "numbeams"
        assert attr_map("centre_beam") == "centrebeam"

    def test_attr_map_no_underscores(self):
        """Test attribute mapping with no underscores."""
        assert attr_map("timestamp") == "timestamp"
        assert attr_map("id") == "id"

    def test_attr_map_multiple_underscores(self):
        """Test attribute mapping with multiple underscores."""
        assert attr_map("required_header_fields") == "requiredheaderfields"
        assert attr_map("sub_record_id") == "subrecordid"

    def test_attr_map_empty_string(self):
        """Test attribute mapping with empty string."""
        assert attr_map("") == ""

