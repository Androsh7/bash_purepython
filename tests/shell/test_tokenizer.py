"""Tests for the command line tokenizer"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import LAST_EXIT_CODE_PLACEHOLDER, ShellSyntaxError, Token, TokenKind
from bash_purepython.shell.tokenizer import tokenize

HOME = "/home/user"
ENVIRONMENT = {"X": "1", "NAME": "world"}


def words(*values: str) -> list[Token]:
    """Return word tokens for each value"""
    return [Token(TokenKind.WORD, value) for value in values]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("echo a b", words("echo", "a", "b")),
        ("echo   a\tb", words("echo", "a", "b")),
        ("echo 'a $X b'", words("echo", "a $X b")),
        ('echo "hi $X"', words("echo", "hi 1")),
        ('echo "\\$X"', words("echo", "$X")),
        ('echo "\\.txt"', words("echo", "\\.txt")),
        ('echo "a\\\\b"', words("echo", "a\\b")),
        ("echo $X", words("echo", "1")),
        ("echo ${X}y", words("echo", "1y")),
        ("echo $MISSING.", words("echo", ".")),
        ("echo a\\ b", words("echo", "a b")),
        ("echo ''", words("echo", "")),
        ("echo a'b'c", words("echo", "abc")),
        ("echo '|' '&&'", words("echo", "|", "&&")),
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
        "adjacent-quotes",
        "quoted-operators",
    ],
)
def test_tokenize_resolves_quoting_and_expansion(line: str, expected: list[Token]) -> None:
    """Check that quoting, escapes and variable expansion follow bash rules"""
    tokens = tokenize(line, ENVIRONMENT, HOME)

    assert tokens == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("cd ~", words("cd", HOME)),
        ("ls ~/x", words("ls", f"{HOME}/x")),
        ("echo '~'", words("echo", "~")),
        ("echo a~", words("echo", "a~")),
        ("echo ~user", words("echo", "~user")),
    ],
    ids=["bare", "with-path", "quoted", "not-leading", "other-user"],
)
def test_tokenize_expands_only_a_bare_leading_tilde(line: str, expected: list[Token]) -> None:
    """Check that ~ means home only when it is unquoted and starts the word"""
    tokens = tokenize(line, ENVIRONMENT, HOME)

    assert tokens == expected


def test_tokenize_marks_question_mark_for_the_session_to_resolve() -> None:
    """Check that $? becomes the placeholder the session fills in per pipeline"""
    tokens = tokenize("echo $?", ENVIRONMENT, HOME)

    assert tokens == words("echo", LAST_EXIT_CODE_PLACEHOLDER)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("a | b", [Token(TokenKind.WORD, "a"), Token(TokenKind.PIPE, "|"), Token(TokenKind.WORD, "b")]),
        ("a||b", [Token(TokenKind.WORD, "a"), Token(TokenKind.OR, "||"), Token(TokenKind.WORD, "b")]),
        ("a&&b", [Token(TokenKind.WORD, "a"), Token(TokenKind.AND, "&&"), Token(TokenKind.WORD, "b")]),
        ("a;b", [Token(TokenKind.WORD, "a"), Token(TokenKind.SEMICOLON, ";"), Token(TokenKind.WORD, "b")]),
        ("a>b", [Token(TokenKind.WORD, "a"), Token(TokenKind.REDIRECT_WRITE, ">"), Token(TokenKind.WORD, "b")]),
        ("a >> b", [Token(TokenKind.WORD, "a"), Token(TokenKind.REDIRECT_APPEND, ">>"), Token(TokenKind.WORD, "b")]),
    ],
    ids=["pipe", "or", "and", "semicolon", "write", "append"],
)
def test_tokenize_recognises_operators_without_spaces(line: str, expected: list[Token]) -> None:
    """Check that every operator is found whether or not it is surrounded by spaces"""
    tokens = tokenize(line, ENVIRONMENT, HOME)

    assert tokens == expected


@pytest.mark.parametrize(
    "line",
    ["echo 'open", 'echo "open', "sleep 1 & echo"],
    ids=["single-quote", "double-quote", "background"],
)
def test_tokenize_raises_on_invalid_syntax(line: str) -> None:
    """Check that an open quote or a lone ampersand is a syntax error"""
    with pytest.raises(ShellSyntaxError):
        tokenize(line, ENVIRONMENT, HOME)


@pytest.mark.parametrize(
    "line",
    ["ls 2>/dev/null", "ls 2>&1 | wc -l", "ls &>out", "ls >&2"],
    ids=["descriptor", "merge", "both", "to-descriptor"],
)
def test_tokenize_rejects_stderr_redirection_by_name(line: str) -> None:
    """Check that every stderr redirection form is refused with a message that names it"""
    with pytest.raises(ShellSyntaxError, match="stderr redirection"):
        tokenize(line, ENVIRONMENT, HOME)
