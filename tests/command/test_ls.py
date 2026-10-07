"""Test the ls command through the shell"""

# Standard libraries
import os
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.ls import format_modification_time, format_size
from tests.conftest import ShellHarness

LONG_LINE_FIELD_COUNT = 9
OLD_TIMESTAMP_S = 1_000_000_000
NEW_TIMESTAMP_S = 1_700_000_000
ONE_DAY_S = 24 * 60 * 60


@pytest.fixture
def listing_tree(tmp_path: Path) -> None:
    """Build a directory with visible, hidden and nested entries"""
    (tmp_path / "b.txt").write_text("bb", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / ".hidden").write_text("h", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("c", encoding="utf-8")


def long_lines_by_name(stdout: str) -> dict[str, list[str]]:
    """Return the fields of each long-listing line, keyed by the entry name

    Args:
        stdout: The output of ls -l

    Returns:
        The whitespace-separated fields of every line except the total
    """
    lines = [line.split() for line in stdout.splitlines() if not line.startswith("total ")]
    return {fields[-1]: fields for fields in lines}


def test_ls_lists_visible_entries_sorted(shell: ShellHarness, listing_tree: None) -> None:
    """Check that hidden entries are skipped and names are sorted"""
    run = shell.run("ls")

    assert run.stdout.split() == ["a.txt", "b.txt", "sub"]


def test_ls_all_includes_hidden_entries_and_both_dot_directories(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -a shows dot files along with the directory itself and its parent"""
    run = shell.run("ls -a")

    assert run.stdout.split() == [".", "..", ".hidden", "a.txt", "b.txt", "sub"]


def test_ls_almost_all_leaves_out_the_dot_directories(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -A shows dot files but not . and .."""
    run = shell.run("ls -A")

    assert run.stdout.split() == [".hidden", "a.txt", "b.txt", "sub"]


def test_ls_long_starts_with_a_total_line(shell: ShellHarness, listing_tree: None) -> None:
    """Check that a long directory listing is headed by its total"""
    run = shell.run("ls -l")

    assert run.stdout.splitlines()[0].startswith("total ")


def test_ls_long_shows_mode_links_owner_group_size_time_and_name(shell: ShellHarness, listing_tree: None) -> None:
    """Check that each long line carries the nine fields ls -l prints, with the size in bytes"""
    shell.state.variables["USER"] = "guest"

    run = shell.run("ls -l")

    fields = long_lines_by_name(run.stdout)["b.txt"]
    assert len(fields) == LONG_LINE_FIELD_COUNT
    assert (fields[0][0], fields[2], fields[3], fields[4]) == ("-", "guest", "guest", "2")


def test_ls_long_marks_a_directory_in_its_mode(shell: ShellHarness, listing_tree: None) -> None:
    """Check that a directory's mode string starts with d"""
    run = shell.run("ls -l")

    assert long_lines_by_name(run.stdout)["sub"][0].startswith("d")


def test_ls_long_all_of_an_empty_directory_still_prints_the_total_and_dot_directories(
    shell: ShellHarness, tmp_path: Path
) -> None:
    """Check that joined flags on an empty directory show the total, . and .. instead of nothing"""
    (tmp_path / "empty").mkdir()

    run = shell.run("ls -lah empty")

    lines = run.stdout.splitlines()
    assert lines[0].startswith("total ")
    assert [line.split()[-1] for line in lines[1:]] == [".", ".."]


def test_ls_human_readable_shortens_sizes_in_a_long_listing(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -h prints a size with a unit"""
    (tmp_path / "big.bin").write_bytes(b"x" * 1536)

    run = shell.run("ls -lh")

    assert long_lines_by_name(run.stdout)["big.bin"][4] == "1.5K"


@pytest.mark.parametrize("flags", ["-lah", "-alh", "-hal", "-lsa", "-ltr", "-lA1", "-laFS"], ids=str)
def test_ls_accepts_joined_flags(shell: ShellHarness, listing_tree: None, flags: str) -> None:
    """Check that commonly clustered flags are all recognised"""
    run = shell.run(f"ls {flags}")

    assert (run.exit_code, run.stderr) == (0, "")


def test_ls_reverse_reverses_the_order(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -r lists names from last to first"""
    run = shell.run("ls -r")

    assert run.stdout.split() == ["sub", "b.txt", "a.txt"]


def test_ls_sorts_by_size_largest_first(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -S orders files by their size"""
    (tmp_path / "small").write_bytes(b"x")
    (tmp_path / "large").write_bytes(b"x" * 300)
    (tmp_path / "medium").write_bytes(b"x" * 20)

    run = shell.run("ls -S")

    assert run.stdout.split() == ["large", "medium", "small"]


def test_ls_sorts_by_time_newest_first(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -t orders files by when they were modified"""
    for name, modified_s in (("old", OLD_TIMESTAMP_S), ("new", NEW_TIMESTAMP_S)):
        (tmp_path / name).write_text(name, encoding="utf-8")
        os.utime(tmp_path / name, (modified_s, modified_s))

    run = shell.run("ls -t")

    assert run.stdout.split() == ["new", "old"]


def test_ls_one_per_line_prints_each_name_on_its_own_line(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -1 puts one entry on each line"""
    run = shell.run("ls -1")

    assert run.stdout.splitlines() == ["a.txt", "b.txt", "sub"]


def test_ls_directory_flag_lists_the_directory_itself(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -d names the directory instead of its content"""
    run = shell.run("ls -d sub")

    assert run.stdout.split() == ["sub"]


def test_ls_classify_marks_directories_with_a_slash(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -F appends a slash to a directory and nothing to a file"""
    run = shell.run("ls -F")

    assert run.stdout.split() == ["a.txt", "b.txt", "sub/"]


def test_ls_size_flag_prefixes_each_entry_with_its_blocks(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -s prints a total and a block count before every name"""
    run = shell.run("ls -s")

    lines = run.stdout.splitlines()
    assert lines[0].startswith("total ")
    assert [line.split()[-1] for line in lines[1:]] == ["a.txt", "b.txt", "sub"]
    assert all(line.split()[0].isdigit() for line in lines[1:])


def test_ls_recursive_lists_descendants(shell: ShellHarness, listing_tree: None) -> None:
    """Check that -R includes nested files with their relative paths"""
    run = shell.run("ls -R")

    assert "sub/c.txt" in run.stdout.split()


def test_ls_lists_named_files_before_named_directories_under_headers(shell: ShellHarness, listing_tree: None) -> None:
    """Check that a file argument is listed as itself and a directory argument under its own header"""
    run = shell.run("ls sub a.txt")

    assert run.stdout.splitlines() == ["a.txt", "", "sub:", "c.txt"]


def test_ls_missing_path_fails(shell: ShellHarness) -> None:
    """Check that a missing path is reported with exit code one"""
    run = shell.run("ls nowhere")

    assert run.exit_code == 1
    assert "nowhere" in run.stderr


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0"),
        (1023, "1023"),
        (1024, "1.0K"),
        (1536, "1.5K"),
        (10240, "10K"),
        (1048576, "1.0M"),
        (12 * 1048576, "12M"),
    ],
    ids=[
        "zero",
        "under_a_kilobyte",
        "one_kilobyte",
        "one_and_a_half",
        "ten_kilobytes",
        "one_megabyte",
        "twelve_megabytes",
    ],
)
def test_format_size_matches_gnu_short_form(size: int, expected: str) -> None:
    """Check the human-readable size format"""
    assert format_size(size) == expected


def test_recent_modification_time_shows_the_time_of_day() -> None:
    """Check that an entry modified within the last six months is printed with hours and minutes"""
    formatted = format_modification_time(NEW_TIMESTAMP_S - ONE_DAY_S, NEW_TIMESTAMP_S)

    assert ":" in formatted


def test_old_modification_time_shows_the_year() -> None:
    """Check that an entry modified years ago is printed with its year instead of a time of day"""
    formatted = format_modification_time(OLD_TIMESTAMP_S, NEW_TIMESTAMP_S)

    assert formatted.endswith("2001")
    assert ":" not in formatted
