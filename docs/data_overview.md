# Data Overview

## Data Storage

GSF (Generic Sensor Format) files are typically large binary files containing bathymetry and sonar data. For repository size and performance reasons, **sample and test data files are not stored directly in this repository**.

Instead, data files are maintained in a separate location and referenced by this documentation.

## Data Sources

Test and sample data for the Community GSF Toolkit may be available from:

- **External data repository** (to be established)
- **Public datasets** from hydrographic surveys
- **Community-contributed samples** (with appropriate permissions)
- **Your own GSF files** for testing

## Data Directory Structure

The `data/` directory in this repository is intended for:
- Small sample files for quick testing
- Documentation and metadata about available datasets
- Links or references to larger datasets stored elsewhere

## Example Data Entry

Below is an example of how data files are documented:

### Example: EM2040 Multibeam Survey Data

**File Name:** `0000_20220928_150917_EM2040.gsf`

**Description:**
- Multibeam survey data collected with Kongsberg EM2040 system
- Date: September 28, 2022
- Survey identifier: 0000
- Time: 15:09:17 UTC

**File Characteristics:**
- Format: GSF 3.11
- Record Types: SWATH_BATHYMETRY, ATTITUDE, SOUND_VELOCITY_PROFILE
- Approximate Size: ~150 MB
- Number of Pings: ~12,000
- Coverage: Coastal survey area

**Usage:**
```bash
# Verify against multibeam profile
python tools/gsf_verify.py profiles/multibeam.json 0000_20220928_150917_EM2040.gsf

# Inspect file contents
python tools/gsf_info.py 0000_20220928_150917_EM2040.gsf --summary

# Check time ordering
python tools/gsf_timecheck.py 0000_20220928_150917_EM2040.gsf
```

**Location:** [External data repository URL or local path]

**Access:** Public / Requires authentication / Contact maintainers

**License:** [Data license information]

**Metadata:**
- Coordinate System: WGS-84
- Depth Range: 5-200 meters
- Beam Count: 256 beams per ping
- Ping Rate: ~10 Hz

---

## Adding New Data Entries

When documenting new datasets, include:

1. **File identification**: Name, source, date
2. **Technical details**: Format version, record types, size
3. **Usage examples**: Command-line examples for toolkit tools
4. **Access information**: Where to obtain the file
5. **Metadata**: Coordinate system, survey parameters, etc.

## Data Privacy and Licensing

- Ensure all data files comply with privacy and licensing requirements
- Do not include proprietary or sensitive survey data without permission
- Clearly document data sources and any usage restrictions
- Respect copyright and data ownership

## Obtaining Test Data

For testing and development:

1. **Use your own GSF files** if available
2. **Request access** to sample datasets (contact maintainers)
3. **Check external repositories** for public GSF datasets
4. **Generate synthetic data** for specific test cases (if tools available)

## Questions?

- For data access requests, open a GitHub issue
- For questions about data formats, see the user guide
- For contributing sample data, see CONTRIBUTING.md

---

**Note**: This is an initial placeholder. Detailed data catalog and access instructions will be added as the project evolves.

