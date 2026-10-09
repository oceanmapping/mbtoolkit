# Test Suite

This directory contains unit tests for the Community GSF Toolkit.

## Running Tests

### Prerequisites

Install test dependencies:
```bash
pip install -e ".[dev]"
```

Or install pytest directly:
```bash
pip install pytest
```

### Run All Tests

```bash
pytest
```

### Run Specific Test File

```bash
pytest tests/test_utils.py
```

### Run with Verbose Output

```bash
pytest -v
```

### Run with Coverage

```bash
pip install pytest-cov
pytest --cov=tools --cov-report=html
```

## Test Structure

- `test_utils.py` - Tests for utility functions (subrecord scanning, time conversion, and the
  missing-subrecord check)
- `test_gsf_info.py` - Tests for gsf-info's output options
- `test_gsf_verify.py` - Tests for profile loading and validation
- `test_gsf_repair.py` - Tests for repair functionality
- `test_gsf_timecheck.py` - Tests for time-order checking
- `test_gsf_files.py` - Tests for the synthetic GSF file helpers
- `gsf_files.py` - Helpers that build small GSF files for the tests
- `conftest.py` - Shared pytest fixtures and configuration

## Test Data

The tests need no sample data files. They build small, synthetic GSF files
with the helpers in `gsf_files.py`, which write pings and attitude records
through the gsfu library. The `make_gsf` fixture writes such a file in a
temporary directory, and `compliant_gsf` provides a well-formed one.
`remove_subrecord()` and `insert_subrecord()` edit a written file to make
pings gsfu would never write, such as one without scale factors.

## Writing New Tests

1. Create a new test file following the pattern `test_*.py`
2. Use pytest fixtures from `conftest.py` when available
3. Follow the existing test structure and naming conventions
4. Add docstrings to test classes and functions

## Example Test

```python
def test_example():
    """Test description."""
    result = function_to_test(input_data)
    assert result == expected_output
```

