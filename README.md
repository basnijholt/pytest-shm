# pytest-shm

[![PyPI](https://img.shields.io/pypi/v/pytest-shm)](https://pypi.org/project/pytest-shm/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-shm)](https://pypi.org/project/pytest-shm/)
[![License](https://img.shields.io/github/license/basnijholt/pytest-shm)](LICENSE)
[![CI](https://github.com/basnijholt/pytest-shm/actions/workflows/ci.yml/badge.svg)](https://github.com/basnijholt/pytest-shm/actions/workflows/ci.yml)

A pytest plugin that puts your test suite's temporary files on the `/dev/shm` tmpfs, so tests that fsync stop waiting on the disk.

> [!NOTE]
> Install it and run pytest.
> On Linux it moves the temp root to `/dev/shm` when that is safe, keeps stray `tempfile` output inside pytest's base directory, and frees that directory when the session passes.
> Everywhere else, and whenever you export `TMPDIR`, it does nothing.

## Table of Contents

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Why

SQLite commits, atomic file replacement, and anything else that promises durability call `fsync`, and on a real disk each call waits for the device.
A suite that exercises durable storage can spend most of its time there.
tmpfs lives in memory, so `fsync` returns immediately.

In [MindRoom](https://github.com/mindroom-ai/mindroom)'s suite of about 26,000 tests, summed test time on a 32-worker NVMe machine fell from 5236 s to 1426 s, and the GitHub Actions test step fell from about 16 to 12-15 minutes.

No test can observe the difference.
Durability tests simulate a crashed process, and a crashed process never needed its writes to leave the page cache.

## Installation

```bash
uv add --dev pytest-shm
# or
pip install pytest-shm
```

It needs Python 3.10+ and pytest 8.4+, and pytest loads it automatically.
The report header tells you whether it is active:

```text
shm: temp root /dev/shm
```

or why it is not:

```text
shm: off, TMPDIR is exported
```

## How it works

1. **Temp root.** Before any `conftest.py` is imported, the plugin sets `TMPDIR=/dev/shm`, so `tmp_path`, `tmp_path_factory`, and every `tempfile` call land in memory.
2. **Containment.** Tests and the code they drive often call `tempfile.mkdtemp()` without removing the result. On disk that clutters `/tmp`; on tmpfs it would hold memory until reboot. For the duration of the session, the plugin points `TMPDIR` at `<basetemp>/tmp`, so that output lives and dies with pytest's own base directory.
3. **Cleanup.** pytest keeps the last three sessions' base directories. When a session passes, the plugin deletes its base directory right away instead of holding it in memory. A failing session keeps everything for inspection.
4. **pytest-xdist.** Each worker owns `<basetemp>/popen-gwN` and cleans up after itself, so a failing run keeps only the directories of workers that saw a failure. A `--basetemp` you pass yourself is never deleted, with or without xdist.

Deleting per test is deliberately not offered: pytest would then reuse the freed directory names, and caches keyed by path would hand the next test the previous one's state.

## When it stays off

The plugin leaves the temp root alone, and says why in the report header, when any of these holds:

| Condition | Header |
| --- | --- |
| Not running on Linux | `shm: off, not Linux` |
| `TMPDIR`, `TEMP`, or `TMP` is exported | `shm: off, TMPDIR is exported` |
| `/dev/shm` is missing, or not writable and searchable | `shm: off, /dev/shm is missing or not writable` |
| `/dev/shm` is mounted `noexec` (Docker's default), which would break tests that run scripts they write | `shm: off, /dev/shm is mounted noexec` |
| `/dev/shm` has less free space than `shm_min_free_gib` (Docker's default is 64 MiB) | `shm: off, /dev/shm has 0.1 GiB free, below shm_min_free_gib = 1` |

To turn it off explicitly, export `TMPDIR` to the directory you want, or pass `-p no:shm`.

If you export `TMPDIR=/dev/shm` yourself, the plugin still contains and cleans up temporary files.

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

- **Caches under the temp root become per-session.** Libraries that cache downloads under `tempfile.gettempdir()` see the contained directory, which the plugin frees after the session. Pin such caches in your root `conftest.py`, where `tempfile.gettempdir()` is still `/dev/shm`, for example `os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(tempfile.gettempdir()) / "data-gym-cache"))` for tiktoken.
- **Paths get longer.** `/dev/shm/pytest-of-<user>/pytest-N/popen-gwN/tmp/tmpXXXXXXXX` is much longer than `/tmp/tmpXXXXXXXX`, which matters for the 107-byte limit on `AF_UNIX` socket paths.
- **Files use RAM.** Everything a session writes counts against memory until the session ends. Base directories of failing sessions stay until pytest's retention prunes them or the machine reboots.
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
