# MB-System fix: `mb_update_arrayptr()` false match after array reallocation

## Summary

`mbinfo` and other MB-System tools crash on Linux when reading GSF files that include KMALL backscatter (BRB subrecord 21) with high beam counts (e.g. EM304: 800 beams, ~9,664 sidescan pixels per ping). Files without backscatter read fine.

The crash typically appears as:

- `malloc(): memory corruption`
- `realloc(): invalid old size`
- Segmentation fault in `mb_update_arrays()` → `mb_reallocd()`

The underlying bug is pointer corruption in `mb_read()` that occurs **before** the aborting `realloc()`.

## Symptoms

| Condition | Result |
|-----------|--------|
| GSF with BRB intensity (subrecord 21) | Crash on first ping with sidescan data |
| GSF without BRB (bathy/amplitude only) | OK |
| Format 121 (`MBF_GSFGENMB`) | Correct format; bug is in `libmbio`, not GSF encoding |
| 16-bit intensity | Not the root cause; backscatter presence triggers the realloc path |

Example reproduction:

```bash
mbinfo -F121 -I 0068_20210706_055755_OXR20210703-EM304_EM304.gsf
```

Representative stack trace:

```
mb_read → mb_read_ping → mb_update_arrays → mb_reallocd → abort
```

## Root cause

Programs such as `mbinfo` register per-application output arrays via `mb_register_array()`. When a ping requires larger buffers than the format defaults (`beams_bath_max=254`, `pixels_ss_max=8192`), `mb_read_ping()` calls `mb_update_arrays()` to grow bathymetry and sidescan allocations. `mb_read()` then calls `mb_update_arrayptr()` to refresh local pointers (`bath`, `sslon`, etc.) held by the caller.

### Current (buggy) logic

**File:** `src/mbio/mb_mem.c`  
**Function:** `mb_update_arrayptr()`

```c
for (int i = 0; i < mb_io_ptr->n_regarray && !found; i++) {
    if (*handle == mb_io_ptr->regarray_oldptr[i]) {
        *handle = mb_io_ptr->regarray_ptr[i];
        found = true;
    }
}
```

This matches registrations by comparing the **data pointer** (`*handle`) against **stale freed addresses** in `regarray_oldptr[]`.

### Why this fails

1. **No registration identity** — does not use `regarray_handle[i]` (the stable address of the caller’s `double **` / `char **` variable).
2. **No type filter** — a sidescan pointer can match a bathymetry `regarray_oldptr` entry.
3. **Stale old pointers** — `regarray_oldptr[i]` is set on realloc but not cleared after update, so recycled heap addresses remain in the search set.
4. **Linux heap recycling** — when the old bath buffer is freed and its address reused, `sslon` can be rebound to the **bathymetry** allocation (~1,024 doubles) instead of the sidescan allocation (~9,728 doubles).

### Failure sequence

1. First ping with backscatter forces **both** bath and sidescan registered arrays to grow in one `mb_update_arrays()` call.
2. `mb_update_arrayptr((void **)&sslon, …)` false-matches a bathymetry registration via recycled heap address.
3. `mb_read()` writes sidescan longitudes into the undersized bath buffer:

   **File:** `src/mbio/mb_read.c`

   ```c
   for (int i = 0; i < mb_io_ptr->pixels_ss_max; i++) {
       if (mb_io_ptr->ss_num[i] > 0) {
           sslon[i] = *navlon + headingy * mtodeglon * mb_io_ptr->ss_acrosstrack[i] +
                      headingx * mtodeglon * mb_io_ptr->ss_alongtrack[i];
           ...
           *nss = i + 1;
       }
   }
   ```

   With ~9,664 pixels, this writes far past a ~1,024-element bath buffer → heap corruption.
4. Next `realloc()` detects corruption and aborts.

Backscatter triggers the bug because it is the first condition that forces sidescan buffers to grow past `pixels_ss_max=8192`, invoking `mb_update_arrayptr()` for `sslon` on the same ping as a bath grow.

## Suggested fix

**File:** `src/mbio/mb_mem.c`  
**Function:** `mb_update_arrayptr()`

Match registrations by the **handle address** (pointer-to-pointer), which is unique and stable for the life of the registration:

```c
int mb_update_arrayptr(int verbose, void *mbio_ptr, void **handle, int *error)
{
    if (verbose >= 2 || mb_mem_debug) {
        fprintf(stderr, "\ndbg2  MBIO function <%s> called\n", __func__);
        fprintf(stderr, "dbg2  Input arguments:\n");
        fprintf(stderr, "dbg2       verbose:    %d\n", verbose);
        fprintf(stderr, "dbg2       handle:     %p\n", (void *)handle);
        fprintf(stderr, "dbg2       *handle:    %p\n", (void *)*handle);
    }

    struct mb_io_struct *mb_io_ptr = (struct mb_io_struct *)mbio_ptr;

    for (int i = 0; i < mb_io_ptr->n_regarray; i++) {
        if ((void **)handle == (void **)mb_io_ptr->regarray_handle[i]) {
            *handle = (void *)mb_io_ptr->regarray_ptr[i];
            mb_io_ptr->regarray_oldptr[i] = NULL;
            break;
        }
    }

    if (verbose >= 2 || mb_mem_debug) {
        fprintf(stderr, "\ndbg2  MBIO function <%s> completed\n", __func__);
        fprintf(stderr, "dbg2  Return values:\n");
        fprintf(stderr, "dbg2       *handle:    %p\n", (void *)*handle);
        fprintf(stderr, "dbg2       error:      %d\n", *error);
        fprintf(stderr, "dbg2  Return status:\n");
        fprintf(stderr, "dbg2       status:  %d\n", MB_SUCCESS);
    }

    return MB_SUCCESS;
}
```

### Why this works

`mb_register_array()` stores the caller’s `handle` in `regarray_handle[i]` and updates `*handle` in place during `mb_update_arrays()`. After realloc, only the **data pointer** (`*handle`) changes; the **handle variable’s address** does not. Matching on `handle == regarray_handle[i]` is unambiguous across bathymetry, amplitude, and sidescan registrations and cannot cross-bind due to heap address reuse.

### Optional hardening

In `mb_update_arrays()`, after updating each registered array via `mb_reallocd()`, set `regarray_oldptr[i] = NULL` so no stale freed addresses remain searchable by any future logic.

## Why not other approaches

| Approach | Problem |
|----------|---------|
| Match on `*handle == regarray_ptr[i]` | Fails after first update; `*handle` already equals new pointer |
| Filter by `regarray_type` only | Still relies on address equality; wrong `*handle` can still match |
| Increase default `pixels_ss_max` / `beams_bath_max` | Avoids first realloc on some files; does not fix the logic bug |

## Files involved

| File | Role |
|------|------|
| `src/mbio/mb_mem.c` | `mb_register_array()`, `mb_update_arrays()`, **`mb_update_arrayptr()` (fix here)** |
| `src/mbio/mb_read.c` | Calls `mb_update_arrayptr()` for `sslon`/`sslat`; writes `sslon[i]` up to `pixels_ss_max` |
| `src/mbio/mb_get.c` | Same pattern for acrosstrack/alongtrack sidescan pointers |
| `src/utilities/mbinfo.cc` | Registers `datacur->sslon` via `mb_register_array()` |

## Verification

1. Read EM304 GSF with backscatter through the full file:

   ```bash
   mbinfo -F121 -I <file_with_BRB>.gsf
   ```

2. Confirm sidescan stats appear (max pixels/ping > 8,192; millions of total pixels).

3. Run under Valgrind: no invalid writes to bath-sized allocations during `sslon[]` assignment in `mb_read()`.

4. Regression: read NO_BS GSF and legacy low-beam-count formats unchanged.

## Workarounds (until fixed upstream)

- Process GSF exports **without** subrecord 21 (bathy/amplitude only).
- Strip BRB intensity from GSF before feeding MB-System.
- Upgrade MB-System only after confirming this fix (or equivalent) is present in the installed `libmbio`.

## References

- GSF format 121: `MBF_GSFGENMB` / Leidos Generic Sensor Format
- Affected data: KMALL EM304 GSF v03.10 with 800 beams and 16-bit BRB intensity
- Related mbtoolkit context: BRB intensity is valid per GSF spec; absence of intensity scale factors is not a spec violation
