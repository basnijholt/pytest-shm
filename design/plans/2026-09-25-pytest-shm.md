# pytest-shm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use baspowers:subagent-driven-development (recommended) or baspowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish-ready `pytest-shm` plugin that moves pytest's temporary files to `/dev/shm`, contains bare `tempfile` output, and frees passing sessions' directories.

**Architecture:** One module, `pytest_shm.plugin`, registered through the `pytest11` entry point `shm`. A `tryfirst` `pytest_load_initial_conftests` hook switches `TMPDIR` before any `conftest.py` loads; a session fixture contains bare `tempfile` output under the base directory; a `trylast` `pytest_sessionfinish` deletes pytest-owned base directories after a passing session, with xdist workers told by the controller whether the caller chose `--basetemp`.

**Tech Stack:** Python >=3.10, pytest >=7, pytest-xdist (optional, dev), hatchling + hatch-vcs, uv, ruff, mypy, ty, prek/pre-commit, GitHub Actions.

**Spec:** `docs/baspowers/specs/2026-09-25-pytest-shm-design.md`

## Global Constraints

- Distribution name `pytest-shm`, import package `pytest_shm`, entry point `shm = "pytest_shm.plugin"`.
- `requires-python = ">=3.10"`, `dependencies = ["pytest>=7"]`.
- Ini option `shm_min_free_gib`, default `"1"`, parsed with `float()`.
- xdist worker input key `shm_owns_basetemp`.
- Report header text: `shm: temp root /dev/shm` or `shm: off, <reason>`.
- Off reasons, exact text: `not Linux`, `<NAME> is exported`, `/dev/shm is missing or not writable`, `/dev/shm is mounted noexec`, `/dev/shm has {free:.1f} GiB free, below shm_min_free_gib = {min:g}`.
- Scaffolding mirrors `basnijholt/compose-farm`; commits use plain English messages with no AI attribution trailers.
- Repository lives at `/work/repos/pytest-shm`, remote `github.com/basnijholt/pytest-shm`.

---

### Task 1: Package scaffolding with a registered, empty plugin

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `.python-version`, `.envrc`, `justfile`, `.pre-commit-config.yaml`
- Create: `src/pytest_shm/__init__.py`, `src/pytest_shm/plugin.py`, `src/pytest_shm/py.typed`
- Test: `tests/conftest.py`, `tests/test_plugin.py`

**Interfaces:**
- Produces: importable `pytest_shm.plugin` loaded by pytest as plugin `shm`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "pytest-shm"
dynamic = ["version"]
description = "Put pytest's temporary files on the /dev/shm tmpfs so fsync-heavy suites stop waiting on the disk"
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
authors = [
    { name = "Bas Nijholt", email = "bas@nijho.lt" }
]
maintainers = [
    { name = "Bas Nijholt", email = "bas@nijho.lt" }
]
requires-python = ">=3.10"
keywords = ["pytest", "tmpfs", "shm", "fsync", "tempfile", "xdist", "testing", "performance"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Framework :: Pytest",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Software Development :: Testing",
    "Typing :: Typed",
]
dependencies = ["pytest>=7"]

[project.urls]
Homepage = "https://github.com/basnijholt/pytest-shm"
Repository = "https://github.com/basnijholt/pytest-shm"
Documentation = "https://github.com/basnijholt/pytest-shm#readme"
Issues = "https://github.com/basnijholt/pytest-shm/issues"
Changelog = "https://github.com/basnijholt/pytest-shm/releases"

[project.entry-points.pytest11]
shm = "pytest_shm.plugin"

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "src/pytest_shm/_version.py"

[tool.hatch.build.targets.wheel]
packages = ["src/pytest_shm"]

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["ALL"]
ignore = [
    "D203",    # incompatible with D211
    "D213",    # incompatible with D212
    "E501",    # formatter handles line length
    "COM812",  # avoid formatter conflicts
    "ISC001",  # avoid formatter conflicts
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101", "S108", "PLR2004"]

[tool.mypy]
python_version = "3.10"
strict = true

[[tool.mypy.overrides]]
module = "pytest_shm._version"
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ty.environment]
python-version = "3.10"

[tool.ty.src]
exclude = ["src/pytest_shm/_version.py"]

[dependency-groups]
dev = [
    "mypy>=1.19.0",
    "pre-commit>=4.5.0",
    "pytest>=9.0.2",
    "pytest-xdist>=3.8.0",
    "ruff>=0.16.0",
    "ty>=0.0.1a13",
]
```

- [ ] **Step 2: Write the small project files**

`.gitignore`:

```gitignore
# Python
__pycache__/
src/pytest_shm/_version.py
*.py[cod]
build/
dist/
*.egg-info/

# Virtual environments
.venv/

# IDE
.idea/
.vscode/
*.swp
.DS_Store

# Tools
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

`LICENSE`: the MIT license text from compose-farm with `Copyright (c) 2026 Bas Nijholt`.

`.python-version`: `3.14`. `.envrc`: `source .venv/bin/activate`.

`justfile`:

```just
# pytest-shm Development Commands
# Run `just` to see available commands

# Default: list available commands
default:
    @just --list

# Install development dependencies
install:
    uv sync --dev

# Run all tests (parallel)
test:
    uv run pytest -n auto

# Lint, format, and type check
lint:
    uv run ruff check --fix .
    uv run ruff format .
    uv run mypy src tests
    uv run ty check

# Clean up build artifacts and caches
clean:
    rm -rf .pytest_cache .mypy_cache .ruff_cache dist build
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: debug-statements

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.9
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format

  - repo: local
    hooks:
      - id: mypy
        name: mypy (type checker)
        entry: uv run mypy src tests
        language: system
        types: [python]
        pass_filenames: false

      - id: ty
        name: ty (type checker)
        entry: uv run ty check
        language: system
        types: [python]
        pass_filenames: false
```

- [ ] **Step 3: Write the package skeleton**

`src/pytest_shm/__init__.py`:

```python
"""Put pytest's temporary files on the `/dev/shm` tmpfs."""

try:
    from pytest_shm._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0"
    __version_tuple__ = (0, 0, 0)

__all__ = ["__version__", "__version_tuple__"]
```

`src/pytest_shm/plugin.py`:

```python
"""Run pytest with its temporary files on the `/dev/shm` tmpfs."""
```

`src/pytest_shm/py.typed`: empty.

- [ ] **Step 4: Write the registration test**

`tests/conftest.py`:

```python
"""Shared test configuration."""

pytest_plugins = ["pytester"]
```

`tests/test_plugin.py`:

```python
"""Behavior of the pytest-shm plugin, observed through real pytest sessions."""

from __future__ import annotations

import pytest


def test_plugin_is_registered(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("shm")
```

- [ ] **Step 5: Install and run**

Run: `git init` already done; `uv sync --dev && uv run pytest -q`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore LICENSE .python-version .envrc justfile .pre-commit-config.yaml src tests uv.lock
git commit -m "Add package scaffolding and register the shm plugin"
```

### Task 2: Move the temp root to `/dev/shm`, report it, and restore it

**Files:**
- Modify: `src/pytest_shm/plugin.py`
- Test: `tests/test_plugin.py`

**Interfaces:**
- Produces: `SHM: Path`, `off_reason(min_free_gib: float, environ: Mapping[str, str]) -> str | None`, hooks `pytest_addoption`, `pytest_load_initial_conftests`, `pytest_report_header`, `pytest_unconfigure`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugin.py` (merge imports at the top):

```python
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from pytest_shm.plugin import SHM, off_reason

if TYPE_CHECKING:
    from collections.abc import Iterator

_SHM_OFF = off_reason(1, {})
needs_shm = pytest.mark.skipif(_SHM_OFF is not None, reason=f"{SHM} is unusable: {_SHM_OFF}")

_TEMP_ROOT_IS_NOT_SHM = """
import tempfile

def test_temp_root():
    assert not tempfile.gettempdir().startswith("/dev/shm")
"""


@pytest.fixture
def temproot(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Give inner sessions no exported temp root and their own pytest temp root on /dev/shm.

    Depending on `pytester` makes this override the `PYTEST_DEBUG_TEMPROOT` it sets.
    """
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(name, raising=False)
    root = Path(tempfile.mkdtemp(dir=SHM, prefix="pytest-shm-test-"))
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(root))
    yield root
    shutil.rmtree(root)


def run_pytest(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run pytest in a subprocess without the `--basetemp` that `runpytest_subprocess` forces."""
    return pytester.run(sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args, timeout=60)


@needs_shm
def test_moves_the_temp_root_to_shm(pytester: pytest.Pytester, temproot: Path) -> None:
    pytester.makepyfile(
        """
        import tempfile
        from pathlib import Path

        def test_temp_root(tmp_path):
            assert Path(tempfile.gettempdir()).is_relative_to("/dev/shm")
            assert tmp_path.is_relative_to(Path("/dev/shm").resolve())
        """
    )
    result = run_pytest(pytester)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: temp root /dev/shm"])


@needs_shm
def test_exported_temp_root_wins(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = pytester.mkdir("chosen")
    monkeypatch.setenv("TMPDIR", str(chosen))
    pytester.makepyfile(
        f"""
        import tempfile

        def test_temp_root():
            assert tempfile.gettempdir() == {str(chosen)!r}
        """
    )
    result = run_pytest(pytester)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: off, TMPDIR is exported"])


@needs_shm
def test_too_little_free_space_leaves_the_temp_root_alone(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile(_TEMP_ROOT_IS_NOT_SHM)
    result = run_pytest(pytester, "-o", "shm_min_free_gib=1e9")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        ["shm: off, /dev/shm has * GiB free, below shm_min_free_gib = 1e+09"]
    )


@needs_shm
def test_disabled_plugin_leaves_the_temp_root_alone(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile(_TEMP_ROOT_IS_NOT_SHM)
    result = run_pytest(pytester, "-p", "no:shm")
    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("shm:*")


@needs_shm
def test_in_process_session_restores_the_environment(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", None)
    pytester.makepyfile("def test_pass():\n    pass\n")
    result = pytester.runpytest_inprocess()
    result.assert_outcomes(passed=1)
    assert "TMPDIR" not in os.environ
    assert tempfile.tempdir is None


@needs_shm
def test_noexec_shm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "statvfs", lambda _path: SimpleNamespace(f_flag=os.ST_NOEXEC))
    assert off_reason(0, {}) == "/dev/shm is mounted noexec"


@pytest.mark.skipif(sys.platform == "linux", reason="checks the report outside Linux")
def test_stays_off_outside_linux(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_pass():\n    pass\n")
    result = run_pytest(pytester)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: off, not Linux"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q`
Expected: collection error `ImportError: cannot import name 'SHM' from 'pytest_shm.plugin'`.

- [ ] **Step 3: Implement**

Replace `src/pytest_shm/plugin.py` with:

```python
"""Run pytest with its temporary files on the `/dev/shm` tmpfs."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

SHM = Path("/dev/shm")  # noqa: S108
_TEMP_ROOT_VARIABLES = ("TMPDIR", "TEMP", "TMP")
_MIN_FREE_INI = "shm_min_free_gib"
_SWITCHED = pytest.StashKey[bool]()
_OFF_REASON = pytest.StashKey[str]()


def off_reason(min_free_gib: float, environ: Mapping[str, str]) -> str | None:
    """Return why the temp root should stay where it is, or `None` to move it to `/dev/shm`."""
    if sys.platform != "linux":
        return "not Linux"
    for name in _TEMP_ROOT_VARIABLES:
        if name in environ:
            return f"{name} is exported"
    if not SHM.is_dir() or not os.access(SHM, os.W_OK | os.X_OK):
        return f"{SHM} is missing or not writable"
    if os.statvfs(SHM).f_flag & os.ST_NOEXEC:
        return f"{SHM} is mounted noexec"
    free_gib = shutil.disk_usage(SHM).free / 2**30
    if free_gib < min_free_gib:
        return f"{SHM} has {free_gib:.1f} GiB free, below {_MIN_FREE_INI} = {min_free_gib:g}"
    return None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the free-space threshold."""
    parser.addini(
        _MIN_FREE_INI,
        f"Minimum free GiB {SHM} needs before temporary files move there (default: 1).",
        default="1",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config: pytest.Config) -> None:
    """Point the temp root at `/dev/shm` before any `conftest.py` can read it."""
    reason = off_reason(float(early_config.getini(_MIN_FREE_INI)), os.environ)
    if reason is not None:
        early_config.stash[_OFF_REASON] = reason
        return
    os.environ["TMPDIR"] = str(SHM)
    tempfile.tempdir = None
    early_config.stash[_SWITCHED] = True


def pytest_report_header(config: pytest.Config) -> str:
    """Say where temporary files go, or why they stay put."""
    temp_root = tempfile.gettempdir()
    if Path(temp_root) == SHM:
        return f"shm: temp root {SHM}"
    return f"shm: off, {config.stash.get(_OFF_REASON, f'temp root is {temp_root}')}"


def pytest_unconfigure(config: pytest.Config) -> None:
    """Hand an in-process caller back the environment it started with."""
    if config.stash.get(_SWITCHED, False):
        os.environ.pop("TMPDIR", None)
        tempfile.tempdir = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass on Linux (the non-Linux test skips).

- [ ] **Step 5: Commit**

```bash
git add src/pytest_shm/plugin.py tests/test_plugin.py
git commit -m "Move the temp root to /dev/shm when it can hold the session"
```

### Task 3: Contain bare `tempfile` output and free passing sessions' directories

**Files:**
- Modify: `src/pytest_shm/plugin.py`
- Test: `tests/test_plugin.py`

**Interfaces:**
- Consumes: `SHM`, `run_pytest`, `temproot`, `needs_shm` from Task 2.
- Produces: fixture `_shm_contain_temporary_files`, hooks `pytest_configure_node`, `pytest_sessionfinish`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugin.py`:

```python
@needs_shm
def test_bare_tempfile_output_lands_in_the_base_directory(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile(
        """
        import os
        import tempfile
        from pathlib import Path

        def test_contained(tmp_path_factory):
            contained = tmp_path_factory.getbasetemp() / "tmp"
            assert tempfile.gettempdir() == os.environ["TMPDIR"] == str(contained)
            assert Path(tempfile.mkdtemp()).parent == contained
        """
    )
    run_pytest(pytester).assert_outcomes(passed=1)


@needs_shm
@pytest.mark.parametrize(
    ("statement", "outcome"),
    [("pass", "passed"), ("assert False", "failed")],
    ids=["passing", "failing"],
)
def test_only_a_failing_session_keeps_its_base_directory(
    pytester: pytest.Pytester, temproot: Path, statement: str, outcome: str
) -> None:
    pytester.makepyfile(
        f"""
        import tempfile
        from pathlib import Path

        def test_write():
            Path(tempfile.mkdtemp(), "state").write_text("x")
            {statement}
        """
    )
    run_pytest(pytester).assert_outcomes(**{outcome: 1})
    numbered = list(temproot.glob("pytest-of-*/pytest-[0-9]*"))
    if outcome == "passed":
        assert numbered == []
    else:
        (basetemp,) = numbered
        assert list(basetemp.glob("tmp/tmp*/state"))


@needs_shm
@pytest.mark.parametrize("workers", [(), ("-n", "2")], ids=["serial", "xdist"])
def test_explicit_basetemp_survives_a_passing_session(
    pytester: pytest.Pytester, temproot: Path, workers: tuple[str, ...]
) -> None:
    pytester.makepyfile("def test_write(tmp_path):\n    (tmp_path / 'kept').write_text('x')\n")
    basetemp = temproot / "chosen"
    run_pytest(pytester, f"--basetemp={basetemp}", *workers).assert_outcomes(passed=1)
    assert list(basetemp.rglob("kept"))


@needs_shm
def test_xdist_keeps_only_the_failing_workers_directory(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile(
        """
        import os

        def test_fails_on_gw1():
            assert os.environ["PYTEST_XDIST_WORKER"] != "gw1"
        """
    )
    run_pytest(pytester, "-n", "2", "--dist", "each").assert_outcomes(passed=1, failed=1)
    (basetemp,) = temproot.glob("pytest-of-*/pytest-[0-9]*")
    assert [path.name for path in basetemp.iterdir()] == ["popen-gw1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q -k "base_directory or basetemp or failing_workers"`
Expected: `test_bare_tempfile_output_lands_in_the_base_directory`, the `passing` case, and the xdist per-worker test FAIL; the explicit-basetemp and `failing` cases already pass (nothing deletes yet).

- [ ] **Step 3: Implement**

In `src/pytest_shm/plugin.py`, extend the `TYPE_CHECKING` block and constants:

```python
if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from xdist.workermanage import WorkerController
```

```python
_OWNS_BASETEMP_KEY = "shm_owns_basetemp"
_OWNED_BASETEMP = pytest.StashKey[Path]()
```

Append:

```python
def _pytest_chose_basetemp(config: pytest.Config) -> bool:
    """Tell whether pytest picked the base directory rather than the caller."""
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        return bool(workerinput[_OWNS_BASETEMP_KEY])
    return config.option.basetemp is None


@pytest.fixture(scope="session", autouse=True)
def _shm_contain_temporary_files(
    pytestconfig: pytest.Config,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Keep bare `tempfile` output inside pytest's base directory on `/dev/shm`.

    Tests and the code they drive often call `tempfile.mkdtemp()` without removing
    the result. On disk that only clutters `/tmp`, but on tmpfs it would hold memory
    until reboot, so it joins the `tmp_path` directories that `pytest_sessionfinish`
    frees.

    xdist workers inherit `TMPDIR` from the controller, so this checks where the temp
    root is rather than whether this process moved it.
    """
    if Path(tempfile.gettempdir()) != SHM:
        yield
        return
    basetemp = tmp_path_factory.getbasetemp()
    if _pytest_chose_basetemp(pytestconfig) and basetemp.is_relative_to(SHM.resolve()):
        pytestconfig.stash[_OWNED_BASETEMP] = basetemp
    contained = basetemp / "tmp"
    contained.mkdir()
    os.environ["TMPDIR"] = str(contained)
    tempfile.tempdir = str(contained)
    yield
    os.environ["TMPDIR"] = str(SHM)
    tempfile.tempdir = None


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: WorkerController) -> None:
    """Tell each xdist worker whether its base directory is pytest's own or the caller's.

    xdist hands every worker its directory as `--basetemp`, so only the controller
    still knows whether the caller chose one, which must outlive a passing session.
    """
    node.workerinput[_OWNS_BASETEMP_KEY] = node.config.option.basetemp is None


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """Free a passing session's base directory instead of holding it in memory.

    pytest keeps the last three sessions' directories, which on tmpfs pins memory
    until they are pruned. Each xdist worker owns its own base directory, so a
    failing session keeps only the workers that saw a failure. Deleting per test is
    not an option: pytest then reuses the freed names, and caches keyed by path hand
    the next test the previous one's state.
    """
    basetemp = session.config.stash.get(_OWNED_BASETEMP, None)
    if basetemp is not None and exitstatus == 0:
        shutil.rmtree(basetemp, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q -n auto`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pytest_shm/plugin.py tests/test_plugin.py
git commit -m "Contain bare tempfile output and free passing sessions' directories"
```

### Task 4: README, agent guide, and GitHub automation

**Files:**
- Create: `README.md`, `CLAUDE.md`, `AGENTS.md -> CLAUDE.md`, `GEMINI.md -> CLAUDE.md`
- Create: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/workflows/release-drafter.yml`, `.github/workflows/toc.yaml`, `.github/release-drafter.yml`, `.github/renovate.json`

**Interfaces:**
- Consumes: behavior and option names from Tasks 2-3.

- [ ] **Step 1: Write `README.md`**

Sections, one sentence per line: title with PyPI/Python/License badges, one-line summary, `> [!NOTE]` with the fsync rationale, TOC markers (`<!-- START doctoc generated TOC please keep comment here to allow auto update -->` / `<!-- END doctoc generated TOC please keep comment here to allow auto update -->`), Why (MindRoom numbers from the spec), Installation (`uv add --dev pytest-shm`, `pip install pytest-shm`), How it works (activation, containment, cleanup, xdist), When it stays off (table of the five reasons plus `-p no:shm`), Configuration (`shm_min_free_gib` with a `pyproject.toml` example and `-o`), Caveats (per-run caches with the tiktoken example, longer paths vs the 107-byte `AF_UNIX` limit, RAM accounting, `PYTEST_DISABLE_PLUGIN_AUTOLOAD` needs `-p shm`), Development (`just install`, `just test`, `just lint`), License.

- [ ] **Step 2: Write `CLAUDE.md` and symlinks**

Adapted from compose-farm: Core Principles (KISS, YAGNI, DRY), Architecture (file tree of `src/pytest_shm/`), Key Design Decisions (hook timing, containment, per-worker cleanup, no per-test deletion), Development Commands table, Testing (inner sessions through `pytester.run`, the `temproot` fixture), Git Safety, Pull Requests, Releases (`gh release create vX.Y.Z`).
Then `ln -s CLAUDE.md AGENTS.md && ln -s CLAUDE.md GEMINI.md`.

- [ ] **Step 3: Write the workflows**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]

    steps:
      - uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --dev --python ${{ matrix.python-version }}

      - name: Run tests
        run: uv run --python ${{ matrix.python-version }} pytest -n auto -v

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --dev

      - name: Run pre-commit (via prek)
        uses: j178/prek-action@v1
```

`.github/workflows/release.yml`, `.github/workflows/release-drafter.yml`, `.github/workflows/toc.yaml`, `.github/release-drafter.yml`, `.github/renovate.json`: copied verbatim from compose-farm.

- [ ] **Step 4: Verify**

Run: `uv run pre-commit run --all-files && uv run pytest -n auto -q && uv build`
Expected: hooks pass, tests pass, sdist and wheel built with the entry point (`unzip -p dist/*.whl '*/entry_points.txt'` shows `shm = pytest_shm.plugin`).

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md AGENTS.md GEMINI.md .github
git commit -m "Document the plugin and add CI, release, and maintenance workflows"
```

### Task 5: Publish the repository

- [ ] **Step 1:** `gh repo create basnijholt/pytest-shm --public --source . --push --description "Put pytest's temporary files on the /dev/shm tmpfs so fsync-heavy suites stop waiting on the disk"`, then add topics `pytest`, `pytest-plugin`, `tmpfs`, `testing`.
- [ ] **Step 2:** Watch CI on `main` until every job passes; fix and push follow-up commits if not.
- [ ] **Step 3:** Stop. PyPI trusted publishing needs the owner to add a pending publisher (project `pytest-shm`, owner `basnijholt`, repository `pytest-shm`, workflow `release.yml`, environment `pypi`) before `gh release create v0.1.0`.
