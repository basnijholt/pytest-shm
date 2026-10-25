# pytest-shm

[![PyPI](https://img.shields.io/pypi/v/pytest-shm)](https://pypi.org/project/pytest-shm/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-shm)](https://pypi.org/project/pytest-shm/)
[![Docs](https://img.shields.io/badge/docs-pytest--shm.nijho.lt-blue)](https://pytest-shm.nijho.lt)
[![License](https://img.shields.io/github/license/basnijholt/pytest-shm)](https://github.com/basnijholt/pytest-shm/blob/main/LICENSE)
[![CI](https://github.com/basnijholt/pytest-shm/actions/workflows/ci.yml/badge.svg)](https://github.com/basnijholt/pytest-shm/actions/workflows/ci.yml)

<img src="https://raw.githubusercontent.com/basnijholt/pytest-shm/main/docs/logo.svg" alt="pytest-shm logo" align="right" width="200" />

**Faster tests for code that saves files, by keeping pytest's temporary files in memory instead of on disk.**

Install it and run pytest as usual.
There is nothing to configure, and most test suites need no changes.

## Table of Contents

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [The problem: waiting on the disk](#the-problem-waiting-on-the-disk)
- [The fix: a folder that lives in memory](#the-fix-a-folder-that-lives-in-memory)
- [Does it help?](#does-it-help)
- [Installation](#installation)
- [How it works](#how-it-works)
- [When it stays off](#when-it-stays-off)
- [Configuration](#configuration)
- [Caveats](#caveats)
- [Development](#development)
- [License](#license)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## The problem: waiting on the disk

When a program saves something it cannot afford to lose, writing the file is not enough.
The operating system first keeps written data in memory and copies it to the disk a little later, so a power cut could still lose it.
To be sure, the program asks the operating system to push the data all the way to the disk and waits until the disk confirms.
That request is called `fsync`.

SQLite does this on every commit by default, and careful code that replaces a file safely ("atomic writes") does it too.
Each `fsync` takes from a fraction of a millisecond to many milliseconds, depending on the disk.
In production that wait is the price of not losing data.
In tests it buys nothing, because nobody needs a test's files to survive a power cut.
A suite that saves data thousands of times can spend most of its time just waiting on the disk.

## The fix: a folder that lives in memory

Linux has a folder, `/dev/shm`, that looks like any other folder but keeps its files in memory.
The name is short for *shared memory*, because programs use it to share data through memory, and the kind of filesystem behind it is called *tmpfs*.
Files there can be created, written, read, and deleted like any other file, but `fsync` has no disk to wait for, so it returns immediately.

pytest-shm moves pytest's temporary files into `/dev/shm`.
That covers `tmp_path`, `tmp_path_factory`, and anything Python's `tempfile` module creates in its default location.
Because those files take up memory, the plugin also cleans up what the test session created after a passing run, and keeps it after a failing run so you can inspect it.
[How it works](#how-it-works) and the [caveats](#caveats) list what it leaves behind.

## Does it help?

That depends on how much of your suite waits on `fsync`.
As one data point, [MindRoom](https://github.com/mindroom-ai/mindroom) has about 26,000 tests that commit SQLite transactions and write files atomically throughout:

| Measurement | Without pytest-shm | With pytest-shm |
| --- | --- | --- |
| Summed test time, 32 workers on an NVMe disk | 5236 s | 1426 s |
| GitHub Actions test step | about 16 min | 12-15 min |

To measure your own suite, compare a plain `pytest` run with `pytest -o shm_min_free_gib=inf`, which keeps the plugin off.

Tests that check your code survives a crash still mean the same thing.
They simulate the program crashing, not the machine losing power, and data a crashed program already handed to the operating system is safe whether or not it reached the disk.
The [caveats](#caveats) list the few differences other tests can notice.

## Installation

```bash
uv add --dev pytest-shm
# or
pip install pytest-shm
```

It needs Python 3.10+ and pytest 8.4+, and pytest loads it automatically.
It only acts on Linux, and only when `/dev/shm` is safe to use; elsewhere, and whenever you export `TMPDIR` to a folder other than `/dev/shm`, it leaves your temporary files where they are, so it is safe to add to cross-platform projects.
The report header at the top of each run tells you whether it is active:

```text
shm: temp root /dev/shm
```

or why it is not:

```text
shm: off, TMPDIR is exported
```

## How it works

1. **Temp root.** Before any `conftest.py` is imported, the plugin sets `TMPDIR=/dev/shm`, so `tmp_path`, `tmp_path_factory`, and every `tempfile` call land in memory.
2. **Containment.** Tests and the code they drive often call `tempfile.mkdtemp()` without removing the result. On disk that clutters `/tmp`; on tmpfs it would hold memory until reboot. When the session starts, before collection, the plugin points `TMPDIR` at `<basetemp>/shm-tmp`, so that output lives and dies with pytest's own base directory.
3. **Cleanup.** pytest keeps the last three sessions' base directories. When a session passes, collects no tests, or stops at a usage error, the plugin deletes everything in its base directory right away instead of holding it in memory. Before pytest 9.1 the empty directory itself stays until the process exits and pytest prunes it, so a session starting in the meantime cannot take its number and lose its lock to pytest's exit handler. A failing session keeps everything for inspection.
4. **pytest-xdist.** Each worker owns `<basetemp>/popen-gwN` and cleans up after itself, so a failing run keeps only the directories of workers that saw a failure. A `--basetemp` you pass yourself is never deleted, with or without xdist.

Deleting per test is deliberately not offered: pytest would then reuse the freed directory names, and caches keyed by path would hand the next test the previous one's state.

## When it stays off

The plugin leaves the temp root alone, and says why in the report header, when any of these holds:

| Condition | Header |
| --- | --- |
| Not running on Linux | `shm: off, not Linux` |
| `TMPDIR`, `TEMP`, or `TMP` is exported | `shm: off, TMPDIR is exported`, naming the first one set |
| `--basetemp` or `PYTEST_DEBUG_TEMPROOT` puts pytest's base directory outside `/dev/shm` | `shm: off, --basetemp is outside /dev/shm` |
| pytest's `tmpdir` plugin is disabled (`-p no:tmpdir`) | `shm: off, pytest's tmpdir plugin is disabled` |
| `/dev/shm` is missing, or not writable and searchable | `shm: off, /dev/shm is missing or not writable` |
| `/dev/shm` is mounted `noexec` (Docker's default), which would break tests that run scripts they write | `shm: off, /dev/shm is mounted noexec` |
| `/dev/shm` has less free space than `shm_min_free_gib` (Docker's default is 64 MiB) | `shm: off, /dev/shm has 0.1 GiB free, below shm_min_free_gib = 1` |

To turn it off explicitly, export `TMPDIR` to the directory you want, or pass `-o shm_min_free_gib=inf`.
`-p no:shm` works too, but pytest then warns about the unknown `shm_min_free_gib` option if you configured it, and `--strict-config` makes that an error.

If you export `TMPDIR=/dev/shm` yourself, the plugin still contains and cleans up temporary files, as long as pytest's base directory is on `/dev/shm` too.

## Configuration

One ini option sets how much free space `/dev/shm` needs before the plugin uses it:

```toml
[tool.pytest.ini_options]
shm_min_free_gib = 4
```

The default is `1`.
Set it above your suite's peak usage, which you can watch with `df -h /dev/shm` during a run.
Override it for one run with `-o shm_min_free_gib=8`.

## Caveats

- **Only output during the session is contained.** Temporary files created before the session starts (while the initial `conftest.py` files are imported, in `pytest_configure`, or in other plugins' `pytest_sessionstart` hooks) or after it ends (`pytest_terminal_summary`, `pytest_unconfigure`) land directly in `/dev/shm` and stay there until reboot. Create them in fixtures, or remove them yourself.
- **Caches under the temp root become per-session.** A library that caches downloads under `tempfile.gettempdir()` sees the contained directory, which the plugin frees after the session, so it downloads again every session. If your suite uses such a library, point its cache at a stable directory in your root `conftest.py`, where `tempfile.gettempdir()` is still `/dev/shm`. Which environment variable to set depends on the library. For example, [tiktoken](https://github.com/openai/tiktoken) reads `TIKTOKEN_CACHE_DIR`, falling back to `DATA_GYM_CACHE_DIR`:

  ```python
  # conftest.py at the repository root (tiktoken shown as an example)
  import os
  import tempfile
  from pathlib import Path

  if "TIKTOKEN_CACHE_DIR" not in os.environ and "DATA_GYM_CACHE_DIR" not in os.environ:
      os.environ["TIKTOKEN_CACHE_DIR"] = str(Path(tempfile.gettempdir()) / "data-gym-cache")
  ```

- **Temp files live on another filesystem.** `os.rename` or `os.replace` from a temporary file into your project fails with `EXDEV`, as it already does wherever `/tmp` is tmpfs.
- **Paths get longer.** `/dev/shm/pytest-of-<user>/pytest-N/popen-gwN/shm-tmp/tmpXXXXXXXX` is much longer than `/tmp/tmpXXXXXXXX`, which matters for the 107-byte limit on `AF_UNIX` socket paths.
- **Files use RAM.** Everything a session writes counts against memory until the session ends. Base directories of failing sessions stay until the machine reboots or later failing sessions push them out of pytest's retention of three numbered directories; a passing session leaves at most an empty directory.
- **Plugin autoloading.** With `PYTEST_DISABLE_PLUGIN_AUTOLOAD` set, pass `-p shm` to load the plugin.

## Development

```bash
just install  # uv sync --dev
just test     # uv run pytest -n auto
just lint     # ruff, mypy, ty
```

The tests run real pytest sessions in subprocesses with `pytester` and inspect what they leave behind on `/dev/shm`.

## License

MIT
