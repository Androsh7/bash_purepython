"""Tokenise one simple command into words, redirections and assignments, and expand the words"""

# Standard libraries
import fnmatch
import glob
import itertools
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Project libraries
from bash_purepython.arithmetic import evaluate_arithmetic
from bash_purepython.shell_state import (
    NULL_DEVICE_PATH,
    ExpansionError,
    ShellOption,
    ShellState,
    ShellSyntaxError,
    UnboundVariableError,
)
from bash_purepython.workflow import Redirection, RedirectionKind

WHITESPACE_CHARACTERS = frozenset(" \t\n")
ASSIGNMENT_PATTERN = re.compile(r"^([A-Za-z_]\w*)(?:\[([^\]]+)\])?(\+?)=")
ARRAY_VALUE_START_PATTERN = re.compile(r"^[A-Za-z_]\w*\+?=$")
GLOB_CHARACTER_PATTERN = re.compile(r"[*?\[]")
VARIABLE_NAME_PATTERN = re.compile(r"[A-Za-z_]\w*")
SPECIAL_PARAMETER_CHARACTERS = frozenset("?#@*$!0123456789")
PARAMETER_PATTERN = re.compile(r"^(!?)([A-Za-z_]\w*|[?#@*$!0-9])(?:\[([^\]]+)\])?(.*)$", re.DOTALL)
PARAMETER_OPERATOR_PATTERN = re.compile(r"^(:[-=+?]|[-=+?]|##|#|%%|%|//|/#|/%|/|\^\^|\^|,,|,|:)", re.DOTALL)
DEFAULT_OPERATORS = frozenset({":-", "-", ":=", "=", ":+", "+", ":?", "?"})
REMOVAL_OPERATORS = frozenset({"#", "##", "%", "%%"})
SUBSTITUTION_OPERATORS = frozenset({"/", "//", "/#", "/%"})
SUBSTRING_OPERATOR = ":"
ALL_ELEMENTS_SUBSCRIPTS = frozenset("@*")
ALL_ELEMENTS_EXPANSION_PATTERN = re.compile(r"^(\$@|\$\{@\}|\$\{[A-Za-z_]\w*\[@\]\})$")
FIELD_SEPARATOR_VARIABLE_NAME = "IFS"
DEFAULT_FIELD_SEPARATORS = " \t\n"
RANDOM_VARIABLE_NAME = "RANDOM"
SECONDS_VARIABLE_NAME = "SECONDS"
RANDOM_LIMIT = 32768
SHELL_PID = "1"
DEFAULT_VARIABLES = {"PPID": "0", "SHELL": "/bin/bash", "BASH_VERSION": "5.2.0(1)-bash_purepython"}
ANSI_C_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "e": "\x1b",
    "E": "\x1b",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}
HEXADECIMAL_ESCAPE_PATTERN = re.compile(r"x([0-9A-Fa-f]{1,2})")
UNICODE_ESCAPE_PATTERN = re.compile(r"u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})")
OCTAL_ESCAPE_PATTERN = re.compile(r"0?([0-7]{1,3})")
BRACE_RANGE_PATTERN = re.compile(r"^(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?$")
BRACE_LETTER_RANGE_PATTERN = re.compile(r"^([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?$")
HEREDOC_DELIMITER_PATTERN = re.compile(r"(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|(\\?[^\s;&|()<>'\"]+))")
DOUBLE_QUOTE_ESCAPABLE_CHARACTERS = frozenset('$`"\\\n')
DESCRIPTOR_DUPLICATION_OPERATORS = (">&1", ">&2", ">&-")
STDOUT_DESCRIPTOR = "1"
STDERR_DESCRIPTOR = "2"
CLOSE_DESCRIPTOR_TARGET = "-"
ECHO_ESCAPE_SEQUENCES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
HOME_VARIABLE_NAME = "HOME"
ARITHMETIC_OPENING = "$(("
ARITHMETIC_CLOSING = "))"
SHELL_NAME = "bash"
POSITIONAL_FIELD_SEPARATOR = "\x1f"
ALL_POSITIONAL_SPELLINGS = frozenset({"$@", "${@}"})

RunSubstitution = Callable[[str], Awaitable[str]]


class QuoteStyle(StrEnum):
    """Name how one part of a word was quoted"""

    NONE = "none"
    SINGLE = "single"
    DOUBLE = "double"


@dataclass(frozen=True)
class WordPart:
    """Hold one run of a word that shares a quoting style"""

    text: str
    quote: QuoteStyle


@dataclass(frozen=True)
class Word:
    """Hold one unexpanded word as its quoted parts"""

    parts: list[WordPart]

    def raw_text(self) -> str:
        """Return the parts joined without their quotes

        Returns:
            The word text with quoting removed but expansions untouched
        """
        return "".join(part.text for part in self.parts)


@dataclass(frozen=True)
class Assignment:
    """Hold one ``name=value`` word that preceded the command name

    ``index_text`` is the subscript of ``name[index]=value``, ``append`` marks ``+=``, and ``array_words``
    holds the words of ``name=(...)`` in place of a value
    """

    name: str
    value: Word
    index_text: str | None = None
    append: bool = False
    array_words: list[Word] | None = None


@dataclass(frozen=True)
class SimpleCommandParts:
    """Hold everything a simple command's text was split into"""

    words: list[Word]
    redirections: list[Redirection]
    assignments: list[Assignment]


class SimpleCommandTokenizer:
    """Scan one simple command's text once"""

    def __init__(self, text: str):
        """Prepare to scan one command

        Args:
            text: The command text with any heredoc bodies after its first newline
        """
        self.text = text
        self.position = 0
        self.parts: list[WordPart] = []
        self.words: list[Word] = []
        self.redirections: list[Redirection] = []
        self.assignments: list[Assignment] = []
        self.pending_heredocs: list[tuple[int, bool, bool]] = []
        self.word_started = False
        self.pending_array_words: list[Word] | None = None

    def tokenize(self) -> SimpleCommandParts:
        """Return the words, redirections and assignments of the command

        Raises:
            ShellSyntaxError: If a quote is unclosed or an operator has no target

        Returns:
            The split command
        """
        while self.position < len(self.text):
            self._scan_next()
        self._end_word()
        return SimpleCommandParts(words=self.words, redirections=self.redirections, assignments=self.assignments)

    def _scan_next(self) -> None:
        """Consume the next token at the current position"""
        character = self.text[self.position]
        if character == "\n":
            self._end_word()
            self.position += 1
            if self.pending_heredocs:
                self._consume_heredoc_bodies()
            return
        if character in WHITESPACE_CHARACTERS:
            self._end_word()
            self.position += 1
            return
        if self._try_consume_redirection():
            return
        if character == "'":
            self._consume_single_quoted()
        elif character == '"':
            self._consume_double_quoted()
        elif character == "\\":
            self._consume_escape()
        elif character == "$" and self.text.startswith("$'", self.position):
            self._consume_ansi_c_quoted()
        elif character == "(" and self._at_array_value_start():
            self._consume_array_value()
        elif character == "$" and self.text.startswith(("$(", "${"), self.position):
            opening = self.text[self.position + 1]
            start = self.position
            self.position += 2
            self._skip_balanced(opening, ")" if opening == "(" else "}")
            self._add_part(self.text[start : self.position], QuoteStyle.NONE)
        elif character == "`":
            start = self.position
            self._skip_backticks()
            self._add_part(self.text[start : self.position], QuoteStyle.NONE)
        elif character in "()":
            raise ShellSyntaxError(f"unexpected {character} in command: {self.text}")
        elif character == ";":
            raise ShellSyntaxError("syntax error near unexpected token `;;'")
        else:
            self.position += 1
            self._add_part(character, QuoteStyle.NONE)

    def _add_part(self, text: str, quote: QuoteStyle) -> None:
        """Append text to the current word, merging with the previous part when the quoting matches

        Args:
            text: The text to append, with quotes removed
            quote: How the text was quoted
        """
        self.word_started = True
        if self.parts and self.parts[-1].quote == quote:
            self.parts[-1] = WordPart(text=self.parts[-1].text + text, quote=quote)
        else:
            self.parts.append(WordPart(text=text, quote=quote))

    def _end_word(self) -> None:
        """Finish the current word, classifying it as an assignment when it precedes the command name"""
        if not self.word_started:
            return
        word = Word(parts=self.parts)
        self.parts = []
        self.word_started = False
        array_words = self.pending_array_words
        self.pending_array_words = None
        assignment = self._as_assignment(word, array_words)
        if assignment is not None and not self.words:
            self.assignments.append(assignment)
        else:
            self.words.append(word)

    def _as_assignment(self, word: Word, array_words: list[Word] | None) -> Assignment | None:
        """Return the assignment a word denotes, or None when it is an ordinary word

        Args:
            word: The finished word
            array_words: The words of a parenthesised value that followed the equals sign, or None

        Returns:
            The assignment, or None
        """
        if not word.parts or word.parts[0].quote != QuoteStyle.NONE:
            return None
        match = ASSIGNMENT_PATTERN.match(word.parts[0].text)
        if match is None:
            return None
        first_remainder = word.parts[0].text[match.end() :]
        value_parts = [WordPart(text=first_remainder, quote=QuoteStyle.NONE), *word.parts[1:]]
        return Assignment(
            name=match.group(1),
            value=Word(parts=[part for part in value_parts if part.text]),
            index_text=match.group(2),
            append=match.group(3) == "+",
            array_words=array_words,
        )

    def _at_array_value_start(self) -> bool:
        """Return whether the word so far is ``name=`` or ``name+=``, so a parenthesis opens an array value"""
        return (
            len(self.parts) == 1
            and self.parts[0].quote == QuoteStyle.NONE
            and ARRAY_VALUE_START_PATTERN.match(self.parts[0].text) is not None
        )

    def _consume_array_value(self) -> None:
        """Consume the parenthesised words of an array assignment

        Raises:
            ShellSyntaxError: If the parenthesis never closes
        """
        start = self.position + 1
        self.position = start
        self._skip_balanced("(", ")")
        inner = SimpleCommandTokenizer(self.text[start : self.position - 1]).tokenize()
        leading = [
            Word(parts=[WordPart(text=f"{assignment.name}=", quote=QuoteStyle.NONE), *assignment.value.parts])
            for assignment in inner.assignments
        ]
        self.pending_array_words = [*leading, *inner.words]

    def _consume_ansi_c_quoted(self) -> None:
        """Consume a ``$'...'`` string, decoding its backslash escapes

        Raises:
            ShellSyntaxError: If the quote never closes
        """
        index = self.position + 2
        while index < len(self.text) and self.text[index] != "'":
            index += 2 if self.text[index] == "\\" else 1
        if index >= len(self.text):
            raise ShellSyntaxError(f"unclosed single quote: {self.text}")
        self._add_part(decode_ansi_c_escapes(self.text[self.position + 2 : index]), QuoteStyle.SINGLE)
        self.position = index + 1

    def _consume_single_quoted(self) -> None:
        """Consume a single-quoted string"""
        closing_index = self.text.find("'", self.position + 1)
        if closing_index == -1:
            raise ShellSyntaxError(f"unclosed single quote: {self.text}")
        self._add_part(self.text[self.position + 1 : closing_index], QuoteStyle.SINGLE)
        self.position = closing_index + 1

    def _consume_double_quoted(self) -> None:
        """Consume a double-quoted string, keeping its expansions and escapes raw for the expander"""
        start = self.position + 1
        self.position = start
        while self.position < len(self.text):
            character = self.text[self.position]
            if character == "\\":
                self.position += 2
            elif character == '"':
                self._add_part(self.text[start : self.position], QuoteStyle.DOUBLE)
                self.position += 1
                return
            elif character == "`":
                self._skip_backticks()
            elif self.text.startswith("$(", self.position):
                self.position += 2
                self._skip_balanced("(", ")")
            elif self.text.startswith("${", self.position):
                self.position += 2
                self._skip_balanced("{", "}")
            else:
                self.position += 1
        raise ShellSyntaxError(f"unclosed double quote: {self.text}")

    def _consume_escape(self) -> None:
        """Consume a backslash and the character it protects"""
        if self.position + 1 >= len(self.text):
            self._add_part("\\", QuoteStyle.SINGLE)
            self.position += 1
            return
        escaped = self.text[self.position + 1]
        self.position += 2
        if escaped != "\n":
            self._add_part(escaped, QuoteStyle.SINGLE)

    def _skip_balanced(self, opening: str, closing: str) -> None:
        """Advance past the bracket balancing an already consumed opening bracket

        Args:
            opening: The opening bracket character
            closing: The closing bracket character

        Raises:
            ShellSyntaxError: If the brackets never balance
        """
        depth = 1
        while self.position < len(self.text) and depth > 0:
            character = self.text[self.position]
            if character == "\\":
                self.position += 2
            elif character == "'":
                closing_index = self.text.find("'", self.position + 1)
                self.position = len(self.text) if closing_index == -1 else closing_index + 1
            elif character == '"':
                self._skip_double_quoted()
            elif character == "`":
                self._skip_backticks()
            else:
                if character == opening:
                    depth += 1
                elif character == closing:
                    depth -= 1
                self.position += 1
        if depth > 0:
            raise ShellSyntaxError(f"unbalanced {opening}: {self.text}")

    def _skip_double_quoted(self) -> None:
        """Advance past a double-quoted string without recording it"""
        self.position += 1
        while self.position < len(self.text):
            character = self.text[self.position]
            if character == "\\":
                self.position += 2
            elif character == '"':
                self.position += 1
                return
            else:
                self.position += 1

    def _skip_backticks(self) -> None:
        """Advance past a backtick substitution"""
        self.position += 1
        while self.position < len(self.text):
            character = self.text[self.position]
            self.position += 2 if character == "\\" else 1
            if character == "`":
                return
        raise ShellSyntaxError(f"unclosed backtick: {self.text}")

    def _try_consume_redirection(self) -> bool:
        """Consume a redirection operator and its target if one starts at the current position

        Returns:
            True when a redirection was consumed
        """
        remaining = self.text[self.position :]
        if remaining[0] not in "<>&":
            return False
        descriptor_prefix = ""
        if self.word_started:
            if len(self.parts) == 1 and self.parts[0].quote == QuoteStyle.NONE and self.parts[0].text in ("1", "2"):
                descriptor_prefix = self.parts[0].text
            else:
                self._end_word()
        duplication = self._match_descriptor_duplication(remaining, descriptor_prefix)
        if duplication is not None:
            operator_length, redirection = duplication
            if descriptor_prefix:
                self.parts = []
                self.word_started = False
            self.position += operator_length
            if redirection is not None:
                self.redirections.append(redirection)
            return True
        kind = self._match_redirection_kind(remaining, descriptor_prefix)
        if kind is None:
            if descriptor_prefix:
                return False
            raise ShellSyntaxError(f"unsupported redirection: {self.text}")
        if descriptor_prefix:
            self.parts = []
            self.word_started = False
        self.position += self._operator_length(kind, descriptor_prefix)
        if kind == RedirectionKind.HEREDOC:
            self._consume_heredoc_operator()
            return True
        target = self._consume_target_word()
        self.redirections.append(Redirection(kind=kind, target=target))
        return True

    def _match_descriptor_duplication(
        self, remaining: str, descriptor_prefix: str
    ) -> tuple[int, Redirection | None] | None:
        """Return the redirection a ``>&1``, ``>&2`` or ``>&-`` form denotes, given the descriptor before it

        Pointing a descriptor at itself changes nothing, so it consumes the operator and records no redirection.
        Closing a descriptor is recorded as sending it to the null device

        Args:
            remaining: The text from the current position
            descriptor_prefix: ``1``, ``2`` or empty, which means ``1``

        Returns:
            The operator length and the redirection to record or None, or None when the text is another operator
        """
        operator = next(
            (candidate for candidate in DESCRIPTOR_DUPLICATION_OPERATORS if remaining.startswith(candidate)), None
        )
        if operator is None:
            return None
        source = descriptor_prefix or STDOUT_DESCRIPTOR
        target = operator[-1]
        if target == CLOSE_DESCRIPTOR_TARGET:
            kind = RedirectionKind.WRITE_STDERR if source == STDERR_DESCRIPTOR else RedirectionKind.WRITE_STDOUT
            return len(operator), Redirection(kind=kind, target=NULL_DEVICE_PATH)
        if target == source:
            return len(operator), None
        kind = RedirectionKind.STDERR_TO_STDOUT if source == STDERR_DESCRIPTOR else RedirectionKind.STDOUT_TO_STDERR
        return len(operator), Redirection(kind=kind, target="")

    def _match_redirection_kind(self, remaining: str, descriptor_prefix: str) -> RedirectionKind | None:
        """Return the redirection kind starting the remaining text, given the descriptor digit before it

        Args:
            remaining: The text from the current position
            descriptor_prefix: ``1``, ``2`` or empty

        Returns:
            The kind, or None when the text is not a supported redirection
        """
        if descriptor_prefix == "2":
            if remaining.startswith(">>"):
                return RedirectionKind.APPEND_STDERR
            if remaining.startswith(">"):
                return RedirectionKind.WRITE_STDERR
            return None
        if descriptor_prefix == "1" and not remaining.startswith(">"):
            return None
        if remaining.startswith("&>"):
            return RedirectionKind.WRITE_BOTH if not descriptor_prefix else None
        if remaining.startswith(">>"):
            return RedirectionKind.APPEND_STDOUT
        if remaining.startswith(">&") or remaining.startswith("<&"):
            return None
        if remaining.startswith(">"):
            return RedirectionKind.WRITE_STDOUT
        if remaining.startswith("<<<"):
            return RedirectionKind.HERE_STRING
        if remaining.startswith("<<"):
            return RedirectionKind.HEREDOC
        if remaining.startswith("<"):
            return RedirectionKind.READ_STDIN
        return None

    def _operator_length(self, kind: RedirectionKind, descriptor_prefix: str) -> int:
        """Return how many characters the operator occupies after any descriptor digit

        Args:
            kind: The matched kind
            descriptor_prefix: The digit before the operator, or empty

        Returns:
            The operator length
        """
        if kind in (RedirectionKind.WRITE_STDERR, RedirectionKind.APPEND_STDERR):
            return len(kind.value) - len(descriptor_prefix)
        return len(kind.value)

    def _consume_target_word(self) -> str:
        """Return the raw word after a redirection operator

        Raises:
            ShellSyntaxError: If no word follows

        Returns:
            The target word with its quotes still present
        """
        while self.position < len(self.text) and self.text[self.position] in " \t":
            self.position += 1
        start = self.position
        while self.position < len(self.text) and self.text[self.position] not in " \t\n<>|&;":
            character = self.text[self.position]
            if character == "'":
                closing_index = self.text.find("'", self.position + 1)
                self.position = len(self.text) if closing_index == -1 else closing_index + 1
            elif character == '"':
                self._skip_double_quoted()
            elif character == "\\":
                self.position += 2
            elif self.text.startswith(("$(", "${"), self.position):
                opening = self.text[self.position + 1]
                self.position += 2
                self._skip_balanced(opening, ")" if opening == "(" else "}")
            elif character == "`":
                self._skip_backticks()
            else:
                self.position += 1
        if start == self.position:
            raise ShellSyntaxError(f"redirection without a target: {self.text}")
        return self.text[start : self.position]

    def _consume_heredoc_operator(self) -> None:
        """Record a heredoc whose body follows the first newline after the command"""
        match = HEREDOC_DELIMITER_PATTERN.match(self.text, self.position)
        if match is None:
            raise ShellSyntaxError(f"heredoc without a delimiter: {self.text}")
        strip_leading_tabs = match.group(1) == "-"
        quoted = match.group(2) is not None or match.group(3) is not None or match.group(4).startswith("\\")
        delimiter = match.group(2) or match.group(3) or match.group(4).removeprefix("\\")
        self.position = match.end()
        self.redirections.append(Redirection(kind=RedirectionKind.HEREDOC, target="", expand_target=not quoted))
        self.pending_heredocs.append((len(self.redirections) - 1, strip_leading_tabs, delimiter))

    def _consume_heredoc_bodies(self) -> None:
        """Read every pending heredoc body and store it on its redirection"""
        for redirection_index, strip_leading_tabs, delimiter in self.pending_heredocs:
            body_lines: list[str] = []
            while self.position < len(self.text):
                newline_index = self.text.find("\n", self.position)
                line_end = len(self.text) if newline_index == -1 else newline_index
                line = self.text[self.position : line_end]
                self.position = min(line_end + 1, len(self.text))
                if strip_leading_tabs:
                    line = line.lstrip("\t")
                if line == delimiter:
                    break
                body_lines.append(line + "\n")
            previous = self.redirections[redirection_index]
            self.redirections[redirection_index] = Redirection(
                kind=previous.kind, target="".join(body_lines), expand_target=previous.expand_target
            )
        self.pending_heredocs.clear()


def decode_ansi_c_escapes(text: str) -> str:
    """Return the body of a ``$'...'`` string with its escapes replaced

    Args:
        text: The text between the quotes

    Returns:
        The decoded text, with an unknown escape kept as written
    """
    pieces: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character != "\\" or index + 1 >= len(text):
            pieces.append(character)
            index += 1
            continue
        escaped = text[index + 1]
        if escaped in ANSI_C_ESCAPES:
            pieces.append(ANSI_C_ESCAPES[escaped])
            index += 2
            continue
        hexadecimal = HEXADECIMAL_ESCAPE_PATTERN.match(text, index + 1)
        unicode_match = UNICODE_ESCAPE_PATTERN.match(text, index + 1)
        octal = OCTAL_ESCAPE_PATTERN.match(text, index + 1)
        if hexadecimal is not None:
            pieces.append(chr(int(hexadecimal.group(1), 16)))
            index = hexadecimal.end()
        elif unicode_match is not None:
            pieces.append(chr(int(unicode_match.group(1) or unicode_match.group(2), 16)))
            index = unicode_match.end()
        elif octal is not None:
            pieces.append(chr(int(octal.group(1), 8)))
            index = octal.end()
        else:
            pieces.append("\\" + escaped)
            index += 2
    return "".join(pieces)


def tokenize_simple_command(text: str) -> tuple[list[Word], list[Redirection], list[Assignment]]:
    """Return the words, redirections and assignments of one simple command

    Args:
        text: The command text, with heredoc bodies after its first newline

    Raises:
        ShellSyntaxError: If quoting or a redirection is malformed

    Returns:
        The words in order, the redirections in order, and the leading assignments
    """
    parts = SimpleCommandTokenizer(text).tokenize()
    return parts.words, parts.redirections, parts.assignments


def lookup_parameter(name: str, state: ShellState) -> str:
    """Return the value of a variable or special parameter, empty when unset

    An array name stands for its first element. ``$*`` joins the positional arguments with the first
    character of ``IFS``

    Args:
        name: A variable name, a digit, or one of ``? # @ * $ ! 0``
        state: The shell state holding variables, positional arguments and the last exit code

    Returns:
        The value as text
    """
    if name == "?":
        return str(state.last_exit_code)
    if name == "#":
        return str(len(state.positional_arguments))
    if name == "@":
        return " ".join(state.positional_arguments)
    if name == "*":
        return field_separators(state)[:1].join(state.positional_arguments)
    if name == "0":
        return SHELL_NAME
    if name == "!":
        return "" if state.last_background_pid is None else str(state.last_background_pid)
    if name == "$":
        return SHELL_PID
    if name.isdigit():
        index = int(name) - 1
        return state.positional_arguments[index] if 0 <= index < len(state.positional_arguments) else ""
    if name in state.variables:
        return state.variables[name]
    if name in state.arrays:
        return state.arrays[name].get(0, "")
    if name == HOME_VARIABLE_NAME:
        return str(Path.home())
    if name == RANDOM_VARIABLE_NAME:
        return str(random.randrange(RANDOM_LIMIT))
    if name == SECONDS_VARIABLE_NAME:
        return str(int(time.monotonic() - state.started_at))
    return DEFAULT_VARIABLES.get(name, "")


def check_unset(name: str, state: ShellState) -> None:
    """Raise when an unset variable is expanded while ``set -u`` is on

    Args:
        name: The variable name
        state: The shell state holding the options

    Raises:
        ExpansionError: If the option is on and the name is an ordinary variable or positional argument
    """
    if ShellOption.NOUNSET not in state.options:
        return
    if name in DEFAULT_VARIABLES or name in (HOME_VARIABLE_NAME, RANDOM_VARIABLE_NAME, SECONDS_VARIABLE_NAME):
        return
    if VARIABLE_NAME_PATTERN.fullmatch(name) or (name.isdigit() and name != "0"):
        raise UnboundVariableError(f"{name}: unbound variable")


def field_separators(state: ShellState) -> str:
    """Return the characters that separate fields during word splitting

    Args:
        state: The shell state holding ``IFS``

    Returns:
        The value of ``IFS``, or space, tab and newline when it is unset
    """
    return state.variables.get(FIELD_SEPARATOR_VARIABLE_NAME, DEFAULT_FIELD_SEPARATORS)


def split_fields(text: str, separators: str) -> list[str | None]:
    """Return the text as field tokens with None marking each boundary between fields

    Runs of whitespace separators form one boundary and are dropped from the ends. A separator that is
    not whitespace always ends a field, so two in a row produce an empty field, as bash does

    Args:
        text: The expanded text
        separators: The characters that separate fields

    Returns:
        Text pieces and None boundaries, in order
    """
    whitespace = "".join(character for character in separators if character in WHITESPACE_CHARACTERS)
    others = "".join(character for character in separators if character not in WHITESPACE_CHARACTERS)
    if whitespace:
        text = text.strip(whitespace)
    tokens: list[str | None] = []
    current = ""
    index = 0
    while index < len(text):
        character = text[index]
        if character in whitespace:
            while index < len(text) and text[index] in whitespace:
                index += 1
            if index < len(text) and text[index] in others:
                index += 1
                while index < len(text) and text[index] in whitespace:
                    index += 1
                tokens.extend([current, None])
            elif index < len(text):
                tokens.extend([current, None])
            current = ""
            continue
        if character in others:
            index += 1
            while index < len(text) and text[index] in whitespace:
                index += 1
            tokens.extend([current, None])
            current = ""
            continue
        current += character
        index += 1
    if current or not tokens:
        tokens.append(current)
    return tokens


def array_elements(name: str, state: ShellState) -> dict[int, str]:
    """Return the elements of an array by index, treating a scalar as an array with one element

    Args:
        name: The array name, or ``@``/``*`` for the positional arguments
        state: The shell state holding arrays and variables

    Returns:
        The elements in index order
    """
    if name in ALL_ELEMENTS_SUBSCRIPTS:
        return dict(enumerate(state.positional_arguments, start=1))
    if name in state.arrays:
        return dict(sorted(state.arrays[name].items()))
    if name in state.variables:
        return {0: state.variables[name]}
    return {}


async def resolve_array_index(
    index_text: str, element_count: int, state: ShellState, run_substitution: RunSubstitution
) -> int:
    """Return the index an array subscript names, counting a negative one back from the end

    Args:
        index_text: The subscript text, an arithmetic expression
        element_count: How many elements the array has, for negative subscripts
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Raises:
        ExpansionError: If a negative subscript reaches before the first element

    Returns:
        The index
    """
    expanded = await expand_text(index_text, state, run_substitution, in_double_quotes=False)
    index = evaluate_arithmetic(expanded, state)
    if index < 0:
        index += element_count
        if index < 0:
            raise ExpansionError(f"{index_text}: bad array subscript")
    return index


def glob_to_regex(pattern: str, anchor_start: bool = False, anchor_end: bool = False) -> re.Pattern[str]:
    """Return a regular expression matching what a shell pattern matches anywhere in a string

    Args:
        pattern: A pattern with ``*``, ``?`` and ``[...]``
        anchor_start: Whether the match must start at the beginning
        anchor_end: Whether the match must end at the end

    Returns:
        The compiled expression
    """
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\" and index + 1 < len(pattern):
            pieces.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if character == "*":
            pieces.append(".*")
        elif character == "?":
            pieces.append(".")
        elif character == "[":
            closing = pattern.find("]", index + 1)
            if closing == -1:
                pieces.append(re.escape(character))
            else:
                body = pattern[index + 1 : closing]
                if body.startswith("!"):
                    body = "^" + body[1:]
                pieces.append("[" + body.replace("\\", "\\\\") + "]")
                index = closing
        else:
            pieces.append(re.escape(character))
        index += 1
    return re.compile(("^" if anchor_start else "") + "".join(pieces) + ("$" if anchor_end else ""), re.DOTALL)


def remove_pattern(value: str, pattern: str, from_start: bool, longest: bool) -> str:
    """Return the value with the matching prefix or suffix removed, as ``#`` ``##`` ``%`` ``%%`` do

    Args:
        value: The text to trim
        pattern: The shell pattern to remove
        from_start: Whether to remove a prefix rather than a suffix
        longest: Whether the longest match wins rather than the shortest

    Returns:
        The trimmed value
    """
    lengths = range(len(value) + 1)
    for length in reversed(lengths) if longest else lengths:
        candidate = value[:length] if from_start else value[len(value) - length :]
        if fnmatch.fnmatchcase(candidate, pattern):
            return value[length:] if from_start else value[: len(value) - length]
    return value


def substitute_pattern(value: str, operand: str, operator: str) -> str:
    """Return the value with a pattern replaced, as ``/`` ``//`` ``/#`` ``/%`` do

    Args:
        value: The text to edit
        operand: The ``pattern/replacement`` text, where the replacement may be omitted
        operator: Which of the four substitution operators was written

    Returns:
        The edited value
    """
    pattern, _, replacement = split_substitution_operand(operand)
    anchored_start = operator == "/#"
    anchored_end = operator == "/%"
    expression = glob_to_regex(pattern, anchor_start=anchored_start, anchor_end=anchored_end)
    count = 0 if operator == "//" else 1
    return expression.sub(lambda match: replacement, value, count=count)


def split_substitution_operand(operand: str) -> tuple[str, str, str]:
    """Return the pattern and replacement of a ``/`` operand, split at the first unescaped slash

    Args:
        operand: The text after the operator

    Returns:
        The pattern, the slash when one was present, and the replacement
    """
    index = 0
    while index < len(operand):
        if operand[index] == "\\":
            index += 2
            continue
        if operand[index] == "/":
            return operand[:index], "/", operand[index + 1 :]
        index += 1
    return operand, "", ""


def modify_case(value: str, pattern: str, operator: str) -> str:
    """Return the value with its case changed, as ``^`` ``^^`` ``,`` ``,,`` do

    Args:
        value: The text to change
        pattern: A pattern a character must match to change, or empty for every character
        operator: Which of the four case operators was written

    Returns:
        The changed value
    """
    upper = operator.startswith("^")
    first_only = len(operator) == 1
    characters = list(value)
    for index, character in enumerate(characters):
        if pattern and not fnmatch.fnmatchcase(character, pattern):
            continue
        characters[index] = character.upper() if upper else character.lower()
        if first_only:
            break
    return "".join(characters)


async def expand_operand(
    operand: str, state: ShellState, run_substitution: RunSubstitution, in_double_quotes: bool
) -> str:
    """Return the word after a ``${name:-...}`` style operator, expanded as bash expands it

    Outside double quotes the operand is a word of its own, so its quotes are removed; inside them it is plain text

    Args:
        operand: The raw operand text
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output
        in_double_quotes: Whether the whole expansion sits inside double quotes

    Returns:
        The expanded operand
    """
    if not in_double_quotes:
        try:
            words, redirections, assignments = tokenize_simple_command(operand)
        except ShellSyntaxError:
            words, redirections, assignments = [], [], []
        if len(words) == 1 and not redirections and not assignments:
            return await expand_word_unsplit(words[0], state, run_substitution)
    return await expand_text(operand, state, run_substitution, in_double_quotes=True)


@dataclass
class ParameterReference:
    """Hold what a ``${...}`` expression names before any operator is applied"""

    name: str
    values: list[str]
    is_set: bool
    all_elements: bool
    joiner: str


async def resolve_parameter_reference(
    name: str,
    subscript: str | None,
    state: ShellState,
    run_substitution: RunSubstitution,
    split_positional: bool,
) -> ParameterReference:
    """Return the values a parameter name with an optional subscript stands for

    Args:
        name: The variable, array or special parameter name
        subscript: The text inside ``[ ]`` after the name, or None
        state: The shell state to read from
        run_substitution: Runs a script and returns its output
        split_positional: Whether every element of ``@`` is kept apart with the field separator

    Returns:
        The reference with its values and whether it counts as set
    """
    if subscript is None and name not in ALL_ELEMENTS_SUBSCRIPTS:
        value = lookup_parameter(name, state)
        is_set = (
            name in state.variables
            or name in state.arrays
            or (name.isdigit() and value != "")
            or name in SPECIAL_PARAMETER_CHARACTERS
        )
        return ParameterReference(name=name, values=[value], is_set=is_set, all_elements=False, joiner="")
    elements = array_elements(name, state)
    if subscript is None or subscript in ALL_ELEMENTS_SUBSCRIPTS:
        whole = subscript if subscript is not None else name
        if whole == "@" and split_positional:
            joiner = POSITIONAL_FIELD_SEPARATOR
        elif whole == "*":
            joiner = field_separators(state)[:1]
        else:
            joiner = " "
        return ParameterReference(
            name=name, values=list(elements.values()), is_set=bool(elements), all_elements=True, joiner=joiner
        )
    index = await resolve_array_index(subscript, len(elements), state, run_substitution)
    return ParameterReference(
        name=name, values=[elements.get(index, "")], is_set=index in elements, all_elements=False, joiner=""
    )


async def expand_braced_parameter(
    expression: str,
    state: ShellState,
    run_substitution: RunSubstitution,
    in_double_quotes: bool = True,
    split_positional: bool = False,
) -> str:
    """Return the value of a ``${...}`` expression

    Supports lengths (``#``), indirection (``!``), array subscripts, defaults and alternatives
    (``:- - := = :+ + :? ?``), substrings (``:offset:length``), prefix and suffix removal (``# ## % %%``),
    substitution (``/ // /# /%``) and case modification (``^ ^^ , ,,``), each applied to every element
    when the subscript is ``@`` or ``*``

    Args:
        expression: The text between the braces
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output, for operands holding substitutions
        in_double_quotes: Whether the expansion sits inside double quotes, which keeps operand quotes literal
        split_positional: Whether ``${@}`` and ``${name[@]}`` keep elements apart with the field separator

    Raises:
        ShellSyntaxError: If the expression uses an operator this shell does not support

    Returns:
        The expanded value
    """
    if expression == "#":
        return lookup_parameter("#", state)
    if expression.startswith("#") and len(expression) > 1:
        return await parameter_length(expression[1:], state, run_substitution)
    match = PARAMETER_PATTERN.match(expression)
    if match is None:
        raise ExpansionError(f"${{{expression}}}: bad substitution")
    indirect, name, subscript, rest = match.group(1) == "!", match.group(2), match.group(3), match.group(4)
    if indirect:
        if subscript in ALL_ELEMENTS_SUBSCRIPTS:
            keys = " ".join(str(index) for index in array_elements(name, state))
            return (
                keys
                if not rest
                else await apply_parameter_operator(
                    ParameterReference(name, keys.split(), bool(keys), True, " "),
                    rest,
                    state,
                    run_substitution,
                    in_double_quotes,
                )
            )
        name, subscript = lookup_parameter(name, state), None
        if not VARIABLE_NAME_PATTERN.fullmatch(name):
            raise ExpansionError(f"${{{expression}}}: bad substitution")
    reference = await resolve_parameter_reference(name, subscript, state, run_substitution, split_positional)
    if not rest:
        if not reference.is_set:
            check_unset(name, state)
        return reference.joiner.join(reference.values)
    return await apply_parameter_operator(reference, rest, state, run_substitution, in_double_quotes)


async def parameter_length(expression: str, state: ShellState, run_substitution: RunSubstitution) -> str:
    """Return the length a ``${#...}`` expression asks for

    Args:
        expression: The text after ``#``: a name, ``@``, ``*``, or a subscripted name
        state: The shell state to read from
        run_substitution: Runs a script and returns its output

    Raises:
        ExpansionError: If the text is not a parameter

    Returns:
        The number of elements for ``@``, ``*`` or an ``[@]`` subscript, otherwise the length of the value
    """
    match = PARAMETER_PATTERN.match(expression)
    if match is None or match.group(1) or match.group(4):
        raise ExpansionError(f"${{#{expression}}}: bad substitution")
    reference = await resolve_parameter_reference(match.group(2), match.group(3), state, run_substitution, False)
    if reference.all_elements:
        return str(len(reference.values))
    return str(len(reference.values[0]))


async def apply_parameter_operator(
    reference: ParameterReference,
    rest: str,
    state: ShellState,
    run_substitution: RunSubstitution,
    in_double_quotes: bool,
) -> str:
    """Return the result of the operator written after a parameter name

    Args:
        reference: The parameter and its values
        rest: The operator and its operand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output
        in_double_quotes: Whether the expansion sits inside double quotes

    Raises:
        ExpansionError: If the operator is unknown, or a ``?`` operator finds the parameter unset

    Returns:
        The expanded value
    """
    operator_match = PARAMETER_OPERATOR_PATTERN.match(rest)
    if operator_match is None:
        raise ExpansionError(f"${{{reference.name}{rest}}}: bad substitution")
    operator = operator_match.group(1)
    operand = rest[operator_match.end() :]
    joined = reference.joiner.join(reference.values)
    if operator in DEFAULT_OPERATORS:
        return await apply_default_operator(
            reference, operator, operand, joined, state, run_substitution, in_double_quotes
        )
    if operator == SUBSTRING_OPERATOR:
        return await apply_substring_operator(reference, operand, state, run_substitution)
    pattern = await expand_text(operand, state, run_substitution, in_double_quotes=False)
    if operator in REMOVAL_OPERATORS:
        from_start = operator.startswith("#")
        longest = len(operator) == 2
        values = [remove_pattern(value, pattern, from_start, longest) for value in reference.values]
    elif operator in SUBSTITUTION_OPERATORS:
        values = [substitute_pattern(value, pattern, operator) for value in reference.values]
    else:
        values = [modify_case(value, pattern, operator) for value in reference.values]
    return reference.joiner.join(values)


async def apply_default_operator(
    reference: ParameterReference,
    operator: str,
    operand: str,
    joined: str,
    state: ShellState,
    run_substitution: RunSubstitution,
    in_double_quotes: bool,
) -> str:
    """Return the value chosen by a ``- = + ?`` operator, with or without its colon

    Args:
        reference: The parameter and its values
        operator: The operator text
        operand: The word after the operator
        joined: The parameter's value as one string
        state: The shell state, assigned to by ``=``
        run_substitution: Runs a script and returns its output
        in_double_quotes: Whether the expansion sits inside double quotes

    Raises:
        ExpansionError: If a ``?`` operator finds the parameter unset or empty

    Returns:
        The chosen value
    """
    treat_empty_as_unset = operator.startswith(":")
    missing = not reference.is_set or (treat_empty_as_unset and joined == "")
    if operator.endswith("-"):
        return await expand_operand(operand, state, run_substitution, in_double_quotes) if missing else joined
    if operator.endswith("+"):
        return "" if missing else await expand_operand(operand, state, run_substitution, in_double_quotes)
    if operator.endswith("="):
        if missing:
            joined = await expand_operand(operand, state, run_substitution, in_double_quotes)
            state.variables[reference.name] = joined
        return joined
    if missing:
        message = (
            await expand_operand(operand, state, run_substitution, in_double_quotes) or "parameter null or not set"
        )
        raise ExpansionError(f"{reference.name}: {message}")
    return joined


async def apply_substring_operator(
    reference: ParameterReference, operand: str, state: ShellState, run_substitution: RunSubstitution
) -> str:
    """Return the part of the value an ``:offset:length`` operator selects

    Args:
        reference: The parameter and its values, sliced element-wise when it names every element
        operand: The offset, optionally followed by a colon and a length, each an arithmetic expression
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        The selected text or elements
    """
    offset_text, _, length_text = operand.partition(":")
    offset = evaluate_arithmetic(await expand_text(offset_text, state, run_substitution, in_double_quotes=False), state)
    length = None
    if length_text.strip():
        length = evaluate_arithmetic(
            await expand_text(length_text, state, run_substitution, in_double_quotes=False), state
        )
    if reference.all_elements:
        items: list[str] = reference.values
        if reference.name in ALL_ELEMENTS_SUBSCRIPTS and offset > 0:
            offset -= 1
    else:
        items = list(reference.values[0])
    if offset < 0:
        offset = max(len(items) + offset, 0)
    stop = len(items) if length is None else (offset + length if length >= 0 else len(items) + length)
    selected = items[offset:stop]
    return reference.joiner.join(selected) if reference.all_elements else "".join(selected)


def find_balanced_end(text: str, start: int, opening: str, closing: str) -> int:
    """Return the index just past the bracket balancing the one at start

    Args:
        text: The text to scan
        start: The index of the opening bracket
        opening: The opening bracket character
        closing: The closing bracket character

    Raises:
        ShellSyntaxError: If the brackets never balance

    Returns:
        The index after the closing bracket
    """
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ShellSyntaxError(f"unbalanced {opening}: {text}")


def find_arithmetic_end(text: str, start: int) -> int | None:
    """Return where an arithmetic expansion starting at a position ends, or None when it is not one

    ``$((`` opens an arithmetic expansion only when the two opening parentheses are closed together by
    ``))``; otherwise it is a command substitution whose command starts with a subshell

    Args:
        text: The text being expanded
        start: The position of the dollar sign

    Returns:
        The position just past the closing ``))``, or None
    """
    if not text.startswith(ARITHMETIC_OPENING, start):
        return None
    try:
        outer_end = find_balanced_end(text, start + 1, "(", ")")
        inner_end = find_balanced_end(text, start + 2, "(", ")")
    except ShellSyntaxError:
        return None
    return outer_end if inner_end == outer_end - 1 else None


async def expand_text(
    text: str,
    state: ShellState,
    run_substitution: RunSubstitution,
    in_double_quotes: bool,
    split_positional: bool = False,
) -> str:
    """Return text with every parameter and command substitution replaced

    Args:
        text: Raw text from an unquoted or double-quoted word part
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output with trailing newlines removed
        in_double_quotes: Whether backslashes follow the double-quote escaping rules
        split_positional: Whether ``$@`` separates the positional arguments with the field separator

    Returns:
        The expanded text, not yet word-split
    """
    pieces: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and in_double_quotes and index + 1 < len(text):
            escaped = text[index + 1]
            pieces.append(escaped if escaped in DOUBLE_QUOTE_ESCAPABLE_CHARACTERS else "\\" + escaped)
            index += 2
        elif character == "`":
            closing_index = text.find("`", index + 1)
            if closing_index == -1:
                raise ShellSyntaxError(f"unclosed backtick: {text}")
            pieces.append(await run_substitution(text[index + 1 : closing_index]))
            index = closing_index + 1
        elif (arithmetic_end := find_arithmetic_end(text, index)) is not None:
            expression = await expand_text(
                text[index + len(ARITHMETIC_OPENING) : arithmetic_end - len(ARITHMETIC_CLOSING)],
                state,
                run_substitution,
                in_double_quotes=False,
            )
            pieces.append(str(evaluate_arithmetic(expression, state)))
            index = arithmetic_end
        elif text.startswith("$(", index):
            end = find_balanced_end(text, index + 1, "(", ")")
            pieces.append(await run_substitution(text[index + 2 : end - 1]))
            index = end
        elif text.startswith("${", index):
            end = find_balanced_end(text, index + 1, "{", "}")
            braced = text[index + 2 : end - 1]
            pieces.append(
                await expand_braced_parameter(braced, state, run_substitution, in_double_quotes, split_positional)
            )
            index = end
        elif character == "$":
            match = VARIABLE_NAME_PATTERN.match(text, index + 1)
            if match is not None:
                if match.group(0) not in state.variables and match.group(0) not in state.arrays:
                    check_unset(match.group(0), state)
                pieces.append(lookup_parameter(match.group(0), state))
                index = match.end()
            elif index + 1 < len(text) and text[index + 1] == "@" and split_positional:
                pieces.append(POSITIONAL_FIELD_SEPARATOR.join(state.positional_arguments))
                index += 2
            elif index + 1 < len(text) and text[index + 1] in SPECIAL_PARAMETER_CHARACTERS:
                pieces.append(lookup_parameter(text[index + 1], state))
                index += 2
            else:
                pieces.append("$")
                index += 1
        else:
            pieces.append(character)
            index += 1
    return "".join(pieces)


def expand_tilde(text: str, state: ShellState) -> str:
    """Return text with a leading tilde replaced by the home directory

    Args:
        text: An unquoted word part
        state: The shell state holding HOME

    Returns:
        The text with the tilde expanded when it stands alone or precedes a slash
    """
    if text == "~" or text.startswith("~/"):
        return lookup_parameter(HOME_VARIABLE_NAME, state) + text[1:]
    return text


@dataclass(frozen=True)
class ExpandedField:
    """Hold one field after expansion, with the glob pattern that stands for it

    The pattern equals the text except that quoted characters are escaped, so only unquoted wildcards match
    """

    text: str
    pattern: str
    has_wildcard: bool


@dataclass
class FieldBuilder:
    """Collect the fields one word expands to, remembering which characters were quoted"""

    fields: list[ExpandedField] = field(default_factory=list)
    text: str | None = None
    pattern: str = ""
    has_wildcard: bool = False

    def add_quoted(self, text: str) -> None:
        """Append text whose wildcard characters are literal

        Args:
            text: The quoted text, which starts a field even when empty
        """
        self.text = (self.text or "") + text
        self.pattern += glob.escape(text)

    def add_unquoted(self, text: str) -> None:
        """Append text whose wildcard characters match paths

        Args:
            text: The unquoted text
        """
        self.text = (self.text or "") + text
        self.pattern += text
        if GLOB_CHARACTER_PATTERN.search(text):
            self.has_wildcard = True

    def end_field(self) -> None:
        """Finish the field being built, if one was started"""
        if self.text is None:
            return
        self.fields.append(ExpandedField(text=self.text, pattern=self.pattern, has_wildcard=self.has_wildcard))
        self.text = None
        self.pattern = ""
        self.has_wildcard = False


def expand_pathnames(expanded_field: ExpandedField, state: ShellState) -> list[str]:
    """Return the paths a field's unquoted wildcards match, or the field itself when it matches nothing

    Hidden files match only a pattern that names the leading dot. Relative patterns are matched against
    the shell's current directory

    Args:
        expanded_field: The field and its pattern
        state: The shell state holding the current directory

    Returns:
        The matching paths in sorted order, or the literal text as the only entry
    """
    if not expanded_field.has_wildcard:
        return [expanded_field.text]
    matches = sorted(glob.glob(expanded_field.pattern, root_dir=state.cwd))  # noqa: PTH207
    return matches or [expanded_field.text]


async def expand_word(word: Word, state: ShellState, run_substitution: RunSubstitution) -> list[str]:
    """Return the fields one word expands to

    Unquoted expansions are split on whitespace and dropped when empty; quoted text is kept whole. A field
    with an unquoted ``*``, ``?`` or ``[`` is then replaced by the paths it matches, when it matches any

    Args:
        word: The word to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        Zero or more fields
    """
    fields: list[str] = []
    for expanded_word in expand_braces(word):
        fields.extend(await expand_fields(expanded_word, state, run_substitution))
    return fields


async def expand_fields(word: Word, state: ShellState, run_substitution: RunSubstitution) -> list[str]:
    """Return the fields one word expands to once its braces have been expanded

    Args:
        word: The word to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        Zero or more fields
    """
    builder = FieldBuilder()
    for part_index, part in enumerate(word.parts):
        if part.quote == QuoteStyle.SINGLE:
            builder.add_quoted(part.text)
            continue
        if part.quote == QuoteStyle.DOUBLE:
            expanded = await expand_text(
                part.text, state, run_substitution, in_double_quotes=True, split_positional=True
            )
            if expanded == "" and ALL_ELEMENTS_EXPANSION_PATTERN.match(part.text) is not None:
                continue
            positional_fields = expanded.split(POSITIONAL_FIELD_SEPARATOR)
            builder.add_quoted(positional_fields[0])
            for positional_field in positional_fields[1:]:
                builder.end_field()
                builder.add_quoted(positional_field)
            continue
        text = expand_tilde(part.text, state) if part_index == 0 else part.text
        expanded = await expand_text(text, state, run_substitution, in_double_quotes=False)
        tokens = split_fields(expanded, field_separators(state))
        for token in tokens:
            if token is None:
                builder.end_field()
            elif token or len(tokens) > 1:
                builder.add_unquoted(token)
    builder.end_field()
    fields: list[str] = []
    for expanded_field in builder.fields:
        fields.extend(expand_pathnames(expanded_field, state))
    return fields


def expand_braces(word: Word) -> list[Word]:
    """Return the words a word's unquoted brace patterns produce, left to right and then nested

    ``{a,b}`` lists and ``{1..5}``, ``{a..e}`` and ``{1..10..2}`` ranges expand; ``${...}`` and a brace
    holding no comma or range stay as written

    Args:
        word: The word before expansion

    Returns:
        The word itself when it holds no brace pattern, otherwise every word it produces
    """
    characters = [(character, part.quote) for part in word.parts for character in part.text]
    found = find_brace_pattern(characters)
    if found is None:
        return [word]
    start, end, alternatives = found
    produced: list[Word] = []
    for alternative in alternatives:
        produced.extend(expand_braces(word_from_characters(characters[:start] + alternative + characters[end + 1 :])))
    return produced


QuotedCharacter = tuple[str, QuoteStyle]


def word_from_characters(characters: list[QuotedCharacter]) -> Word:
    """Return a word whose parts merge runs of characters quoted the same way

    Args:
        characters: Each character with how it was quoted

    Returns:
        The word, holding no parts when there are no characters, which then expands to no field
    """
    if not characters:
        return Word(parts=[])
    parts: list[WordPart] = []
    for character, quote in characters:
        if parts and parts[-1].quote == quote:
            parts[-1] = WordPart(text=parts[-1].text + character, quote=quote)
        else:
            parts.append(WordPart(text=character, quote=quote))
    return Word(parts=parts)


def skip_unquoted_expansion(characters: list[QuotedCharacter], index: int) -> int:
    """Return the index after a ``$(`` or ``${`` expansion starting at an index, or the index itself

    Args:
        characters: The word's characters
        index: Where a dollar sign sits

    Returns:
        The index just past the balancing bracket, or the given index when no expansion starts there
    """
    if index + 1 >= len(characters) or characters[index + 1][0] not in "({":
        return index
    opening = characters[index + 1][0]
    closing = ")" if opening == "(" else "}"
    depth = 0
    position = index + 1
    while position < len(characters):
        character, quote = characters[position]
        if quote == QuoteStyle.NONE and character == opening:
            depth += 1
        elif quote == QuoteStyle.NONE and character == closing:
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return len(characters)


def find_brace_pattern(
    characters: list[QuotedCharacter],
) -> tuple[int, int, list[list[QuotedCharacter]]] | None:
    """Return the first expandable brace pattern in a word

    Args:
        characters: The word's characters

    Returns:
        The indices of the opening and closing braces and the alternatives between them, or None
    """
    index = 0
    while index < len(characters):
        character, quote = characters[index]
        if quote != QuoteStyle.NONE:
            index += 1
            continue
        if character == "$":
            index = max(skip_unquoted_expansion(characters, index), index + 1)
            continue
        if character == "{":
            found = brace_alternatives(characters, index)
            if found is not None:
                return found
        index += 1
    return None


def brace_alternatives(
    characters: list[QuotedCharacter], start: int
) -> tuple[int, int, list[list[QuotedCharacter]]] | None:
    """Return the alternatives of the brace pattern opening at an index, or None when it is not one

    Args:
        characters: The word's characters
        start: The index of the opening brace

    Returns:
        The opening and closing indices with the alternatives, or None
    """
    depth = 0
    comma_positions: list[int] = []
    index = start
    while index < len(characters):
        character, quote = characters[index]
        if quote != QuoteStyle.NONE:
            index += 1
            continue
        if character == "$":
            index = max(skip_unquoted_expansion(characters, index), index + 1)
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                break
        elif character == "," and depth == 1:
            comma_positions.append(index)
        index += 1
    else:
        return None
    end = index
    if comma_positions:
        boundaries = [start, *comma_positions, end]
        alternatives = [characters[left + 1 : right] for left, right in itertools.pairwise(boundaries)]
        return start, end, alternatives
    body = characters[start + 1 : end]
    if any(quote != QuoteStyle.NONE for _, quote in body):
        return None
    range_values = expand_brace_range("".join(character for character, _ in body))
    if range_values is None:
        return None
    return start, end, [[(character, QuoteStyle.NONE) for character in value] for value in range_values]


def expand_brace_range(body: str) -> list[str] | None:
    """Return the values of a ``start..end[..step]`` range, or None when the text is not one

    Args:
        body: The text between the braces

    Returns:
        The values in order, zero-padded when either bound was, or None
    """
    number_match = BRACE_RANGE_PATTERN.match(body)
    if number_match is not None:
        first_text, last_text, step_text = number_match.groups()
        first, last = int(first_text), int(last_text)
        step = abs(int(step_text)) if step_text else 1
        if step == 0:
            step = 1
        values = range(first, last + 1, step) if first <= last else range(first, last - 1, -step)
        padded = any(text.lstrip("-").startswith("0") and len(text.lstrip("-")) > 1 for text in (first_text, last_text))
        width = max(len(first_text), len(last_text)) if padded else 0
        return [f"{value:0{width}d}" if padded and value >= 0 else str(value).zfill(width) for value in values]
    letter_match = BRACE_LETTER_RANGE_PATTERN.match(body)
    if letter_match is None:
        return None
    first_letter, last_letter, step_text = letter_match.groups()
    step = abs(int(step_text)) if step_text else 1
    if step == 0:
        step = 1
    first, last = ord(first_letter), ord(last_letter)
    codes = range(first, last + 1, step) if first <= last else range(first, last - 1, -step)
    return [chr(code) for code in codes]


async def expand_words(words: list[Word], state: ShellState, run_substitution: RunSubstitution) -> list[str]:
    """Return the fields a list of words expands to

    Args:
        words: The words to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        Every field from every word, in order
    """
    fields: list[str] = []
    for word in words:
        fields.extend(await expand_word(word, state, run_substitution))
    return fields


async def expand_word_unsplit(word: Word, state: ShellState, run_substitution: RunSubstitution) -> str:
    """Return one word expanded without word splitting, as for an assignment value or redirection target

    Args:
        word: The word to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        The single expanded value
    """
    pieces: list[str] = []
    for part_index, part in enumerate(word.parts):
        if part.quote == QuoteStyle.SINGLE:
            pieces.append(part.text)
        elif part.quote == QuoteStyle.DOUBLE:
            pieces.append(await expand_text(part.text, state, run_substitution, in_double_quotes=True))
        else:
            text = expand_tilde(part.text, state) if part_index == 0 else part.text
            pieces.append(await expand_text(text, state, run_substitution, in_double_quotes=False))
    return "".join(pieces)


async def expand_word_as_pattern(word: Word, state: ShellState, run_substitution: RunSubstitution) -> str:
    """Return one word as a shell pattern in which only its unquoted characters are special

    Args:
        word: The word to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        The pattern text, with quoted text escaped so it matches literally
    """
    pieces: list[str] = []
    for part_index, part in enumerate(word.parts):
        if part.quote == QuoteStyle.SINGLE:
            pieces.append(glob.escape(part.text))
        elif part.quote == QuoteStyle.DOUBLE:
            expanded = await expand_text(part.text, state, run_substitution, in_double_quotes=True)
            pieces.append(glob.escape(expanded))
        else:
            text = expand_tilde(part.text, state) if part_index == 0 else part.text
            pieces.append(await expand_text(text, state, run_substitution, in_double_quotes=False))
    return "".join(pieces)


async def expand_raw_word(text: str, state: ShellState, run_substitution: RunSubstitution) -> str:
    """Return a raw quoted word, such as a redirection target, expanded to one value

    Args:
        text: The word with its quotes still present
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        The single expanded value
    """
    words, redirections, assignments = tokenize_simple_command(text)
    if len(words) != 1 or redirections or assignments:
        raise ShellSyntaxError(f"expected one word: {text}")
    return await expand_word_unsplit(words[0], state, run_substitution)
