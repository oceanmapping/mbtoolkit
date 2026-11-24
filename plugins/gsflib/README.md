# Reference C GSF backend

This optional package registers `gsflib` with mbtoolkit. It uses a small CPython
extension compiled against the reference headers; Python never duplicates GSF
structure layouts. The core toolkit requires neither this package nor a compiler.

## Installation

Use CPython with the GIL, a C compiler, and the [official Leidos GSF 3.11
distribution](https://www.leidos.com/products/ocean-marine). Extract the archive
outside this repository. From the mbtoolkit repository root:

```sh
python -m pip install .
GSFLIB_SOURCE_DIR=/absolute/path/to/GSF_03-11 python -m pip install ./plugins/gsflib
```

`GSFLIB_SOURCE_DIR` must contain the reference headers and seven `gsf*.c` files.
They compile into the extension, so this installation has no separate `libgsf`
runtime dependency. The reference source is supplied by the user, subject to its
own distribution terms; it is not included in this repository.

Alternatively, link an existing installation with matching GSF 3.11 headers and
library (`include/gsf.h`, `include/gsf_dec.h`, `include/gsf_ft.h`, `lib/libgsf.*`):

```sh
GSFLIB_PREFIX=/absolute/path/to/gsf python -m pip install ./plugins/gsflib
```

Set exactly one build variable. The prefix is recorded as a runtime library search
path on Unix; keep that installation available. Rebuild the plugin when changing
the library or its headers. `BackendInfo.version` reports the compile-time
`GSF_VERSION`, so the linked library must match those headers. Source builds were
tested on macOS; Windows builds have not been validated.

## Use

All four tools use the existing selection mechanism:

```sh
gsf-info survey.gsf --backend gsflib
gsf-verify profiles/xyz.json survey.gsf --backend gsflib
gsf-repair profiles/xyz.json survey.gsf --backend gsflib --out repaired.gsf
gsf-timecheck survey.gsf --backend gsflib
gsf-info --list-backends
export MBTOOLKIT_GSF_BACKEND=gsflib
```

```python
from readers import DecodeRequest, open_reader

with open_reader("survey.gsf", backend="gsflib") as reader:
    for record in reader.records(DecodeRequest(frozenset({2, 12}), True)):
        if record.record_id == 2:
            print(record.data.fields["timestamp_ns"], record.data.arrays.get(1))
```

## Contract and limits

The adapter projects file headers, bathymetry pings, and attitude records for GSF
2.x and 3.x. All 30 standard scalar beam-array types are projected, including
packed quality flags and the reference library's compressed arrays. Structured
BRB intensity series have no API v1 projection and produce a diagnostic; their
original bytes remain available. Other record types remain raw.

Each pass opens a read-only SDK handle and closes it on completion, error, or
early exit. No GSF index files are created. SDK calls retain
the CPython GIL because the reference library has shared global state. Concurrent
readers use separate handles, and inherited scale factors are checked per pass.
The shim owns a decoder file table per pass, copies its buffers before returning,
and frees that table with `gsfFree` on close. Record views alias those buffers and
are never freed separately.

The shared toolkit reader owns framing, unknown-record retention, checksums, and
writing policy. The shim calls the reference `gsfDecode*` functions on the
toolkit's framed payloads. This avoids `gsfRead` rejecting unknown
record IDs while skipping records. These decoder interfaces require matching
`gsf_dec.h` and `gsf_ft.h` as well as `gsf.h`; rebuild against each SDK version.
Variable counts and scalar array extents are checked before decoding. The
projection omits BRB subrecords, retaining them in `Record.raw` with a diagnostic;
their nested sample buffers are never allocated by this adapter. The C
library may decode more than the requested projection, including
arrays when only ping headers are requested. Its record-size limits and native
decode failures remain explicit errors. Headerless fragments cannot be decoded
semantically by this backend. There is no fallback to another parser.

Run the common contract suite after installation:

```sh
python -m pip install pytest
python -m pytest -q
```
