"""Test the zip command through the shell"""

# Standard libraries
import zipfile
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from bash_purepython.command.zip import ZipCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds zip"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), ZipCommand()]))


@pytest.fixture
def source_tree(tmp_path: Path) -> None:
    """Build a file and a directory with a nested file"""
    (tmp_path / "a.txt").write_bytes(b"alpha alpha alpha\n")
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "b.txt").write_bytes(b"beta\n")


def test_zip_adds_files_to_a_new_archive(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that the named files end up in the archive with their contents"""
    run = shell.run("zip out.zip a.txt")

    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        assert archive.namelist() == ["a.txt"]
        assert archive.read("a.txt") == b"alpha alpha alpha\n"
    assert run.exit_code == 0


def test_zip_adds_the_suffix_when_the_name_has_none(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that an archive name without a suffix gains .zip"""
    shell.run("zip out a.txt")

    assert (tmp_path / "out.zip").exists()


def test_zip_recurses_into_directories(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that -r adds the directory and everything under it"""
    shell.run("zip -r out.zip project")

    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        assert set(archive.namelist()) == {"project/", "project/b.txt"}


def test_zip_prints_an_adding_line_per_entry(shell: ShellHarness, source_tree: None) -> None:
    """Check that each entry is reported with its method"""
    run = shell.run("zip out.zip a.txt")

    assert run.stdout.startswith("  adding: a.txt (deflated ")


def test_zip_quiet_prints_nothing(shell: ShellHarness, source_tree: None) -> None:
    """Check that -q suppresses the adding lines"""
    run = shell.run("zip -q out.zip a.txt")

    assert run.stdout == ""


def test_zip_reports_a_missing_source(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that a missing source is reported while the others are still added"""
    run = shell.run("zip out.zip missing.txt a.txt")

    assert run.exit_code != 0
    assert "missing.txt" in run.stderr
    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        assert archive.namelist() == ["a.txt"]


def test_zip_accepts_an_absolute_source_path(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that an absolute source is stored under a relative entry name"""
    run = shell.run(f'zip out.zip "{(tmp_path / "a.txt").as_posix()}"')

    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        names = archive.namelist()
    assert run.exit_code == 0
    assert len(names) == 1
    assert names[0].endswith("a.txt")
    assert not names[0].startswith("/")


def test_zip_adds_to_an_existing_archive(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that a second zip call keeps the entries the first one wrote"""
    shell.run("zip out.zip a.txt")

    run = shell.run("zip out.zip project/b.txt")

    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        assert set(archive.namelist()) == {"a.txt", "project/b.txt"}
        assert archive.read("a.txt") == b"alpha alpha alpha\n"
    assert run.exit_code == 0


def test_zip_replaces_a_changed_entry(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that re-adding a file updates its contents and says so"""
    shell.run("zip out.zip a.txt")
    (tmp_path / "a.txt").write_bytes(b"changed\n")

    run = shell.run("zip out.zip a.txt")

    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        assert archive.read("a.txt") == b"changed\n"
    assert run.stdout.startswith("updating: a.txt")


def test_zip_reports_a_missing_archive_directory(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that an archive path in a missing directory fails with a message rather than a crash"""
    run = shell.run("zip nodir/out.zip a.txt")

    assert run.exit_code != 0
    assert "nodir/out.zip" in run.stderr
    assert not (tmp_path / "nodir").exists()


def test_zip_recursing_the_current_directory_skips_the_archive(
    shell: ShellHarness, tmp_path: Path, source_tree: None
) -> None:
    """Check that the archive being written is never added to itself"""
    run = shell.run("zip -r out.zip .")

    with zipfile.ZipFile(tmp_path / "out.zip") as archive:
        assert "out.zip" not in archive.namelist()
        assert "a.txt" in archive.namelist()
    assert run.exit_code == 0
