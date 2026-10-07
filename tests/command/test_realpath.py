"""Test the realpath command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_realpath_resolves_against_the_shell_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a relative path with dot segments becomes absolute"""
    (tmp_path / "a" / "b").mkdir(parents=True)

    run = shell.run("realpath a/../a/b")

    assert run.stdout == (tmp_path / "a" / "b").resolve().as_posix() + "\n"


def test_realpath_existing_flag_rejects_a_missing_path(shell: ShellHarness) -> None:
    """Check that -e fails for a path that does not exist"""
    run = shell.run("realpath -e missing")

    assert (run.stdout, run.exit_code) == ("", 1)
    assert "missing" in run.stderr
