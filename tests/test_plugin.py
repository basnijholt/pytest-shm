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
from pathlib import Path

def test_temp_root():
    temp_root = Path(tempfile.gettempdir()).resolve()
    assert not temp_root.is_relative_to(Path("/dev/shm").resolve())
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


@pytest.fixture
def disk_dir() -> Iterator[Path]:
    """Give a directory outside /dev/shm."""
    path = Path(tempfile.mkdtemp(dir="/var/tmp", prefix="pytest-shm-test-"))
    yield path
    shutil.rmtree(path)


def run_pytest(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run pytest in a subprocess without the `--basetemp` that `runpytest_subprocess` forces."""
    return pytester.run(sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args, timeout=60)


def test_plugin_is_registered(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("shm")


@needs_shm
def test_moves_the_temp_root_to_shm_before_conftests_load(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Let pytest derive its base directory from the switched TMPDIR, as it does for users.
    monkeypatch.delenv("PYTEST_DEBUG_TEMPROOT")
    pytester.makeconftest(
        """
        import tempfile

        IMPORT_TIME_TEMP_ROOT = tempfile.gettempdir()

        def pytest_report_header():
            return f"conftest saw {IMPORT_TIME_TEMP_ROOT}"
        """
    )
    pytester.makepyfile(
        """
        import tempfile
        from pathlib import Path

        def test_temp_root(tmp_path_factory):
            shm = Path("/dev/shm").resolve()
            assert Path(tempfile.gettempdir()).is_relative_to(shm)
            assert tmp_path_factory.getbasetemp().is_relative_to(shm)
        """
    )
    result = run_pytest(pytester)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: temp root /dev/shm", "conftest saw /dev/shm"])


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
def test_base_directory_chosen_outside_shm_leaves_the_temp_root_alone(
    pytester: pytest.Pytester, temproot: Path, disk_dir: Path
) -> None:
    pytester.makepyfile(_TEMP_ROOT_IS_NOT_SHM)
    result = run_pytest(pytester, f"--basetemp={disk_dir / 'basetemp'}")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: off, --basetemp is outside /dev/shm"])


@needs_shm
def test_debug_temp_root_outside_shm_leaves_the_temp_root_alone(
    pytester: pytest.Pytester, temproot: Path, disk_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(disk_dir))
    pytester.makepyfile(_TEMP_ROOT_IS_NOT_SHM)
    result = run_pytest(pytester)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: off, PYTEST_DEBUG_TEMPROOT is outside /dev/shm"])


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
@pytest.mark.skipif(
    int(pytest.__version__.partition(".")[0]) < 9, reason="native [tool.pytest] needs pytest 9"
)
def test_threshold_accepts_a_native_toml_number(pytester: pytest.Pytester, temproot: Path) -> None:
    pytester.makepyprojecttoml("[tool.pytest]\nshm_min_free_gib = 1e9\n")
    pytester.makepyfile(_TEMP_ROOT_IS_NOT_SHM)
    result = run_pytest(pytester)
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


def test_disabled_tmpdir_plugin_leaves_sessions_working(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_pass():\n    pass\n")
    result = run_pytest(pytester, "-p", "no:tmpdir")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: off, *"])


@needs_shm
def test_disabled_tmpdir_plugin_turns_the_plugin_off(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile(_TEMP_ROOT_IS_NOT_SHM)
    result = run_pytest(pytester, "-p", "no:tmpdir")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["shm: off, pytest's tmpdir plugin is disabled"])


@needs_shm
def test_in_process_session_restores_the_callers_environment(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch, disk_dir: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(disk_dir))
    pytester.makepyfile("def test_pass():\n    pass\n")
    pytester.runpytest_inprocess().assert_outcomes(passed=1)
    assert "TMPDIR" not in os.environ
    assert tempfile.tempdir == str(disk_dir)


@needs_shm
def test_in_process_usage_error_restores_the_environment(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", None)
    result = pytester.runpytest_inprocess("--no-such-flag")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "TMPDIR" not in os.environ
    assert not Path(tempfile.gettempdir()).is_relative_to(SHM)


@needs_shm
def test_in_process_session_hands_back_an_exported_shm_temp_root(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(SHM))
    monkeypatch.setattr(tempfile, "tempdir", None)
    pytester.makepyfile(
        """
        import tempfile

        def test_contained():
            assert tempfile.gettempdir() != "/dev/shm"
        """
    )
    pytester.runpytest_inprocess().assert_outcomes(passed=1)
    assert os.environ["TMPDIR"] == str(SHM)
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


@needs_shm
def test_bare_tempfile_output_lands_in_the_base_directory_from_collection_on(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile(
        """
        import os
        import tempfile
        from pathlib import Path

        COLLECTION_TIME_DIRECTORY = Path(tempfile.mkdtemp())

        def test_contained(tmp_path_factory):
            contained = tmp_path_factory.getbasetemp() / "shm-tmp"
            assert COLLECTION_TIME_DIRECTORY.parent == contained
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

        def test_write(tmp_path):
            (tmp_path / "state").write_text("x")
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
        assert list(basetemp.glob("shm-tmp/tmp*/state"))


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
def test_exported_shm_temp_root_with_base_directory_on_disk_is_left_alone(
    pytester: pytest.Pytester, temproot: Path, disk_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Containing would move files the caller sent to /dev/shm onto disk.
    monkeypatch.setenv("TMPDIR", str(SHM))
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(disk_dir))
    pytester.makepyfile(
        """
        import tempfile

        def test_write(tmp_path):
            assert tempfile.gettempdir() == "/dev/shm"
            (tmp_path / "kept").write_text("x")
        """
    )
    run_pytest(pytester).assert_outcomes(passed=1)
    assert list(disk_dir.glob("pytest-of-*/pytest-[0-9]*/test_write0/kept"))


@needs_shm
def test_exported_shm_temp_root_without_tmpdir_plugin_still_runs(
    pytester: pytest.Pytester, temproot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(SHM))
    pytester.makepyfile("def test_pass():\n    pass\n")
    run_pytest(pytester, "-p", "no:tmpdir").assert_outcomes(passed=1)


@needs_shm
@pytest.mark.parametrize(
    ("args", "exit_code"),
    [(("-k", "no_such_test"), 5), (("no_such_path.py",), 4)],
    ids=["no-tests-collected", "usage-error"],
)
def test_session_that_runs_no_tests_leaves_nothing_behind(
    pytester: pytest.Pytester, temproot: Path, args: tuple[str, ...], exit_code: int
) -> None:
    pytester.makepyfile("def test_pass():\n    pass\n")
    assert run_pytest(pytester, *args).ret == exit_code
    assert list(temproot.glob("pytest-of-*/pytest-[0-9]*")) == []


@needs_shm
def test_base_directory_is_freed_after_session_fixtures_finish_with_it(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    # pytest.exit skips the last test's teardown, so pytest tears session fixtures down
    # in pytest_sessionfinish, which must run before the base directory disappears.
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture(scope="session")
        def state(tmp_path_factory):
            path = tmp_path_factory.mktemp("state")
            yield path
            (path / "closed").write_text("x")

        def test_stop(state):
            pytest.exit("done", returncode=0)
        """
    )
    result = run_pytest(pytester)
    assert result.ret == 0, result.stdout.str()
    result.stdout.no_fnmatch_line("*Error*")
    assert list(temproot.glob("pytest-of-*/pytest-[0-9]*")) == []


@needs_shm
def test_passing_xdist_session_leaves_nothing_behind(
    pytester: pytest.Pytester, temproot: Path
) -> None:
    pytester.makepyfile("def test_write(tmp_path):\n    (tmp_path / 'state').write_text('x')\n")
    run_pytest(pytester, "-n", "2", "--dist", "each").assert_outcomes(passed=2)
    assert list(temproot.glob("pytest-of-*/pytest-[0-9]*")) == []


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
    assert sorted(path.name for path in basetemp.iterdir()) == ["popen-gw1", "shm-tmp"]


def test_loads_without_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_pass():\n    pass\n")
    run_pytest(pytester, "-p", "no:xdist").assert_outcomes(passed=1)
