"""Test that unquoted wildcards expand to the paths they match"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.fixture
def files(tmp_path: Path) -> Path:
    """Return a directory holding a few files, a hidden file and a subdirectory"""
    for name in ("alpha.txt", "beta.txt", "gamma.md", ".hidden.txt", "odd[1].txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    return tmp_path


def printed_words(stdout: str) -> list[str]:
    """Return the lines a ``printf '%s\\n'`` call printed

    Args:
        stdout: The captured output

    Returns:
        One entry per printed argument
    """
    return stdout.splitlines()


def test_star_expands_to_matching_names_in_sorted_order(shell: ShellHarness, files: Path) -> None:
    """Check that a wildcard is replaced by every matching name, sorted"""
    run = shell.run("printf '%s\\n' *.md a*.txt b*")

    assert printed_words(run.stdout) == ["gamma.md", "alpha.txt", "beta.txt"]


def test_star_alone_skips_hidden_files(shell: ShellHarness, files: Path) -> None:
    """Check that a bare star lists visible entries and leaves dot files out"""
    run = shell.run("printf '%s\\n' *")

    assert set(printed_words(run.stdout)) == {"alpha.txt", "beta.txt", "gamma.md", "odd[1].txt", "sub"}


def test_pattern_naming_the_dot_matches_hidden_files(shell: ShellHarness, files: Path) -> None:
    """Check that a hidden file is matched once the pattern starts with a dot"""
    run = shell.run("printf '%s\\n' .h*")

    assert printed_words(run.stdout) == [".hidden.txt"]


def test_question_mark_and_bracket_patterns_match(shell: ShellHarness, files: Path) -> None:
    """Check that ? matches one character and a bracket set matches one of its members"""
    run = shell.run("printf '%s\\n' ?eta.txt [ag]*.md")

    assert printed_words(run.stdout) == ["beta.txt", "gamma.md"]


def test_pattern_with_a_directory_matches_inside_it(shell: ShellHarness, files: Path) -> None:
    """Check that a wildcard after a directory name matches that directory's entries"""
    run = shell.run("printf '%s\\n' sub/*.txt")

    assert [Path(word) for word in printed_words(run.stdout)] == [Path("sub/inner.txt")]


def test_pattern_matching_nothing_stays_literal(shell: ShellHarness, files: Path) -> None:
    """Check that a wildcard with no match is passed through unchanged"""
    run = shell.run("printf '%s\\n' *.nope")

    assert printed_words(run.stdout) == ["*.nope"]


@pytest.mark.parametrize(
    "script",
    ["printf '%s\\n' '*.md'", "printf '%s\\n' \"*.md\"", "printf '%s\\n' \\*.md"],
    ids=["single-quoted", "double-quoted", "backslash-escaped"],
)
def test_quoted_wildcard_stays_literal(shell: ShellHarness, files: Path, script: str) -> None:
    """Check that quoting a wildcard stops it matching"""
    run = shell.run(script)

    assert printed_words(run.stdout) == ["*.md"]


def test_quoted_bracket_is_literal_beside_an_unquoted_wildcard(shell: ShellHarness, files: Path) -> None:
    """Check that a quoted bracket inside a pattern is literal while the unquoted star still matches"""
    run = shell.run("printf '%s\\n' odd'['*")

    assert printed_words(run.stdout) == ["odd[1].txt"]


def test_wildcard_from_an_unquoted_variable_expands(shell: ShellHarness, files: Path) -> None:
    """Check that a pattern held in a variable matches when the variable is unquoted and not when quoted"""
    run = shell.run("pattern='*.md'; printf '%s\\n' $pattern \"$pattern\"")

    assert printed_words(run.stdout) == ["gamma.md", "*.md"]


def test_for_loop_iterates_over_matches(shell: ShellHarness, files: Path) -> None:
    """Check that the words of a for loop are expanded to paths"""
    run = shell.run('for name in *.txt; do echo "<$name>"; done')

    assert set(printed_words(run.stdout)) == {"<alpha.txt>", "<beta.txt>", "<odd[1].txt>"}


def test_rm_star_removes_every_visible_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that rm with a bare star removes the visible files and keeps the hidden one"""
    for name in ("one.txt", "two.txt", ".keep"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    run = shell.run("rm *")

    assert run.exit_code == 0
    assert {path.name for path in tmp_path.iterdir()} == {".keep"}
