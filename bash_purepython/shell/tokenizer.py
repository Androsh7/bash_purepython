"""Split a command line into words and operators with bash-style quoting"""

# Standard libraries
import re
from collections.abc import Mapping

# Project libraries
from bash_purepython.shell.models import RawWord, ShellSyntaxError, Token, TokenKind, WordPart

WHITESPACE = " \t"
WORD_BREAKERS = WHITESPACE + "|&;><"
DOUBLE_QUOTE_ESCAPABLE = '$"\\`'
VARIABLE_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|\$(\?)")
STDOUT_DESCRIPTOR = "1"
STDERR_DESCRIPTOR = "2"
UNSUPPORTED_REDIRECTION_MESSAGE = "{what} redirection ({form}) is not supported"


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


def expand_word(word: RawWord, environment: Mapping[str, str], home: str, last_exit_code: int) -> str | None:
    """Return the final text of a word, or None when it expands to nothing

    Unquoted parts are variable-expanded and a bare leading ~ means home. A word
    made only of unquoted text that expands to nothing is dropped, as bash drops it,
    while a quoted empty string stays an empty argument

    Args:
        word: The word as the tokenizer saw it
        environment: The variables available for expansion
        home: The directory a bare ~ stands for
        last_exit_code: The value $? expands to

    Returns:
        The expanded word, or None if it vanished
    """
    expanded = "".join(
        part.text if part.quoted else expand_variables(part.text, environment, last_exit_code) for part in word.parts
    )
    if not expanded and not any(part.quoted for part in word.parts):
        return None
    return expand_tilde(expanded, home) if word.bare_tilde else expanded


def read_stderr_redirect(line: str, index: int) -> tuple[Token, int]:
    """Return the stderr redirect token starting at the > after a 2, and the index past it

    Args:
        line: The whole command line
        index: The position of the > that follows the descriptor

    Raises:
        ShellSyntaxError: If stderr is sent to a descriptor other than 1

    Returns:
        The operator token and the position after it
    """
    if line.startswith(">&1", index):
        return Token(TokenKind.REDIRECT_STDERR_TO_STDOUT, "2>&1"), index + 3
    if line.startswith(">&", index):
        raise ShellSyntaxError(UNSUPPORTED_REDIRECTION_MESSAGE.format(what="stderr to descriptor", form="2>&"))
    if line.startswith(">>", index):
        return Token(TokenKind.REDIRECT_STDERR_APPEND, "2>>"), index + 2
    return Token(TokenKind.REDIRECT_STDERR_WRITE, "2>"), index + 1


def read_operator(line: str, index: int) -> tuple[Token, int]:
    """Return the operator token starting at index and the index just past it

    Args:
        line: The whole command line
        index: The position of the operator's first character

    Raises:
        ShellSyntaxError: If a lone & is found, since background jobs are not supported, or
            stdout is sent to a descriptor

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
        if following == ">":
            return Token(TokenKind.REDIRECT_BOTH, "&>"), index + 2
        raise ShellSyntaxError("background jobs are not supported")
    if character == ";":
        return Token(TokenKind.SEMICOLON, ";"), index + 1
    if character == "<":
        return Token(TokenKind.REDIRECT_INPUT, "<"), index + 1
    if following == "&":
        raise ShellSyntaxError(UNSUPPORTED_REDIRECTION_MESSAGE.format(what="stdout to descriptor", form=">&"))
    if following == ">":
        return Token(TokenKind.REDIRECT_APPEND, ">>"), index + 2
    return Token(TokenKind.REDIRECT_WRITE, ">"), index + 1


def read_word(line: str, index: int) -> tuple[RawWord, int]:
    """Return the word starting at index with its quoting resolved into parts, and the index past it

    Single-quoted text is literal, double-quoted text keeps everything but the escapes
    of $, ", backslash and backtick, and unquoted backslashes escape the next character.
    Variables are not expanded here; the parts say which text may be expanded later

    Args:
        line: The whole command line
        index: The position of the word's first character

    Raises:
        ShellSyntaxError: If a quote is left open at the end of the line

    Returns:
        The word's parts and the position after it
    """
    parts: list[WordPart] = []
    plain = ""
    bare_tilde = line[index] == "~"

    def flush_plain() -> None:
        nonlocal plain
        if plain:
            parts.append(WordPart(text=plain, quoted=False))
            plain = ""

    while index < len(line):
        character = line[index]
        if character in WORD_BREAKERS:
            break
        if character == "'":
            flush_plain()
            closing = line.find("'", index + 1)
            if closing == -1:
                raise ShellSyntaxError("unterminated single quote")
            parts.append(WordPart(text=line[index + 1 : closing], quoted=True))
            index = closing + 1
            continue
        if character == '"':
            flush_plain()
            index += 1
            while index < len(line) and line[index] != '"':
                if line[index] == "\\" and index + 1 < len(line) and line[index + 1] in DOUBLE_QUOTE_ESCAPABLE:
                    flush_plain()
                    parts.append(WordPart(text=line[index + 1], quoted=True))
                    index += 2
                    continue
                plain += line[index]
                index += 1
            if index >= len(line):
                raise ShellSyntaxError("unterminated double quote")
            index += 1
            # Text inside double quotes expands but counts as quoted, so "" and "$UNSET" stay arguments
            if plain:
                parts.append(WordPart(text=plain, quoted=False))
                plain = ""
            parts.append(WordPart(text="", quoted=True))
            continue
        if character == "\\" and index + 1 < len(line):
            flush_plain()
            parts.append(WordPart(text=line[index + 1], quoted=True))
            index += 2
            continue
        plain += character
        index += 1
    flush_plain()
    return RawWord(parts=tuple(parts), bare_tilde=bare_tilde), index


def tokenize(line: str) -> list[Token]:
    """Return the words and operators of a command line, words still unexpanded

    Args:
        line: The command line as typed

    Raises:
        ShellSyntaxError: If a quote is left open, a lone & appears, or a descriptor other
            than 1 and 2 is redirected

    Returns:
        The tokens in order
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
        word, index = read_word(line, index)
        raw = line[start:index]
        if raw.isdigit() and index < len(line) and line[index] == ">":
            if raw == STDOUT_DESCRIPTOR:
                continue
            if raw == STDERR_DESCRIPTOR:
                token, index = read_stderr_redirect(line, index)
                tokens.append(token)
                continue
            raise ShellSyntaxError(
                UNSUPPORTED_REDIRECTION_MESSAGE.format(what=f"file descriptor {raw}", form=f"{raw}>")
            )
        tokens.append(Token(TokenKind.WORD, raw, word))
    return tokens
