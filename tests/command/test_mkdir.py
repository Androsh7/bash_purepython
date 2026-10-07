"""Test the mkdir command through the shell"""

# Standard libraries
from pathlib import Path

# Project libraries
from tests.conftest import ShellHarness


def test_mkdir_creates_a_directory(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a new directory appears"""
    run = shell.run("mkdir fresh")

    assert (run.exit_code, (tmp_path / "fresh").is_dir()) == (0, True)


def test_mkdir_parents_creates_the_chain(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -p creates missing parents and tolerates an existing directory"""
    run = shell.run("mkdir -p a/b/c; mkdir -p a/b/c")

    assert (run.exit_code, (tmp_path / "a" / "b" / "c").is_dir()) == (0, True)


def test_mkdir_existing_directory_fails(shell: ShellHarness) -> None:
    """Check that creating a directory twice without -p fails"""
    run = shell.run("mkdir dup; mkdir dup")

    assert run.exit_code == 1
    assert "dup" in run.stderr


def test_mkdir_verbose_names_the_directory(shell: ShellHarness) -> None:
    """Check that -v prints the created directory"""
    run = shell.run("mkdir -v made")

    assert "made" in run.stdout
