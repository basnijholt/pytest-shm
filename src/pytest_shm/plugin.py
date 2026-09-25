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
    from collections.abc import Iterator, Mapping

    from xdist.workermanage import WorkerController

SHM = Path("/dev/shm")  # noqa: S108
_TEMP_ROOT_VARIABLES = ("TMPDIR", "TEMP", "TMP")
_MIN_FREE_INI = "shm_min_free_gib"
_OWNS_BASETEMP_KEY = "shm_owns_basetemp"
_SWITCHED = pytest.StashKey[bool]()
_OFF_REASON = pytest.StashKey[str]()
_OWNED_BASETEMP = pytest.StashKey[Path]()


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
