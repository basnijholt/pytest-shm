---
icon: lucide/triangle-alert
---

# Caveats

## Only output during the session is contained

Temporary files created before the session starts (while the initial `conftest.py` files are imported, in `pytest_configure`, or in other plugins' `pytest_sessionstart` hooks) or after it ends (`pytest_terminal_summary`, `pytest_unconfigure`) land directly in `/dev/shm` and stay there until reboot.
Create them in fixtures, or remove them yourself.

## Caches under the temp root become per-session

A library that caches downloads under `tempfile.gettempdir()` sees the contained directory, which the plugin frees after the session, so it downloads again every session.
If your suite uses such a library, point its cache at a stable directory in your root `conftest.py`, where `tempfile.gettempdir()` is still `/dev/shm`.
Which environment variable to set depends on the library.
For example, [tiktoken](https://github.com/openai/tiktoken) reads `TIKTOKEN_CACHE_DIR`, falling back to `DATA_GYM_CACHE_DIR`:

```python
# conftest.py at the repository root (tiktoken shown as an example)
import os
import tempfile
from pathlib import Path

if "TIKTOKEN_CACHE_DIR" not in os.environ and "DATA_GYM_CACHE_DIR" not in os.environ:
    os.environ["TIKTOKEN_CACHE_DIR"] = str(Path(tempfile.gettempdir()) / "data-gym-cache")
```

## Temp files live on another filesystem

`os.rename` or `os.replace` from a temporary file into your project fails with `EXDEV`, as it already does wherever `/tmp` is tmpfs.

## Paths get longer

`/dev/shm/pytest-of-<user>/pytest-N/popen-gwN/shm-tmp/tmpXXXXXXXX` is much longer than `/tmp/tmpXXXXXXXX`, which matters for the 107-byte limit on `AF_UNIX` socket paths.

## Files use RAM

Everything a session writes counts against memory until the session ends.
Base directories of failing sessions stay until the machine reboots or later failing sessions push them out of pytest's retention of three numbered directories; passing sessions reuse the freed number instead of advancing it.
