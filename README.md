# Overview

Community Multibeam Toolkit
An open-source suite of verification, conversion, and best-practice tools for Generic Sensor Format (GSF) data. Our mission is to launch and foster an active user & developer community around a common processing formats for bathymetry and sonar data.

## Vision & Goals

### Community Building

- Engage primary stakeholders (surveyors, software developers, data managers)
- Establish channels for collaboration, feedback, and support

### Standards & Best Practices
- Document recommended workflows for GSF data ingestion, processing, and export
- Provide style guides, coding conventions, and metadata guidelines
### Open-Source Tooling
- Deliver verification tools to validate existing (legacy) GSF files
- Provide conversion utilities to modernize or migrate legacy formats into GSF
- Encourage community contributions, plug-ins, and extensions
## Roadmap
- Initial release of conversion & verification tools
- Community engagement: hackathons, virtual meetups, and online discussions
### Future
- Expanded profile/check suites (minimal-XYZ, full-multibeam, single-beam-in-swath)
- Promote integrations with GIS and hydrographic software
- Comprehensive tutorials, reference datasets, and best-practice guides

# Getting Started
1. Clone the repo
   ```bash
   git clone https://github.com/oceanmapping/mbtoolkit.git
   cd mbtoolkit
   ```
2. (Optional) create a virtual environment
   ```bash
   conda create --name venv python=3.13
   conda activate venv
   ```
3. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
   The toolkit reads and writes GSF files with the [gsfu](https://pypi.org/project/gsfu/)
   library, which this installs.
4. Verify a GSF file
   ```
   python ./tools/gsf_verify.py minimal-xyz.json path/to/data.gsf # see ./profiles
   ```
5. Explore content of a GSF file
   ```
   python ./tools/gsf_info.py path/to/data.gsf --list --attitude
   ```
6. Verifies that bathy and attitude records have strictly time-increasing timestamps
   ```
   python ./tools/gsf_timecheck.py path/to/data.gsf
   ```
7. Copies a GSF file and reports the pings that lack subrecords a profile requires.
   (It no longer pads them with empty subrecords, which GSF readers misread.)
   ```
   python ./tools/gsf_repair.py minimal-xyz.json path/to/data.gsf -o path/to/data_fixed.gsf
   ```

# Contributing
We welcome all contributions!
- Join the conversation: subscribe to our mailing list or join the #gsf-toolkit channel on Slack
- Report toolkit issues: open bugs, feature requests, or questions on GitHub

Submit PRs: follow our CONTRIBUTING.md for guidelines; include tests & documentation

# Documentation
- [Toolkit User Guide](docs/user_guide.md)
- [Toolkit Developer Guide](docs/developer_guide.md)

# License
This project is released under the MIT License. See [LICENSE](LICENSE) for details.
