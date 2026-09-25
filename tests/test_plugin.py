"""Behavior of the pytest-shm plugin, observed through real pytest sessions."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

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


def test_plugin_is_registered(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("shm")


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
