# GSF BRB intensity decode: reference gsflib 3.11 vs bundled `pygsf`

This document compares how Leidos reference gsflib (GSF 03.11) decodes subrecord **21 (INTENSITY_SERIES / BRB)** with the bundled reader in `readers/base/pygsf.py`, and lists changes needed for **KMALL EM304** files with **16-bit** backscatter.

Reference source reviewed: `GSF_03-11 3/` (gsflib v03.11).

## Spec summary (reference behaviour)

BRB intensity is **not** a scaled ping array. It does **not** use SCALE_FACTORS (subrecord 100) multiplier/offset.

| Topic | Reference gsflib 3.11 |
|-------|----------------------|
| Scale factors for ID 21 | **Not used** |
| Numeric transform at decode | **None** — raw unsigned samples |
| Internal storage | `unsigned int` per sample |
| Supported `bits_per_sample` | 8, 12, 16, 32 |
| `applied_corrections` | Decoded/stored as flags; **not** applied to values in gsflib |
| Per-beam header | 12 bytes: `sample_count`, `detect_sample`, `start_range_samples`, `spare[6]` |

### Sample decode by width

| Bits | Bytes | Decode |
|------|-------|--------|
| 8 | 1 | `(unsigned int) *ptr` |
| 12 | 3 per 2 samples | Packed bit unpack |
| 16 | 2 | `ntohs()` → `unsigned int` |
| 32 | 4 | `ntohl()` → `unsigned int` |

### BRB subrecord layout (after subrecord size word)

```
bits_per_sample          1 byte
applied_corrections      4 bytes (big-endian uint32)
spare                    16 bytes
sensor imagery           variable (see below)
per beam:
  sample_count           2 bytes (uint16 BE)
  detect_sample          2 bytes (uint16 BE)
  start_range_samples    2 bytes (uint16 BE)   # KMALL
  spare                  6 bytes
  samples[]              sample_count * bytes_per_sample
```

### Sensor imagery skip inside subrecord 21

`DecodeBRBIntensity()` uses `ping->sensor_id` to skip the correct imagery header **before** per-beam samples:

| Sensor subrecord | Imagery bytes skipped |
|------------------|----------------------|
| KMALL (156) | **64** (`DecodeKMALLImagerySpecific`) |
| EM3 / EM4 family | EM3/EM4 imagery decode sizes |
| R2Sonic 2020/2022/2024 | R2Sonic imagery decode |
| Reson 8100, 7125, etc. | respective decode |
| Unknown / default | **0** (misalignment risk) |

For OXR EM304 GSF files, sensor specific subrecord **156 (KMALL)** must be decoded (or 64 bytes skipped) inside the BRB block.

## Current `pygsf.py` behaviour

Subrecord 21 is handled in `SWATH_BATHYMETRY_PING.read()`:

```python
elif subrecord_id == 21:
    self.SNIPPET_SERIES_ARRAY = self.readintensityarray(
        sf.multiplier, sf.offset, datatype, self.snippettype)
```

`readintensityarray()` (`readers/base/pygsf.py`):

1. Reads `bits_per_sample` and `applied_corrections` from the BRB header.
2. **Always** calls `decodeR2SonicImagerySpecific()` (~140 bytes) — not KMALL 64-byte skip.
3. Per beam, reads header as `>hh8s` (does not expose `start_range_samples`).
4. **Always** reads samples as `>NsH` (16-bit unsigned), ignoring `bits_per_sample`.
5. Optionally applies **scale-factor** `scale`/`offset` and log-mean snippet reduction (R2Sonic/QPS workflow).
6. Strips zero samples before aggregation.

The ping reader does **not** track `sensor_id` when decoding subrecord 21, so it cannot select KMALL vs R2Sonic imagery layout.

## Gap analysis

| Item | Reference gsflib 3.11 | Bundled `pygsf` | Impact on KMALL 16-bit |
|------|----------------------|-----------------|------------------------|
| SCALE_FACTORS on ID 21 | Not used | Passes `sf.multiplier`, `sf.offset` | Wrong if SF entry exists; meaningless transform |
| `bits_per_sample` | Honoured (8/12/16/32) | Read then ignored; always `H` | Wrong for non-16-bit; OK only when file is 16-bit |
| 32-bit samples | `ntohl`, 4 bytes each | Would read 2 bytes each | Broken for 32-bit files |
| 12-bit packed | 3 bytes / 2 samples | Not implemented | Broken for 12-bit files |
| KMALL imagery (64 B) | Skipped via sensor_id 156 | R2Sonic decode (~140 B) | **Stream misalignment** — wrong sample counts/values |
| Per-beam `start_range_samples` | Decoded | Not decoded (`8s` spare instead) | Wrong if downstream needs range indexing |
| `applied_corrections` | Stored, not applied | Read, not used consistently | Metadata loss for tools |
| Output shape | Full per-beam time series (`gsfBRBIntensity`) | Collapsed snippet means per beam | Different API; OK for snippet tools only |
| Subrecord padding | None in reference | `seek(4 - subrecord_size % 4)` hack | May hide alignment bugs |

## Recommended fixes for `pygsf.py`

### 1. Stop using SCALE_FACTORS for subrecord 21 (required)

Match reference gsflib: do not pass `sf.multiplier` / `sf.offset` into intensity decode. Subrecord 21 is outside the Table 4-3 scaled-array set.

```python
elif subrecord_id == 21:
    self.brb_intensity = self.read_brb_intensity(self.sensor_id)
```

Do not add ID 21 to `gsf-repair` SCALE_FACTORS repair lists (already reverted in mbtoolkit).

### 2. Track `sensor_id` on each ping (required for KMALL)

Set `self.sensor_id` when subrecord 156 (or other sensor specific) is read, before subrecord 21 is processed. Reference gsflib passes `ping->sensor_id` into `DecodeBRBIntensity()`.

### 3. Replace `readintensityarray()` with spec-aligned `read_brb_intensity()` (required)

Implement a decode path aligned with `DecodeBRBIntensity()`:

**BRB header**

- `bits_per_sample` — 1 byte
- `applied_corrections` — `>I`
- `spare` — 16 bytes

**Sensor imagery** — dispatch on `sensor_id`:

```python
IMAGERY_SKIP = {
    156: 64,   # KMALL_SPECIFIC — skip spare only
    # add EM3/EM4/Reson/R2Sonic sizes as needed
}
```

For KMALL, reference only skips 64 zeroed bytes; no fields are populated.

**Per beam** (repeat `numbeams` times)

```python
sample_count, detect_sample, start_range_samples = struct.unpack('>HHH', ...)
spare = file.read(6)
samples = read_samples(bits_per_sample, sample_count)  # raw unsigned ints
```

**`read_samples(bits_per_sample, n)`**

| bits | Implementation |
|------|----------------|
| 8 | `struct.unpack(f'>{n}B', ...)` |
| 16 | `struct.unpack(f'>{n}H', ...)` |
| 32 | `struct.unpack(f'>{n}I', ...)` |
| 12 | 3-byte unpack loop (port from `gsf_dec.c`) |

Store as Python `list[int]` or `numpy` array — **no** `value / multiplier - offset`.

Expose on the ping object, e.g.:

```python
self.brb_intensity = {
    'bits_per_sample': bps,
    'applied_corrections': flags,
    'time_series': [
        {'sample_count': n, 'detect_sample': d, 'start_range_samples': s, 'samples': [...]},
        ...
    ],
}
```

Keep the old `readintensityarray()` + snippet reduction as an **optional** downstream helper for R2Sonic workflows, not the primary BRB decode.

### 4. Remove subrecord padding hack (recommended)

Delete or guard:

```python
if subrecord_size % 4 > 0:
    self.fileptr.seek(4 - (subrecord_size % 4), 1)
```

Correct imagery skip and sample stride should make this unnecessary. If padding is ever required, derive it from parsed byte count vs `subrecord_size`.

### 5. `gsf_info.py` reporting (optional)

When subrecord 21 is present, report:

- `bits_per_sample`
- `applied_corrections` (decoded flags: LINEAR, CALIBRATED, POWER, GAIN)
- Per-ping total sample count and min/max/mean of raw values
- Do **not** flag missing SCALE_FACTORS entry for ID 21

## Verification checklist

Use a known-good WithBS EM304 file (e.g. OXR, 800 beams, 16-bit, KMALL 156):

1. **Byte alignment** — parsed BRB payload length matches subrecord size (no trailing slack).
2. **Sample counts** — per-beam counts in hundreds for outer beams, not garbage (e.g. 32549 from misalignment).
3. **Totals** — ~8,000–9,700 samples per ping, ~12M+ across file.
4. **Raw range** — 16-bit values roughly 0–65535 (EM304 often ~30k+); no scale-factor math applied.
5. **Cross-check** — compare first ping totals with reference `gsfRead()` or MB-System 5.8.x `mbinfo -F121` sidescan pixel counts.

## Related documents

- [mbsystem_mb_update_arrayptr_fix.md](mbsystem_mb_update_arrayptr_fix.md) — MB-System crash when reading BS through `mb_read()` (separate libmbio bug, not GSF decode).
- GSF spec Table 4-3 — scaled arrays IDs 1–18; intensity (21) is structured BRB, not SF-scaled.

## References (reference gsflib 3.11)

| Function | File |
|----------|------|
| `DecodeBRBIntensity` | `gsf_dec.c` |
| `EncodeBRBIntensity` | `gsf_enc.c` |
| `DecodeKMALLImagerySpecific` | `gsf_dec.c` (64-byte skip) |
| `gsfBRBIntensity`, `gsfTimeSeriesIntensity` | `gsf.h` |
