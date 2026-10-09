# Community GSF Toolkit - User Guide

Welcome to the Community GSF Toolkit user guide. This document provides instructions for using the toolkit's tools and utilities.

## Installation

### Prerequisites

- Python 3.7 or higher
- pip (Python package installer)

### Install Dependencies

```bash
pip install -r requirements.txt
```

No git submodules are required; the GSF reader is bundled in `readers/base`.

This will install:
- `numpy` - For numerical operations
- bundled GSF reader code in `readers/base`

## Available Tools

The toolkit provides several command-line tools for working with GSF files:

### gsf_info.py

Inspect GSF files and print information based on flags.

**Usage:**
```bash
python tools/gsf_info.py <filename> [options]
```

**Options:**
- `--list` - List all datagram record types
- `--positions` - Print timestamp/lat/lon for SWATH_BATHYMETRY
- `--depths` - Print depth arrays from SWATH_BATHYMETRY
- `--depthStats` - Print min/max/mean stats and beam flag summary
- `--attitude` - Print attitude records
- `--summary` - Print summary of datagram counts
- `--pingHeader` - Print full SWATH_BATHYMETRY ping headers
- `--pingHeaderVerbose` - Print ping headers + decoded sub-record payloads

**Example:**
```bash
python tools/gsf_info.py data/sample.gsf --summary --positions
```

### gsf_verify.py

Validate a GSF file against a profile JSON.

**Usage:**
```bash
python tools/gsf_verify.py <profile> <gsf_file>
```

**Example:**
```bash
python tools/gsf_verify.py profiles/xyz.json data/sample.gsf
```

### gsf_repair.py

Repair a GSF file to comply with a minimal profile (e.g., missing subrecords).

**Usage:**
```bash
python tools/gsf_repair.py <profile> <infile> --out <output_file>
```

**Example:**
```bash
python tools/gsf_repair.py profiles/xyz.json data/sample.gsf --out data/repaired.gsf
```

### gsf_timecheck.py

Verify that SWATH_BATHYMETRY and ATTITUDE records are strictly time-increasing.

**Usage:**
```bash
python tools/gsf_timecheck.py <filename>
```

**Example:**
```bash
python tools/gsf_timecheck.py data/sample.gsf
```

## Profiles

The toolkit uses JSON profile files to define validation rules. Available profiles:

- `profiles/xyz.json` - Minimal XYZ profile
- `profiles/singlebeam.json` - Single-beam profile
- `profiles/multibeam.json` - Complete multibeam profile

## Common Workflows

### Validating a GSF File

1. Choose an appropriate profile
2. Run verification:
   ```bash
   python tools/gsf_verify.py profiles/xyz.json your_file.gsf
   ```

### Inspecting File Contents

```bash
python tools/gsf_info.py your_file.gsf --summary --positions
```

### Checking Time Ordering

```bash
python tools/gsf_timecheck.py your_file.gsf
```

## Troubleshooting

### Import Errors

If you see import errors, run commands from the repository root so `readers/base` is importable:
```bash
python tools/gsf_info.py data/sample.gsf --summary
```

### File Not Found

Ensure you're using the correct path to your GSF file. Use absolute paths if needed.

## Getting Help

- Check GitHub Issues for known problems
- Open a new issue for bugs or questions
- Join community discussions (channels to be established)

---

**Note**: This is an initial placeholder. Detailed user documentation with examples and tutorials will be added as the project evolves.

