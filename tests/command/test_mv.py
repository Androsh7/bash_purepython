"""Test the mv command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_mv_renames_a_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that the source disappears and the target holds its content"""
    (tmp_path / "a.txt").write_text("moved\n", encoding="utf-8")

    run = shell.run("mv a.txt b.txt")

    assert run.exit_code == 0
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "moved\n"


def test_mv_moves_into_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a file moved to a directory keeps its name inside it"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "dest").mkdir()

    shell.run("mv a.txt dest")

    assert (tmp_path / "dest" / "a.txt").exists()


def test_mv_no_clobber_keeps_the_existing_target(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -n leaves an existing target and its source alone"""
    (tmp_path / "a.txt").write_text("new", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old", encoding="utf-8")

    shell.run("mv -n a.txt b.txt")

    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "old"
    assert (tmp_path / "a.txt").exists()


def test_mv_missing_source_fails(shell: ShellHarness) -> None:
    """Check that a missing source is reported with exit code one"""
    run = shell.run("mv nothing somewhere")

    assert run.exit_code == 1
    assert "nothing" in run.stderr
