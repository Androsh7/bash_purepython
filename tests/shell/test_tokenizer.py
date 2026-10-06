"""Tests for the command line tokenizer and word expansion"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import ShellSyntaxError, TokenKind
from bash_purepython.shell.tokenizer import expand_word, expand_word_to_arguments, tokenize

HOME = "/home/user"
ENVIRONMENT = {"X": "1", "NAME": "world"}


def expand_line(line: str, last_exit_code: int = 0) -> list[str | None]:
    """Return each token as its expanded word, or the operator text"""
    expanded: list[str | None] = []
    for token in tokenize(line):
        if token.kind == TokenKind.WORD and token.word is not None:
            expanded.append(expand_word(token.word, ENVIRONMENT, HOME, last_exit_code))
        else:
            expanded.append(token.value)
    return expanded


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("echo a b", ["echo", "a", "b"]),
        ("echo   a\tb", ["echo", "a", "b"]),
        ("echo 'a $X b'", ["echo", "a $X b"]),
        ('echo "hi $X"', ["echo", "hi 1"]),
        ('echo "\\$X"', ["echo", "$X"]),
        ('echo "\\.txt"', ["echo", "\\.txt"]),
        ('echo "a\\\\b"', ["echo", "a\\b"]),
        ("echo $X", ["echo", "1"]),
        ("echo ${X}y", ["echo", "1y"]),
        ("echo $MISSING.", ["echo", "."]),
        ("echo a\\ b", ["echo", "a b"]),
        ("echo ''", ["echo", ""]),
        ('echo "$MISSING"', ["echo", ""]),
        ("echo a'b'c", ["echo", "abc"]),
        ("echo '|' '&&'", ["echo", "|", "&&"]),
    ],
    ids=[
        "plain",
        "mixed-whitespace",
        "single-quotes-literal",
        "double-quotes-expand",
        "escaped-dollar",
        "plain-backslash-kept",
        "escaped-backslash",
        "variable",
        "braced-variable",
        "unknown-variable",
        "escaped-space",
        "empty-quotes",
        "quoted-empty-expansion",
        "adjacent-quotes",
        "quoted-operators",
    ],
)
def test_expand_word_resolves_quoting_and_expansion(line: str, expected: list[str | None]) -> None:
    """Check that quoting, escapes and variable expansion follow bash rules"""
    assert expand_line(line) == expected


def test_expand_word_drops_an_unquoted_word_that_expands_to_nothing() -> None:
    """Check that a bare unset variable vanishes rather than becoming an empty argument"""
    assert expand_line("echo $MISSING end") == ["echo", None, "end"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("cd ~", ["cd", HOME]),
        ("ls ~/x", ["ls", f"{HOME}/x"]),
        ("echo '~'", ["echo", "~"]),
        ("echo a~", ["echo", "a~"]),
        ("echo ~user", ["echo", "~user"]),
    ],
    ids=["bare", "with-path", "quoted", "not-leading", "other-user"],
)
def test_expand_word_expands_only_a_bare_leading_tilde(line: str, expected: list[str | None]) -> None:
    """Check that ~ means home only when it is unquoted and starts the word"""
    assert expand_line(line) == expected


def test_expand_word_expands_question_mark_to_the_given_exit_code() -> None:
    """Check that $? carries the exit code it is expanded with"""
    assert expand_line("echo $?", last_exit_code=3) == ["echo", "3"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("a | b", ["a", "|", "b"]),
        ("a||b", ["a", "||", "b"]),
        ("a&&b", ["a", "&&", "b"]),
        ("a;b", ["a", ";", "b"]),
        ("a>b", ["a", ">", "b"]),
        ("a >> b", ["a", ">>", "b"]),
        ("echo 1>out", ["echo", ">", "out"]),
    ],
    ids=["pipe", "or", "and", "semicolon", "write", "append", "stdout-descriptor"],
)
def test_tokenize_recognises_operators_without_spaces(line: str, expected: list[str | None]) -> None:
    """Check that every operator is found whether or not it is surrounded by spaces"""
    assert expand_line(line) == expected


@pytest.mark.parametrize(
    "line",
    ["echo 'open", 'echo "open', "sleep 1 & echo"],
    ids=["single-quote", "double-quote", "background"],
)
def test_tokenize_raises_on_invalid_syntax(line: str) -> None:
    """Check that an open quote or a lone ampersand is a syntax error"""
    with pytest.raises(ShellSyntaxError):
        tokenize(line)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ls 2>err", ["ls", "2>", "err"]),
        ("ls 2>>err", ["ls", "2>>", "err"]),
        ("ls 2>&1", ["ls", "2>&1"]),
        ("ls &>all", ["ls", "&>", "all"]),
        ("cat <in", ["cat", "<", "in"]),
        ("ls 2 > out", ["ls", "2", ">", "out"]),
    ],
    ids=["stderr-write", "stderr-append", "stderr-to-stdout", "both", "input", "spaced-digit-is-a-word"],
)
def test_tokenize_recognises_stderr_and_input_redirection(line: str, expected: list[str | None]) -> None:
    """Check that the stderr and input forms are operators, and a digit with a space after it is not"""
    assert expand_line(line) == expected


@pytest.mark.parametrize(
    ("line", "expected_message"),
    [
        ("ls 3>out", "file descriptor 3"),
        ("ls >&2", "stdout to descriptor"),
        ("ls 2>&3", "stderr to descriptor"),
    ],
    ids=["other-descriptor", "stdout-to-descriptor", "stderr-to-other"],
)
def test_tokenize_rejects_descriptor_redirection_by_name(line: str, expected_message: str) -> None:
    """Check that descriptor forms the shell cannot honour are refused with a message that names them"""
    with pytest.raises(ShellSyntaxError, match=expected_message):
        tokenize(line)


def arguments_of(line: str, environment: dict[str, str] | None = None) -> list[str]:
    """Return every argument the words of a line become, wildcards included"""
    arguments: list[str] = []
    for token in tokenize(line):
        if token.word is not None:
            arguments.extend(expand_word_to_arguments(token.word, environment or ENVIRONMENT, HOME, 0))
    return arguments


def test_expand_word_to_arguments_matches_files_in_sorted_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that an unquoted star becomes one argument per matching file"""
    monkeypatch.chdir(tmp_path)
    for name in ("b.txt", "a.txt", "c.log"):
        (tmp_path / name).write_text("")

    assert arguments_of("echo *.txt") == ["echo", "a.txt", "b.txt"]


def test_expand_word_to_arguments_keeps_a_pattern_with_no_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that a star that matches nothing is passed through as typed"""
    monkeypatch.chdir(tmp_path)

    assert arguments_of("echo *.none") == ["echo", "*.none"]


def test_expand_word_to_arguments_leaves_quoted_wildcards_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that quoting a wildcard keeps it literal"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("")

    assert arguments_of("echo '*' \"*.txt\" \\*") == ["echo", "*", "*.txt", "*"]


def test_expand_word_to_arguments_skips_hidden_files_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that * ignores dotfiles and .* finds them"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".hidden").write_text("")
    (tmp_path / "shown").write_text("")

    assert arguments_of("echo *") == ["echo", "shown"]
    assert arguments_of("echo .*") == ["echo", ".hidden"]


def test_expand_word_to_arguments_matches_through_a_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that a wildcard inside an unquoted variable value is matched"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "one.log").write_text("")

    assert arguments_of("echo $PATTERN", {"PATTERN": "*.log"}) == ["echo", "one.log"]


def test_expand_word_to_arguments_matches_question_mark_and_brackets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that ? and [...] work as in bash"""
    monkeypatch.chdir(tmp_path)
    for name in ("f1", "f2", "f10"):
        (tmp_path / name).write_text("")

    assert arguments_of("echo f? f[2-9]") == ["echo", "f1", "f2", "f2"]
