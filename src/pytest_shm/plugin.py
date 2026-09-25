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
    from collections.abc import Generator, Mapping

    from xdist.workermanage import WorkerController

SHM = Path("/dev/shm")  # noqa: S108
_TEMP_ROOT_VARIABLES = ("TMPDIR", "TEMP", "TMP")
_MIN_FREE_INI = "shm_min_free_gib"
_CONTAINED_NAME = "shm-tmp"
_OWNS_BASETEMP_KEY = "shm_owns_basetemp"
_OFF_REASON = pytest.StashKey[str]()
_CONTAINED = pytest.StashKey[bool]()
_OWNED_BASETEMP = pytest.StashKey[Path]()


def off_reason(
    min_free_gib: float,
    environ: Mapping[str, str],
    basetemp: str | None = None,
) -> str | None:
    """Return why the temp root should stay where it is, or `None` to move it to `/dev/shm`.

    `basetemp` is the caller's `--basetemp`, which, like `PYTEST_DEBUG_TEMPROOT`,
    decides where pytest's base directory goes regardless of the temp root.
    """
    if sys.platform != "linux":
        return "not Linux"
    for name in _TEMP_ROOT_VARIABLES:
        if name in environ:
            return f"{name} is exported"
    base_source, base = (
        ("--basetemp", basetemp)
        if basetemp
        else ("PYTEST_DEBUG_TEMPROOT", environ.get("PYTEST_DEBUG_TEMPROOT"))
    )
    if base and not Path(base).resolve().is_relative_to(SHM.resolve()):
        return f"{base_source} is outside {SHM}"
    return _shm_off_reason(min_free_gib)


def _shm_off_reason(min_free_gib: float) -> str | None:
    """Return why `/dev/shm` itself cannot hold the session's files, or `None`."""
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
        type="float",
        default=1.0,
    )


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config: pytest.Config) -> None:
    """Point the temp root at `/dev/shm` before any `conftest.py` can read it."""
    reason = off_reason(
        early_config.getini(_MIN_FREE_INI),
        os.environ,
        # pytest's tmpdir plugin registers --basetemp, so it is missing when that plugin is.
        getattr(early_config.known_args_namespace, "basetemp", None),
    )
    if reason is None and early_config.pluginmanager.is_blocked("tmpdir"):
        reason = "pytest's tmpdir plugin is disabled"
    if reason is not None:
        early_config.stash[_OFF_REASON] = reason
        return
    previous_tempdir = tempfile.tempdir
    os.environ["TMPDIR"] = str(SHM)
    tempfile.tempdir = None

    def restore() -> None:
        # pytest runs cleanups even when the session never configures, such as on a usage error.
        os.environ.pop("TMPDIR", None)
        tempfile.tempdir = previous_tempdir

    early_config.add_cleanup(restore)


def pytest_report_header(config: pytest.Config) -> str:
    """Say where temporary files go, or why they stay put."""
    temp_root = tempfile.gettempdir()
    if Path(temp_root) == SHM:
        return f"shm: temp root {SHM}"
    return f"shm: off, {config.stash.get(_OFF_REASON, f'temp root is {temp_root}')}"


def _pytest_chose_basetemp(config: pytest.Config) -> bool:
    """Tell whether pytest picked the base directory rather than the caller."""
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        return bool(workerinput.get(_OWNS_BASETEMP_KEY, False))
    return config.option.basetemp is None


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: WorkerController) -> None:
    """Tell each xdist worker whether its base directory is pytest's own or the caller's.

    xdist hands every worker its directory as `--basetemp`, so only the controller
    still knows whether the caller chose one, which must outlive a passing session.
    """
    node.workerinput[_OWNS_BASETEMP_KEY] = node.config.option.basetemp is None


@pytest.hookimpl(wrapper=True)
def pytest_sessionstart(session: pytest.Session) -> Generator[None]:
    """Keep bare `tempfile` output inside pytest's base directory on `/dev/shm`.

    Tests and the code they drive often call `tempfile.mkdtemp()` without removing
    the result. On disk that only clutters `/tmp`, but on tmpfs it would hold memory
    until reboot, so from collection on it joins the `tmp_path` directories that
    `pytest_sessionfinish` frees.

    This runs after every other `pytest_sessionstart`, once xdist has started its
    workers, so they inherit `/dev/shm` itself rather than this process's directory.
    Workers never switch the temp root, so this checks where it is rather than
    whether this process moved it.
    """
    yield
    config = session.config
    # pytest's tmpdir plugin sets this in pytest_configure, and xdist reads it the same way.
    factory: pytest.TempPathFactory | None = getattr(config, "_tmp_path_factory", None)
    if factory is None or Path(tempfile.gettempdir()) != SHM:
        return
    basetemp = factory.getbasetemp()
    if _pytest_chose_basetemp(config) and basetemp.is_relative_to(SHM.resolve()):
        config.stash[_OWNED_BASETEMP] = basetemp
    contained = basetemp / _CONTAINED_NAME
    contained.mkdir()
    os.environ["TMPDIR"] = str(contained)
    tempfile.tempdir = str(contained)
    config.stash[_CONTAINED] = True


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """Hand back `/dev/shm`, and free a passing session's base directory from memory.

    pytest keeps the last three sessions' directories, which on tmpfs pins memory
    until they are pruned. Each xdist worker owns its own base directory, so a
    failing session keeps only the workers that saw a failure. Deleting per test is
    not an option: pytest then reuses the freed names, and caches keyed by path hand
    the next test the previous one's state.
    """
    config = session.config
    if config.stash.get(_CONTAINED, False):
        os.environ["TMPDIR"] = str(SHM)
        tempfile.tempdir = None
    basetemp = config.stash.get(_OWNED_BASETEMP, None)
    if basetemp is not None and exitstatus == 0:
        shutil.rmtree(basetemp, ignore_errors=True)
