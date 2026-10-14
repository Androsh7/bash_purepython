"""Test the unzip command through the shell"""

# Standard libraries
import zipfile
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from bash_purepython.command.unzip import UnzipCommand
from tests.conftest import ShellHarness

ENTRY_DATE_TIME = (2024, 1, 2, 3, 4, 0)


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds unzip"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), UnzipCommand()]))


@pytest.fixture
def archive(tmp_path: Path) -> None:
    """Build an archive with a file and a directory"""
    with zipfile.ZipFile(tmp_path / "in.zip", "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(zipfile.ZipInfo("a.txt", ENTRY_DATE_TIME), "alpha\n", compress_type=zipfile.ZIP_DEFLATED)
        zipped.writestr(zipfile.ZipInfo("sub/", ENTRY_DATE_TIME), "")
        zipped.writestr(zipfile.ZipInfo("sub/b.txt", ENTRY_DATE_TIME), "beta\n", compress_type=zipfile.ZIP_DEFLATED)


def test_unzip_extracts_every_entry(shell: ShellHarness, tmp_path: Path, archive: None) -> None:
    """Check that the files are written with their contents"""
    run = shell.run("unzip in.zip")

    assert run.exit_code == 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\n"
    assert (tmp_path / "sub" / "b.txt").read_text(encoding="utf-8") == "beta\n"


def test_unzip_lists_entries_in_the_info_zip_table(shell: ShellHarness, archive: None) -> None:
    """Check that -l prints the archive name, one line per entry and the totals in the Info-ZIP layout"""
    run = shell.run("unzip -l in.zip")

    assert run.stdout == (
        "Archive:  in.zip\n"
        "  Length      Date    Time    Name\n"
        "---------  ---------- -----   ----\n"
        "        6  2024-01-02 03:04   a.txt\n"
        "        0  2024-01-02 03:04   sub/\n"
        "        5  2024-01-02 03:04   sub/b.txt\n"
        "---------                     -------\n"
        "       11                     3 files\n"
    )


def test_unzip_extracts_into_the_named_directory(shell: ShellHarness, tmp_path: Path, archive: None) -> None:
    """Check that -d puts the entries under another directory"""
    shell.run("unzip -q in.zip -d out")

    assert (tmp_path / "out" / "a.txt").read_text(encoding="utf-8") == "alpha\n"


def test_unzip_refuses_to_overwrite_without_the_flag(shell: ShellHarness, tmp_path: Path, archive: None) -> None:
    """Check that an existing file is kept and the exit code is one"""
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")

    run = shell.run("unzip in.zip a.txt")

    assert run.exit_code == 1
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old\n"


def test_unzip_overwrites_with_the_flag(shell: ShellHarness, tmp_path: Path, archive: None) -> None:
    """Check that -o replaces an existing file"""
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")

    run = shell.run("unzip -o in.zip a.txt")

    assert run.exit_code == 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\n"


def test_unzip_quiet_prints_nothing(shell: ShellHarness, archive: None) -> None:
    """Check that -q suppresses the extraction log"""
    run = shell.run("unzip -q in.zip")

    assert run.stdout == ""


def test_unzip_reports_a_missing_archive(shell: ShellHarness) -> None:
    """Check that a missing archive fails with exit code nine"""
    run = shell.run("unzip missing.zip")

    assert run.exit_code == 9
    assert "missing.zip" in run.stderr


def test_unzip_reports_an_encrypted_entry(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an entry needing a password fails with a message rather than a crash"""
    with zipfile.ZipFile(tmp_path / "locked.zip", "w") as zipped:
        zipped.writestr("secret.txt", "x")
        zipped.getinfo("secret.txt").flag_bits |= 0x1

    run = shell.run("unzip locked.zip")

    assert run.exit_code != 0
    assert "secret.txt" in run.stderr
    assert not (tmp_path / "secret.txt").exists()


def test_unzip_reports_a_corrupt_entry(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a member whose data fails its checksum is reported with a non-zero exit"""
    with zipfile.ZipFile(tmp_path / "bad.zip", "w") as zipped:
        zipped.writestr("a.txt", "alpha alpha alpha")
    archive_bytes = bytearray((tmp_path / "bad.zip").read_bytes())
    data_start = archive_bytes.index(b"alpha")
    archive_bytes[data_start : data_start + 5] = b"omega"
    (tmp_path / "bad.zip").write_bytes(bytes(archive_bytes))

    run = shell.run("unzip bad.zip")

    assert run.exit_code != 0
    assert "a.txt" in run.stderr
