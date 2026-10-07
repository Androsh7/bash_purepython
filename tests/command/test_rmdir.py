"""Test the rmdir command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_rmdir_removes_an_empty_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an empty directory disappears"""
    (tmp_path / "empty").mkdir()

    run = shell.run("rmdir empty")

    assert (run.exit_code, (tmp_path / "empty").exists()) == (0, False)


def test_rmdir_refuses_a_non_empty_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a directory with content is kept and reported"""
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "file").write_text("x", encoding="utf-8")

    run = shell.run("rmdir full")

    assert (run.exit_code, (tmp_path / "full").exists()) == (1, True)


def test_rmdir_parents_removes_the_empty_chain(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -p removes each emptied parent up to the shell directory"""
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)

    run = shell.run("rmdir -p a/b/c")

    assert (run.exit_code, (tmp_path / "a").exists(), tmp_path.exists()) == (0, False, True)
