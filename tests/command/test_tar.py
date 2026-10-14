"""Test the tar command through the shell"""

# Standard libraries
import gzip
import io
import tarfile
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from bash_purepython.command.tar import TarCommand, normalise_arguments
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds tar"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), TarCommand()]))


@pytest.fixture
def source_tree(tmp_path: Path) -> None:
    """Build a directory with a nested file to archive"""
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "project" / "sub").mkdir()
    (tmp_path / "project" / "sub" / "b.txt").write_text("beta\n", encoding="utf-8")


def archive_names(archive_bytes: bytes) -> set[str]:
    """Return the member names of an archive held in memory

    Args:
        archive_bytes: The archive, compressed or not

    Returns:
        The names
    """
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        return set(archive.getnames())


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["czf", "out.tgz", "dir"], ["-c", "-z", "-f", "out.tgz", "dir"]),
        (["cfz", "out.tgz", "dir"], ["-c", "-f", "out.tgz", "-z", "dir"]),
        (["-xzf", "in.tgz"], ["-xzf", "in.tgz"]),
        (["--create", "-f", "x"], ["--create", "-f", "x"]),
        (["dir"], ["dir"]),
    ],
    ids=["bundled", "file letter mid bundle", "already dashed", "long options", "not a flag bundle"],
)
def test_normalise_arguments_rewrites_only_a_bundled_first_argument(arguments: list[str], expected: list[str]) -> None:
    """Check that an old-style flag bundle is split into options and everything else is left alone"""
    assert normalise_arguments(arguments) == expected


def test_tar_creates_a_gzip_archive_of_a_directory(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that czf writes a gzip archive holding the directory and everything under it"""
    run = shell.run("tar czf project.tgz project")

    archive_bytes = (tmp_path / "project.tgz").read_bytes()
    assert run.exit_code == 0
    assert gzip.decompress(archive_bytes)
    assert archive_names(archive_bytes) == {"project", "project/a.txt", "project/sub", "project/sub/b.txt"}


def test_tar_lists_the_members_of_an_archive(shell: ShellHarness, source_tree: None) -> None:
    """Check that tf prints every member name"""
    shell.run("tar cf project.tar project")

    run = shell.run("tar tf project.tar")

    assert set(run.stdout.split()) == {"project/", "project/a.txt", "project/sub/", "project/sub/b.txt"}


def test_tar_extracts_into_another_directory(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that -C extracts the archive under the named directory"""
    shell.run("tar czf project.tgz project; mkdir out")

    run = shell.run("tar xzf project.tgz -C out")

    assert run.exit_code == 0
    assert (tmp_path / "out" / "project" / "sub" / "b.txt").read_text(encoding="utf-8") == "beta\n"


def test_tar_streams_an_archive_through_a_pipe(shell: ShellHarness, tmp_path: Path, source_tree: None) -> None:
    """Check that an archive written to standard output can be extracted from standard input"""
    shell.run("mkdir out")

    run = shell.run("tar czf - project | tar xzf - -C out")

    assert run.exit_code == 0
    assert (tmp_path / "out" / "project" / "a.txt").read_text(encoding="utf-8") == "alpha\n"


def test_tar_create_with_directory_option_archives_relative_to_it(
    shell: ShellHarness, tmp_path: Path, source_tree: None
) -> None:
    """Check that -C changes where members are taken from and strips the directory from their names"""
    shell.run("tar cf inner.tar -C project a.txt")

    assert archive_names((tmp_path / "inner.tar").read_bytes()) == {"a.txt"}


def test_tar_verbose_create_names_each_member(shell: ShellHarness, source_tree: None) -> None:
    """Check that -v prints the members as they are added"""
    run = shell.run("tar cvf project.tar project")

    assert set(run.stdout.split()) == {"project/", "project/a.txt", "project/sub/", "project/sub/b.txt"}


def test_tar_reports_a_missing_member(shell: ShellHarness) -> None:
    """Check that a missing file is reported and the exit code is two"""
    run = shell.run("tar cf out.tar missing.txt")

    assert run.exit_code == 2
    assert "missing.txt" in run.stderr


def test_tar_reports_a_missing_archive(shell: ShellHarness) -> None:
    """Check that extracting from a missing archive fails"""
    run = shell.run("tar xf missing.tar")

    assert run.exit_code == 2
    assert "missing.tar" in run.stderr


def test_tar_requires_exactly_one_mode(shell: ShellHarness) -> None:
    """Check that naming no mode is an error"""
    run = shell.run("tar -f out.tar")

    assert run.exit_code == 2


def test_tar_reports_a_truncated_compressed_archive(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a gzip stream cut short fails with a message rather than a crash"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        archive.add(tmp_path, arcname="dir", recursive=False)
    whole = gzip.compress(buffer.getvalue())
    (tmp_path / "truncated.tar.gz").write_bytes(whole[: len(whole) // 2])

    run = shell.run("tar -xzf truncated.tar.gz")

    assert run.exit_code == 2
    assert "truncated.tar.gz" in run.stderr


def test_tar_reports_a_missing_archive_directory(shell: ShellHarness, source_tree: None) -> None:
    """Check that writing an archive into a missing directory fails with a message"""
    run = shell.run("tar -cf nodir/out.tar project")

    assert run.exit_code == 2
    assert "nodir/out.tar" in run.stderr


def test_tar_old_style_bundle_takes_the_archive_after_the_bundle(
    shell: ShellHarness, tmp_path: Path, source_tree: None
) -> None:
    """Check that cvfz names the archive with the word after the bundle even though z follows f"""
    run = shell.run("tar cvfz out.tgz project")

    assert run.exit_code == 0
    assert (tmp_path / "out.tgz").is_file()
    assert not (tmp_path / "z").exists()
