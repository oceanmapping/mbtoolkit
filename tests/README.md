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

Backend contracts are covered by `test_backends.py`. Run the suite once with
only core dependencies and once in an environment installed with `.[dev,gsfu]`.
The core-only run skips optional gsfu cases. Contract fixtures are built directly
from GSF wire layouts and exercise both adapters, checksummed records, inherited
scale factors, normalized units and times, owned buffers, unknown records,
explicit failure paths, and third-party plugin loading.

- `test_utils.py` - Tests for utility functions (scan_subrecords, scan_subrecord_ids)
- `test_gsf_verify.py` - Tests for profile loading and validation utilities
- `test_gsf_repair.py` - Tests for repair functionality
- `conftest.py` - Shared pytest fixtures and configuration

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

