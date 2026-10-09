# Community GSF Toolkit - Developer Guide

This guide is for developers who want to understand, modify, or extend the Community GSF Toolkit.

## Project Structure

```
mb-community-toolkit/
├── tools/             # Command-line tools
│   ├── gsf_info.py
│   ├── gsf_verify.py
│   ├── gsf_repair.py
│   └── gsf_timecheck.py
├── profiles/          # JSON validation profiles
│   ├── xyz.json
│   ├── singlebeam.json
│   └── multibeam.json
├── docs/             # Documentation
├── data/             # Sample/test data files
└── requirements.txt  # Python dependencies
```

## Development Setup

### Prerequisites

- Python 3.8+
- pip
- Git

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/community-gsf-toolkit.git
   cd community-gsf-toolkit
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   This installs [gsfu](https://pypi.org/project/gsfu/), the library the tools read GSF files with.

3. (Optional) Install in development mode if creating a package structure

## Architecture Overview

### Core Components

- **GSF Reader**: Uses the `gsfu` library to read GSF data
- **Profile System**: JSON-based validation profiles define required records and subrecords
- **Command Tools**: Standalone scripts for specific operations

### Key Dependencies

- `gsfu`: GSF reader and writer (https://pypi.org/project/gsfu/)
- `numpy`: Numerical operations for array processing

## Code Organization

### Scripts (`tools/`)

Each script is a standalone command-line tool:
- `gsf_info.py`: File inspection and information extraction
- `gsf_verify.py`: Profile-based validation
- `gsf_repair.py`: File copying with a report of unmet profile requirements
- `gsf_timecheck.py`: Time ordering verification

### Profiles (`profiles/`)

JSON files defining validation rules:
- Record types and IDs
- Required header fields
- Required subrecords
- Constraints and encoding recommendations

## Extending the Toolkit

### Adding a New Tool

1. Create a new script in `tools/`
2. Follow existing patterns for:
   - Argument parsing
   - File I/O
   - Error handling
3. Add documentation
4. Update this guide

### Creating a New Profile

1. Create JSON file in `profiles/`
2. Define required records and subrecords
3. Specify constraints and encoding recommendations
4. Test with `gsf_verify.py`

### Common Patterns

**Reading GSF Files:**
```python
from GSFU import gsf

reader = gsf("file.gsf")
for record_type, offset, record in reader.iter_records("SWATH_BATHYMETRY_PING"):
    depths = record["Beams"]["Depth_m"]  # None if the ping has no depth array
    # Process the ping
```

**Profile Loading:**
```python
import json

with open("profile.json", 'r') as f:
    profile = json.load(f)['profile']
```

## Testing

### Running Tests

Install test dependencies:
```bash
pip install -e ".[dev]"
```

Run all tests:
```bash
pytest
```

Run specific test file:
```bash
pytest tests/test_utils.py
```

Run with verbose output:
```bash
pytest -v
```

### Test Structure

The `tests/` directory contains:
- `test_utils.py` - Tests for utility functions
- `test_gsf_info.py` - Tests for gsf-info
- `test_gsf_verify.py` - Tests for profile loading and validation
- `test_gsf_repair.py` - Tests for repair functionality
- `test_gsf_timecheck.py` - Tests for time-order checking
- `gsf_files.py` - Helpers that build synthetic GSF files, so no sample data is needed
- `conftest.py` - Shared pytest fixtures

### Writing Tests

1. Create test files following the pattern `test_*.py`
2. Use pytest fixtures from `conftest.py` when available, such as `make_gsf` to write a
   synthetic GSF file
3. Follow existing test structure and naming conventions
4. See `tests/README.md` for more details

### Manual Testing

Test with sample GSF files in `data/` directory:
```bash
python tools/gsf_verify.py profiles/xyz.json data/sample.gsf
```

### Test Files

- Use provided sample files
- Ensure no sensitive data in test files
- Add new test cases as needed

## Code Style

- Follow PEP 8
- Use type hints where appropriate
- Add docstrings to functions
- Keep functions focused and modular

## Building and Distribution

(To be documented when package structure is established)

## Debugging

### Common Issues

- **Import errors**: Install the dependencies with `pip install -r requirements.txt`
- **File format errors**: Verify GSF file integrity
- **Profile validation**: Check JSON syntax and structure

### Debug Tips

- Use `--pingHeaderVerbose` in `gsf_info.py` for detailed inspection
- Check raw file structure with hex dump if needed
- Validate profile JSON syntax separately

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

## Resources

- GSF Format Specification (to be linked)
- pygsf Documentation (to be linked)
- Community Resources (to be established)

---

**Note**: This is an initial placeholder. Detailed developer documentation including API references, architecture diagrams, and advanced topics will be added as the project evolves.

