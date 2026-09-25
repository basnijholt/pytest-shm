# pytest-shm design

## Goal

Extract the tmpfs temp-root logic from MindRoom's root `conftest.py` (PR mindroom-ai/mindroom#2344) into a small, tested, reusable pytest plugin published as `pytest-shm` from `github.com/basnijholt/pytest-shm`.
MindRoom then depends on the package instead of carrying the logic.

## Why

Suites that fsync heavily (SQLite, atomic file publication) spend most of their time waiting on the disk.
tmpfs completes fsync without touching a device.
In MindRoom's suite, summed test time on a 32-worker NVMe machine fell from 5236 s to 1426 s, and the GitHub Actions test step from about 16 to 12-15 minutes.
Nothing in the logic is MindRoom-specific, and inside MindRoom it had no automated tests.

## Behavior

### Activation

At `pytest_load_initial_conftests` (`tryfirst=True`), before any `conftest.py` is imported, the plugin points `TMPDIR` at `/dev/shm` and resets `tempfile.tempdir` when all of these hold, checked in this order:

1. `sys.platform == "linux"`.
2. None of `TMPDIR`, `TEMP`, `TMP` is exported.
3. `/dev/shm` is a directory the process may write to and search (`os.W_OK | os.X_OK`).
4. `/dev/shm` is not mounted `noexec` (`os.statvfs(...).f_flag & os.ST_NOEXEC`).
5. `/dev/shm` has at least `shm_min_free_gib` GiB free.

The first failing check is recorded as the reason the plugin is off.
The plugin records whether it switched, so `pytest_unconfigure` can restore the original environment (remove `TMPDIR`, reset `tempfile.tempdir`) for in-process runs such as `pytest.main()`.

Disabling:

- Export `TMPDIR` (or `TEMP`/`TMP`) to choose a temp root yourself.
- Pass `-p no:shm`.

### Containment

A session-scoped autouse fixture runs whenever `tempfile.gettempdir()` is `/dev/shm`, whether this process switched it or inherited it (xdist workers inherit the controller's environment, and a user may export `TMPDIR=/dev/shm`).
It creates `<basetemp>/tmp`, points `TMPDIR` and `tempfile.tempdir` at it, and on teardown points them back at `/dev/shm`.
Bare `tempfile` output then lives and dies with pytest's base directory instead of holding memory until reboot.

### Cleanup

The fixture stashes the base directory when pytest chose it (no caller `--basetemp`) and it lies under `/dev/shm`.
`pytest_sessionfinish` removes the stashed directory when the session's exit status is 0.
Under xdist each worker owns `<controller basetemp>/popen-gwN`, so a failing run keeps only the directories of workers that saw a failure.
Every xdist worker receives `--basetemp`, so the controller tells each worker through `node.workerinput["shm_owns_basetemp"]` whether the caller chose one, in `pytest_configure_node` (`optionalhook=True`, so the plugin loads without xdist).
The controller's own `pytest-N` directory stays behind, empty after a passing run, and pytest's usual retention of three numbered directories prunes it.

Deleting per test is not offered: pytest then reuses freed numbered names, and caches keyed by path hand the next test the previous one's state.

### Configuration

One ini option, `shm_min_free_gib` (pytest's `float` ini type, default `1.0`), set in `pytest.ini`/`pyproject.toml` or with `-o shm_min_free_gib=4`.
The `float` type (pytest 8.4+) accepts both ini strings and pytest 9's native `[tool.pytest]` TOML numbers, which a `string` option rejects.
The default rejects Docker's 64 MiB `/dev/shm`; suites with a larger peak raise it.

### Report header

`pytest_report_header` prints `shm: temp root /dev/shm` when `tempfile.gettempdir()` is `/dev/shm` at header time, and otherwise `shm: off, <reason>`.

## Known consequences (documented in README)

- Libraries that cache under the temp root lose their cache at containment; pin their cache directory at import time (for example `TIKTOKEN_CACHE_DIR`) in a `conftest.py`, where `tempfile.gettempdir()` is still `/dev/shm`.
- Temp paths are longer than `/tmp/tmpXXXX` (`/dev/shm/pytest-of-<user>/pytest-N/popen-gwN/tmp/...`), which matters for the 107-byte `AF_UNIX` socket path limit.
- Everything written counts against RAM until the session ends; failing workers' directories remain until pytest's retention prunes them or the machine reboots.

## Package layout

- `src/pytest_shm/__init__.py`: version only.
- `src/pytest_shm/plugin.py`: all hooks, the fixture, and `unavailable_reason(min_free_gib) -> str | None`.
- `src/pytest_shm/py.typed`.
- Entry point `[project.entry-points.pytest11] shm = "pytest_shm.plugin"`.
- Dependencies: `pytest>=8.4`; Python `>=3.10`.

## Testing

`tests/test_plugin.py` runs inner sessions with `pytester.run(sys.executable, "-m", "pytest", ...)` so pytester does not force `--basetemp`.
Each inner run gets an environment without `TMPDIR`/`TEMP`/`TMP` and a fresh `PYTEST_DEBUG_TEMPROOT` under `/dev/shm`, so pytest-owned base directories are isolated and inspectable.
Active-path tests skip unless `unavailable_reason` returns `None`; a macOS test checks the header reports the plugin off.

Cases:

- A test sees `tempfile.gettempdir() == <basetemp>/tmp` and `tmp_path` under `/dev/shm`.
- A passing run leaves no `pytest-N` directory; a failing run keeps it, including contained `tempfile` output.
- An explicit `--basetemp` survives a passing run, with and without xdist.
- With xdist `--dist each -n 2` and a test failing only on `gw1`, `popen-gw0` is removed and `popen-gw1` is kept.
- An exported `TMPDIR` wins, and the header says why the plugin is off.
- `-o shm_min_free_gib=1e9`, or the same threshold as a native `[tool.pytest]` TOML number, leaves the temp root alone and reports the free space.
- The plugin loads with `-p no:xdist`.
- `-p no:shm` leaves the temp root alone.
- An in-process run restores `TMPDIR` and `tempfile.tempdir`.
- `unavailable_reason` refuses a `noexec` mount (unit test with a patched `os.statvfs`).

## Repository scaffolding

Follows `basnijholt/compose-farm`: hatchling + hatch-vcs with a generated `_version.py`, ruff `select = ["ALL"]`, mypy strict and ty, pre-commit run by prek in CI, a CI matrix of ubuntu and macOS across Python 3.10-3.14, PyPI trusted publishing on release, release-drafter, renovate, the TOC generator, a justfile, and `CLAUDE.md` with `AGENTS.md`/`GEMINI.md` symlinks.
Not carried over because they do not apply: docs site, Docker files, the README command runner, `.prompts`.

## MindRoom follow-through

In PR #2344, after the first release: add `pytest-shm` to the dev dependencies, set `shm_min_free_gib = 4`, delete the plugin logic from the root `conftest.py` while keeping the `TERM` pin and an unconditional tiktoken cache pin, and point `docs/dev/TESTING.md` at the plugin.
