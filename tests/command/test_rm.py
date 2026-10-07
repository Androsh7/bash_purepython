"""Test the rm command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_rm_removes_a_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the file is gone"""
    (tmp_path / "gone.txt").write_text("x", encoding="utf-8")

    run = shell.run("rm gone.txt")

    assert (run.exit_code, (tmp_path / "gone.txt").exists()) == (0, False)


def test_rm_refuses_a_directory_without_recursive(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a directory needs -r"""
    (tmp_path / "dir").mkdir()

    run = shell.run("rm dir")

    assert (run.exit_code, (tmp_path / "dir").exists()) == (1, True)


def test_rm_recursive_removes_a_tree(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -r removes a directory and its content"""
    (tmp_path / "tree" / "sub").mkdir(parents=True)
    (tmp_path / "tree" / "sub" / "f").write_text("x", encoding="utf-8")

    run = shell.run("rm -r tree")

    assert (run.exit_code, (tmp_path / "tree").exists()) == (0, False)


def test_rm_missing_file_fails_unless_forced(shell: ShellHarness) -> None:
    """Check that a missing file is an error without -f and silent with it"""
    plain = shell.run("rm nothing")
    forced = shell.run("rm -f nothing")

    assert (plain.exit_code, forced.exit_code, forced.stderr) == (1, 0, "")
