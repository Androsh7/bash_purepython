"""Split a command line into words and operators with bash-style quoting"""

# Standard libraries
import re
from collections.abc import Mapping

# Project libraries
from bash_purepython.shell.models import ShellSyntaxError, Token, TokenKind

WHITESPACE = " \t"
WORD_BREAKERS = WHITESPACE + "|&;>"
VARIABLE_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|\$(\?)")


def expand_variables(text: str, environment: Mapping[str, str], last_exit_code: int) -> str:
    """Return the text with every $NAME, ${NAME} and $? reference replaced

    Args:
        text: The unquoted or double-quoted text to expand
        environment: The variables available for expansion
        last_exit_code: The value $? expands to

    Returns:
        The text with unknown variables replaced by nothing
    """

    def replace(match: re.Match[str]) -> str:
        if match.group(3) is not None:
            return str(last_exit_code)
        name = match.group(1) or match.group(2)
        return environment.get(name, "")

    return VARIABLE_REFERENCE.sub(replace, text)


def expand_tilde(value: str, home: str) -> str:
    """Return the word with a bare leading tilde replaced by the home directory

    Args:
        value: The finished word
        home: The directory a bare ~ stands for

    Returns:
        The word with ~ or ~/ expanded, or the word unchanged
    """
    if value == "~":
        return home
    if value.startswith("~/"):
        return home + value[1:]
    return value


def read_operator(line: str, index: int) -> tuple[Token, int]:
    """Return the operator token starting at index and the index just past it

    Args:
        line: The whole command line
        index: The position of the operator's first character

    Raises:
        ShellSyntaxError: If a lone & is found, since background jobs are not supported

    Returns:
        The operator token and the position after it
    """
    character = line[index]
    following = line[index + 1] if index + 1 < len(line) else ""
    if character == "|":
        if following == "|":
            return Token(TokenKind.OR, "||"), index + 2
        return Token(TokenKind.PIPE, "|"), index + 1
    if character == "&":
        if following == "&":
            return Token(TokenKind.AND, "&&"), index + 2
        raise ShellSyntaxError("background jobs are not supported")
    if character == ";":
        return Token(TokenKind.SEMICOLON, ";"), index + 1
    if following == ">":
        return Token(TokenKind.REDIRECT_APPEND, ">>"), index + 2
    return Token(TokenKind.REDIRECT_WRITE, ">"), index + 1


def read_word(line: str, index: int, environment: Mapping[str, str], home: str, last_exit_code: int) -> tuple[str, int]:
    """Return the word starting at index with quoting resolved, and the index just past it

    Only unquoted and double-quoted text is variable-expanded, and only a bare unquoted
    leading ~ means home

    Args:
        line: The whole command line
        index: The position of the word's first character
        environment: The variables available for expansion
        home: The directory a bare ~ stands for
        last_exit_code: The value $? expands to

    Raises:
        ShellSyntaxError: If a quote is left open at the end of the line

    Returns:
        The resolved word and the position after it
    """
    value = ""
    plain = ""
    bare_tilde = line[index] == "~"

    def flush_plain() -> str:
        nonlocal plain
        expanded = expand_variables(plain, environment, last_exit_code)
        plain = ""
        return expanded

    while index < len(line):
        character = line[index]
        if character in WORD_BREAKERS:
            break
        if character == "'":
            value += flush_plain()
            closing = line.find("'", index + 1)
            if closing == -1:
                raise ShellSyntaxError("unterminated single quote")
            value += line[index + 1 : closing]
            index = closing + 1
            continue
        if character == '"':
            value += flush_plain()
            index += 1
            while index < len(line) and line[index] != '"':
                if line[index] == "\\" and index + 1 < len(line):
                    value += flush_plain()
                    value += line[index + 1]
                    index += 2
                    continue
                plain += line[index]
                index += 1
            if index >= len(line):
                raise ShellSyntaxError("unterminated double quote")
            index += 1
            value += flush_plain()
            continue
        if character == "\\" and index + 1 < len(line):
            value += flush_plain()
            value += line[index + 1]
            index += 2
            continue
        plain += character
        index += 1
    value += flush_plain()
    return (expand_tilde(value, home) if bare_tilde else value), index


def tokenize(line: str, environment: Mapping[str, str], home: str, last_exit_code: int = 0) -> list[Token]:
    """Return the words and operators of a command line

    Args:
        line: The command line as typed
        environment: The variables available for expansion
        home: The directory a bare ~ stands for
        last_exit_code: The value $? expands to

    Raises:
        ShellSyntaxError: If a quote is left open or a lone & appears

    Returns:
        The tokens in order, with quoting and expansion already applied to words
    """
    tokens: list[Token] = []
    index = 0
    while index < len(line):
        character = line[index]
        if character in WHITESPACE:
            index += 1
            continue
        if character in WORD_BREAKERS:
            token, index = read_operator(line, index)
            tokens.append(token)
            continue
        start = index
        value, index = read_word(line, index, environment, home, last_exit_code)
        was_quoted = any(quote in line[start:index] for quote in "'\"\\")
        if value or was_quoted:
            tokens.append(Token(TokenKind.WORD, value))
    return tokens
