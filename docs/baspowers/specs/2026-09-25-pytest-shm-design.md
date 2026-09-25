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

At `pytest_load_initial_conftests` (`tryfirst=True`), before any `conftest.py` is imported, the plugin points `TMPDIR` at `/dev/shm` and resets `tempfile.tempdir` unless one of these holds, checked in this order:

1. `sys.platform != "linux"`.
2. One of `TMPDIR`, `TEMP`, `TMP` is exported.
3. The caller's `--basetemp`, or else `PYTEST_DEBUG_TEMPROOT`, resolves outside `/dev/shm`, so pytest's base directory, and with it the contained files, would stay on disk.
4. `/dev/shm` is not a directory the process may write to and search (`os.W_OK | os.X_OK`).
5. `/dev/shm` is mounted `noexec` (`os.statvfs(...).f_flag & os.ST_NOEXEC`).
6. `/dev/shm` has less than `shm_min_free_gib` GiB free.
7. pytest's `tmpdir` plugin is blocked (`-p no:tmpdir`), so nothing could contain or free the files.

Checks 1-6 live in the public `off_reason(min_free_gib, environ, basetemp=None) -> str | None`.
The first failing check is recorded as the reason the plugin is off.
On switching, the plugin registers a `config.add_cleanup` that removes `TMPDIR` and restores the previous `tempfile.tempdir`, which pytest runs even when the session never configures (for example on a usage error), so in-process callers such as `pytest.main()` get their environment back.

Disabling:

- Export `TMPDIR` (or `TEMP`/`TMP`) to choose a temp root yourself.
- Pass `-o shm_min_free_gib=inf`.
- Pass `-p no:shm`, which makes pytest warn about the then-unknown `shm_min_free_gib` option if the project sets it.

### Containment

A `pytest_sessionstart` new-style wrapper acts after every other `pytest_sessionstart` implementation, so xdist's controller has already started its workers and they inherit `/dev/shm` itself.
It acts whenever `tempfile.gettempdir()` is `/dev/shm`, whether this process switched it or inherited it (xdist workers inherit the controller's environment, and a user may export `TMPDIR=/dev/shm`), and pytest's `tmpdir` plugin has set `config._tmp_path_factory`.
It creates `<basetemp>/shm-tmp` and points `TMPDIR` and `tempfile.tempdir` at it, so bare `tempfile` output from collection on lives and dies with pytest's base directory instead of holding memory until reboot.
`pytest_sessionfinish` points them back at `/dev/shm`.
Temporary files created during conftest import or `pytest_configure` are not contained; the README says so.

### Cleanup

Containment stashes the base directory when pytest chose it (no caller `--basetemp`) and it lies under `/dev/shm`.
`pytest_sessionfinish` (`trylast=True`, after the runner has torn down session fixtures) removes the stashed directory when the session's exit status is 0.
Under xdist each worker owns `<controller basetemp>/popen-gwN`, so a failing run keeps only the directories of workers that saw a failure plus the controller's empty `shm-tmp`; a passing run removes the controller's directory too.
Every xdist worker receives `--basetemp`, so the controller tells each worker through `node.workerinput["shm_owns_basetemp"]` whether the caller chose one, in `pytest_configure_node` (`optionalhook=True`, so the plugin loads without xdist).
A worker without the key treats its base directory as the caller's.

Deleting per test is not offered: pytest then reuses freed numbered names, and caches keyed by path hand the next test the previous one's state.

### Configuration

One ini option, `shm_min_free_gib` (pytest's `float` ini type, default `1.0`), set in `pytest.ini`/`pyproject.toml` or with `-o shm_min_free_gib=4`.
The `float` type (pytest 8.4+) accepts both ini strings and pytest 9's native `[tool.pytest]` TOML numbers, which a `string` option rejects.
The default rejects Docker's 64 MiB `/dev/shm`; suites with a larger peak raise it.

### Report header

`pytest_report_header` prints `shm: temp root /dev/shm` when `tempfile.gettempdir()` is `/dev/shm` at header time, and otherwise `shm: off, <reason>`.

## Known consequences (documented in README)

- Temporary files created during conftest import or `pytest_configure` land directly in `/dev/shm`.
- Libraries that cache under the temp root lose their cache at containment; pin their cache directory at import time (for example `TIKTOKEN_CACHE_DIR`) in a `conftest.py`, where `tempfile.gettempdir()` is still `/dev/shm`.
- Temp files live on another filesystem than the project, so renames into it fail with `EXDEV`.
- Temp paths are longer than `/tmp/tmpXXXX` (`/dev/shm/pytest-of-<user>/pytest-N/popen-gwN/shm-tmp/...`), which matters for the 107-byte `AF_UNIX` socket path limit.
- Everything written counts against RAM until the session ends; failing sessions' directories remain until reboot or until later failing sessions push them out of pytest's retention, since passing sessions reuse the freed number.

## Package layout

- `src/pytest_shm/__init__.py`: version only.
- `src/pytest_shm/plugin.py`: all hooks and `off_reason`.
- `src/pytest_shm/py.typed`.
- Entry point `[project.entry-points.pytest11] shm = "pytest_shm.plugin"`.
- Dependencies: `pytest>=8.4`; Python `>=3.10`.
- The sdist ships only `src`, `tests`, `README.md`, and `LICENSE`.

## Testing

`tests/test_plugin.py` runs inner sessions with `pytester.run(sys.executable, "-m", "pytest", ...)` so pytester does not force `--basetemp`, and in-process sessions where restoring the caller's environment is the behavior under test.
Each subprocess run gets an environment without `TMPDIR`/`TEMP`/`TMP` and a fresh `PYTEST_DEBUG_TEMPROOT` under `/dev/shm`, so pytest-owned base directories are isolated and inspectable.
Active-path tests skip unless `off_reason(1, {})` returns `None`; a test outside Linux checks the header reports the plugin off.

Cases:

- A conftest sees `/dev/shm` at import time, and with no `PYTEST_DEBUG_TEMPROOT` pytest derives its base directory from the switched temp root.
- Module-level and in-test `tempfile.mkdtemp()` output lands in `<basetemp>/shm-tmp`.
- A passing run leaves no `pytest-N` directory; a failing run keeps it, including contained `tempfile` output.
- An explicit `--basetemp` survives a passing run, with and without xdist, and so does a pytest-owned base directory outside `/dev/shm`.
- With xdist, a passing run leaves nothing, and with `--dist each -n 2` and a test failing only on `gw1`, only `popen-gw1` and the controller's `shm-tmp` remain.
- An exported `TMPDIR`, a `--basetemp` or `PYTEST_DEBUG_TEMPROOT` outside `/dev/shm`, `-p no:tmpdir`, `-p no:shm`, and a too-high threshold (via `-o` or a native `[tool.pytest]` number) each leave the temp root alone, and the header says why.
- In-process sessions restore the caller's `TMPDIR` and `tempfile.tempdir`, including after a usage error, and hand back an exported `TMPDIR=/dev/shm`.
- `off_reason` refuses a `noexec` mount (unit test with a patched `os.statvfs`).
- The plugin loads with `-p no:xdist`.

CI runs the suite on ubuntu and macOS across Python 3.10-3.14, plus one job on Python 3.10 with pytest 8.4.0, the declared floor.

## Repository scaffolding

Follows `basnijholt/compose-farm`: hatchling + hatch-vcs with a generated `_version.py`, ruff `select = ["ALL"]`, mypy strict and ty, pre-commit run by prek in CI, PyPI trusted publishing on release, release-drafter, renovate, the TOC generator, a justfile, and `CLAUDE.md` with `AGENTS.md`/`GEMINI.md` symlinks.
The release-drafter and TOC jobs declare `contents: write` because new personal repositories default to a read-only `GITHUB_TOKEN`.
Not carried over because they do not apply: docs site, Docker files, the README command runner, `.prompts`, and coverage upload (the tests run the plugin in subprocesses).

## MindRoom follow-through

In PR #2344, after the first release: add `pytest-shm` to the dev dependencies, set `shm_min_free_gib = 4`, delete the plugin logic from the root `conftest.py` while keeping the `TERM` pin and the tiktoken cache pin, and point `docs/dev/TESTING.md` at the plugin.
