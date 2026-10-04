"""Tests for completing the word under the cursor"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.completion import option_names_from_help, render_word, scan_partial_word
from bash_purepython.shell.models import PartialWord, QuoteStyle, WordPosition
from bash_purepython.shell.session import ShellSession

SAMPLE_HELP = """\
usage: grep [-h] [-i] [-n] pattern [paths ...]

Search lines matching a pattern

positional arguments:
  pattern            Regular expression
  paths              Files to search

options:
  -h, --help         show this help message and exit
  -i, --ignore-case  Case insensitive match
  -n, --line-number  Prefix lines with line number
"""


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ca", PartialWord(0, "ca", QuoteStyle.NONE, WordPosition.COMMAND, None)),
        ("cat fi", PartialWord(4, "fi", QuoteStyle.NONE, WordPosition.ARGUMENT, "cat")),
        ("cat ", PartialWord(4, "", QuoteStyle.NONE, WordPosition.ARGUMENT, "cat")),
        ("cat 'a b", PartialWord(4, "a b", QuoteStyle.SINGLE, WordPosition.ARGUMENT, "cat")),
        ('cat "a\\"b', PartialWord(4, 'a"b', QuoteStyle.DOUBLE, WordPosition.ARGUMENT, "cat")),
        ("cat a\\ b", PartialWord(4, "a b", QuoteStyle.NONE, WordPosition.ARGUMENT, "cat")),
        ("echo x > ou", PartialWord(9, "ou", QuoteStyle.NONE, WordPosition.REDIRECT_TARGET, "echo")),
        ("echo x | gr", PartialWord(9, "gr", QuoteStyle.NONE, WordPosition.COMMAND, None)),
        ("a && b || c; ls -", PartialWord(16, "-", QuoteStyle.NONE, WordPosition.ARGUMENT, "ls")),
    ],
    ids=[
        "command",
        "argument",
        "empty-argument",
        "single-quoted",
        "double-quoted-escape",
        "backslash-space",
        "redirect-target",
        "after-pipe",
        "after-list",
    ],
)
def test_scan_partial_word_finds_the_word_and_its_position(line: str, expected: PartialWord) -> None:
    """Check that the word under the cursor is isolated with its quoting and role"""
    word = scan_partial_word(line, len(line))

    assert word == expected


@pytest.mark.parametrize(
    ("value", "quote", "final", "expected"),
    [
        ("plain", QuoteStyle.NONE, True, "plain "),
        ("has space", QuoteStyle.NONE, True, "has\\ space "),
        ("a|b", QuoteStyle.NONE, False, "a\\|b"),
        ("~/dir/", QuoteStyle.NONE, False, "~/dir/"),
        ("has space", QuoteStyle.SINGLE, True, "'has space' "),
        ("has space", QuoteStyle.SINGLE, False, "'has space"),
        ('say "hi"', QuoteStyle.DOUBLE, True, '"say \\"hi\\"" '),
    ],
    ids=["plain", "escaped-space", "escaped-pipe", "tilde-kept", "single-final", "single-partial", "double-final"],
)
def test_render_word_reapplies_the_original_quoting(value: str, quote: QuoteStyle, final: bool, expected: str) -> None:
    """Check that completed text is quoted the way the user started it"""
    rendered = render_word(value, quote, final)

    assert rendered == expected


def test_option_names_from_help_reads_short_and_long_options() -> None:
    """Check that every option in the options section is found once"""
    names = option_names_from_help(SAMPLE_HELP)

    assert names == ["-h", "--help", "-i", "--ignore-case", "-n", "--line-number"]


def test_complete_finishes_a_unique_command_name(session: ShellSession) -> None:
    """Check that a command prefix with one match is completed with a trailing space"""
    result = session.complete("gre", 3)

    assert result.replacement == "grep "
    assert result.word_start == 0


def test_complete_offers_builtins_and_host_commands_too(session: ShellSession) -> None:
    """Check that the command list is the union of every kind"""
    result = session.complete("vi", 2)

    assert result.replacement == "vim "


def test_complete_lists_paths_sharing_only_the_typed_prefix(session: ShellSession, shell_home: Path) -> None:
    """Check that several matches with no longer common prefix are listed"""
    (shell_home / "alpha.txt").write_text("")
    (shell_home / "al-notes").mkdir()

    result = session.complete("cat al", 6)

    assert result.replacement is None
    assert set(result.listing) == {"alpha.txt", "al-notes/"}


def test_complete_extends_to_the_common_prefix(session: ShellSession, shell_home: Path) -> None:
    """Check that matches sharing more than what was typed are extended that far"""
    (shell_home / "report-one.txt").write_text("")
    (shell_home / "report-two.txt").write_text("")

    result = session.complete("cat re", 6)

    assert result.replacement == "report-"


def test_complete_finishes_a_file_with_a_space_and_a_directory_with_a_slash(
    session: ShellSession, shell_home: Path
) -> None:
    """Check that a file completion ends the word and a directory completion leaves it open"""
    (shell_home / "alpha.txt").write_text("")
    (shell_home / "alps").mkdir()

    file_result = session.complete("cat alph", 8)
    directory_result = session.complete("cat alps", 8)

    assert file_result.replacement == "alpha.txt "
    assert directory_result.replacement == "alps/"


def test_complete_descends_into_a_directory_and_keeps_the_tilde(session: ShellSession, shell_home: Path) -> None:
    """Check that ~/ is used for the lookup but preserved in the replacement"""
    (shell_home / "docs").mkdir()
    (shell_home / "docs" / "readme.md").write_text("")

    result = session.complete("cat ~/docs/re", 13)

    assert result.replacement == "~/docs/readme.md "


def test_complete_requotes_a_quoted_path(session: ShellSession, shell_home: Path) -> None:
    """Check that a word opened with a quote is closed with the same quote"""
    (shell_home / "my notes.txt").write_text("")

    result = session.complete("cat 'my", 7)

    assert result.replacement == "'my notes.txt' "


def test_complete_offers_flags_of_a_package_command(session: ShellSession) -> None:
    """Check that a dash after a package command completes its options"""
    result = session.complete("grep --ig", 9)

    assert result.replacement == "--ignore-case "


def test_complete_lists_flags_when_only_a_dash_is_typed(session: ShellSession) -> None:
    """Check that ls - lists several options"""
    result = session.complete("ls -", 4)

    assert "-l" in result.listing
    assert "--help" in result.listing


def test_complete_restarts_command_completion_after_a_pipe(session: ShellSession) -> None:
    """Check that the word after | is a command name again"""
    result = session.complete("echo hi | gre", 13)

    assert result.replacement == "grep "


def test_complete_returns_nothing_for_a_missing_directory(session: ShellSession) -> None:
    """Check that a path into a directory that does not exist has no candidates"""
    result = session.complete("cat nope/fi", 11)

    assert result.replacement is None
    assert result.listing == ()
