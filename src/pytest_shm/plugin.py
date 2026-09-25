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
