"""Test the pwd command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_pwd_prints_the_shell_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that pwd follows cd"""
    (tmp_path / "sub").mkdir()

    run = shell.run("cd sub; pwd")

    assert run.stdout == (tmp_path / "sub").resolve().as_posix() + "\n"
