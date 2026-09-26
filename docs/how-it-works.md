---
icon: lucide/cog
---

# How It Works

## Temp root

Before any `conftest.py` is imported, the plugin sets `TMPDIR=/dev/shm`.
`tmp_path`, `tmp_path_factory`, and every `tempfile` call then land in memory, and so does anything your conftests compute from the temp root at import time.

## Containment

Tests and the code they drive often call `tempfile.mkdtemp()` without removing the result.
On disk that only clutters `/tmp`, but on tmpfs it would hold memory until reboot.
When the session starts, before collection, the plugin points `TMPDIR` at `<basetemp>/shm-tmp`, so that output lives and dies with pytest's own base directory.

## Cleanup

pytest keeps the last three sessions' base directories.
When a session passes, collects no tests, or stops at a usage error, the plugin deletes its base directory right away instead of holding it in memory.
A failing session keeps everything for inspection.

Deleting per test is deliberately not offered: pytest would then reuse the freed directory names, and caches keyed by path would hand the next test the previous one's state.

## pytest-xdist

Each worker owns `<basetemp>/popen-gwN` and cleans up after itself, so a failing run keeps only the directories of workers that saw a failure.
A `--basetemp` you pass yourself is never deleted, with or without xdist.

## When it stays off

The plugin leaves the temp root alone, and says why in the report header, when any of these holds:

| Condition | Header |
| --- | --- |
| Not running on Linux | `shm: off, not Linux` |
| `TMPDIR`, `TEMP`, or `TMP` is exported | `shm: off, TMPDIR is exported` |
| `--basetemp` or `PYTEST_DEBUG_TEMPROOT` puts pytest's base directory outside `/dev/shm` | `shm: off, --basetemp is outside /dev/shm` |
| pytest's `tmpdir` plugin is disabled (`-p no:tmpdir`) | `shm: off, pytest's tmpdir plugin is disabled` |
| `/dev/shm` is missing, or not writable and searchable | `shm: off, /dev/shm is missing or not writable` |
| `/dev/shm` is mounted `noexec` (Docker's default), which would break tests that run scripts they write | `shm: off, /dev/shm is mounted noexec` |
| `/dev/shm` has less free space than `shm_min_free_gib` (Docker's default is 64 MiB) | `shm: off, /dev/shm has 0.1 GiB free, below shm_min_free_gib = 1` |

If you export `TMPDIR=/dev/shm` yourself, the plugin still contains and cleans up temporary files, as long as pytest's base directory is on `/dev/shm` too.
