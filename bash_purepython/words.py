"""Tokenise one simple command into words, redirections and assignments, and expand the words"""

# Standard libraries
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# Project libraries
from bash_purepython.shell_state import ExpansionError, ShellState, ShellSyntaxError
from bash_purepython.workflow import Redirection, RedirectionKind

WHITESPACE_CHARACTERS = frozenset(" \t\n")
WORD_SPLIT_PATTERN = re.compile(r"([ \t\n]+)")
ASSIGNMENT_PATTERN = re.compile(r"^([A-Za-z_]\w*)=")
VARIABLE_NAME_PATTERN = re.compile(r"[A-Za-z_]\w*")
SPECIAL_PARAMETER_CHARACTERS = frozenset("?#@*$0123456789")
HEREDOC_DELIMITER_PATTERN = re.compile(r"(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|(\\?[^\s;&|()<>'\"]+))")
DOUBLE_QUOTE_ESCAPABLE_CHARACTERS = frozenset('$`"\\\n')
ECHO_ESCAPE_SEQUENCES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
HOME_VARIABLE_NAME = "HOME"
SHELL_NAME = "bash"
POSITIONAL_FIELD_SEPARATOR = "\x1f"
ALL_POSITIONAL_SPELLINGS = frozenset({"$@", "${@}"})

RunSubstitution = Callable[[str], str]


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
    """Hold one ``name=value`` word that preceded the command name"""

    name: str
    value: Word


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
        assignment = self._as_assignment(word)
        if assignment is not None and not self.words:
            self.assignments.append(assignment)
        else:
            self.words.append(word)

    def _as_assignment(self, word: Word) -> Assignment | None:
        """Return the assignment a word denotes, or None when it is an ordinary word

        Args:
            word: The finished word

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
        return Assignment(name=match.group(1), value=Word(parts=[part for part in value_parts if part.text]))

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
        kind = self._match_redirection_kind(remaining, descriptor_prefix)
        if kind is None:
            if descriptor_prefix:
                return False
            raise ShellSyntaxError(f"unsupported redirection: {self.text}")
        if descriptor_prefix:
            self.parts = []
            self.word_started = False
        self.position += self._operator_length(kind, descriptor_prefix)
        if kind == RedirectionKind.STDERR_TO_STDOUT:
            self.redirections.append(Redirection(kind=kind, target=""))
            return True
        if kind == RedirectionKind.HEREDOC:
            self._consume_heredoc_operator()
            return True
        target = self._consume_target_word()
        self.redirections.append(Redirection(kind=kind, target=target))
        return True

    def _match_redirection_kind(self, remaining: str, descriptor_prefix: str) -> RedirectionKind | None:
        """Return the redirection kind starting the remaining text, given the descriptor digit before it

        Args:
            remaining: The text from the current position
            descriptor_prefix: ``1``, ``2`` or empty

        Returns:
            The kind, or None when the text is not a supported redirection
        """
        if descriptor_prefix == "2":
            if remaining.startswith(">&1"):
                return RedirectionKind.STDERR_TO_STDOUT
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
        if kind == RedirectionKind.STDERR_TO_STDOUT:
            return len(">&1")
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

    Args:
        name: A variable name, a digit, or one of ``? # @ * $ 0``
        state: The shell state holding variables, positional arguments and the last exit code

    Returns:
        The value as text
    """
    if name == "?":
        return str(state.last_exit_code)
    if name == "#":
        return str(len(state.positional_arguments))
    if name in ("@", "*"):
        return " ".join(state.positional_arguments)
    if name == "0":
        return SHELL_NAME
    if name.isdigit():
        index = int(name) - 1
        return state.positional_arguments[index] if 0 <= index < len(state.positional_arguments) else ""
    if name == HOME_VARIABLE_NAME and HOME_VARIABLE_NAME not in state.variables:
        return str(Path.home())
    return state.variables.get(name, "")


def expand_operand(operand: str, state: ShellState, run_substitution: RunSubstitution, in_double_quotes: bool) -> str:
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
            return expand_word_unsplit(words[0], state, run_substitution)
    return expand_text(operand, state, run_substitution, in_double_quotes=True)


def expand_braced_parameter(
    expression: str,
    state: ShellState,
    run_substitution: RunSubstitution,
    in_double_quotes: bool = True,
    split_positional: bool = False,
) -> str:
    """Return the value of a ``${...}`` expression

    Args:
        expression: The text between the braces
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output, for defaults holding substitutions
        in_double_quotes: Whether the expansion sits inside double quotes, which keeps operand quotes literal
        split_positional: Whether ``${@}`` should separate the positional arguments with the field separator

    Raises:
        ShellSyntaxError: If the expression uses an operator this shell does not support

    Returns:
        The expanded value
    """
    if expression.startswith("#"):
        return str(len(lookup_parameter(expression[1:], state)))
    match = re.match(r"^([A-Za-z_]\w*|[?#@*$0-9])(:?[-=+?])?(.*)$", expression, re.DOTALL)
    if match is None:
        raise ExpansionError(f"${{{expression}}}: bad substitution")
    name, operator, operand = match.group(1), match.group(2), match.group(3)
    value = lookup_parameter(name, state)
    if name == "@" and split_positional:
        value = POSITIONAL_FIELD_SEPARATOR.join(state.positional_arguments)
    if operator is None:
        if operand:
            raise ExpansionError(f"${{{expression}}}: bad substitution")
        return value
    is_set = name in state.variables or (name.isdigit() and value != "") or name in "?#@*$0"
    treat_empty_as_unset = operator.startswith(":")
    missing = not is_set or (treat_empty_as_unset and value == "")
    if operator.endswith("-"):
        return expand_operand(operand, state, run_substitution, in_double_quotes) if missing else value
    if operator.endswith("+"):
        return "" if missing else expand_operand(operand, state, run_substitution, in_double_quotes)
    if operator.endswith("="):
        if missing:
            value = expand_operand(operand, state, run_substitution, in_double_quotes)
            state.variables[name] = value
        return value
    if missing:
        message = expand_operand(operand, state, run_substitution, in_double_quotes) or "parameter null or not set"
        raise ExpansionError(f"{name}: {message}")
    return value


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


def expand_text(
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
            pieces.append(run_substitution(text[index + 1 : closing_index]))
            index = closing_index + 1
        elif text.startswith("$(", index):
            end = find_balanced_end(text, index + 1, "(", ")")
            pieces.append(run_substitution(text[index + 2 : end - 1]))
            index = end
        elif text.startswith("${", index):
            end = find_balanced_end(text, index + 1, "{", "}")
            braced = text[index + 2 : end - 1]
            pieces.append(expand_braced_parameter(braced, state, run_substitution, in_double_quotes, split_positional))
            index = end
        elif character == "$":
            match = VARIABLE_NAME_PATTERN.match(text, index + 1)
            if match is not None:
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


def expand_word(word: Word, state: ShellState, run_substitution: RunSubstitution) -> list[str]:
    """Return the fields one word expands to

    Unquoted expansions are split on whitespace and dropped when empty; quoted text is kept whole

    Args:
        word: The word to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        Zero or more fields
    """
    fields: list[str] = []
    current: str | None = None
    for part_index, part in enumerate(word.parts):
        if part.quote == QuoteStyle.SINGLE:
            current = (current or "") + part.text
            continue
        if part.quote == QuoteStyle.DOUBLE:
            expanded = expand_text(part.text, state, run_substitution, in_double_quotes=True, split_positional=True)
            if expanded == "" and part.text in ALL_POSITIONAL_SPELLINGS:
                continue
            positional_fields = expanded.split(POSITIONAL_FIELD_SEPARATOR)
            current = (current or "") + positional_fields[0]
            for positional_field in positional_fields[1:]:
                fields.append(current)
                current = positional_field
            continue
        text = expand_tilde(part.text, state) if part_index == 0 else part.text
        expanded = expand_text(text, state, run_substitution, in_double_quotes=False)
        for token in WORD_SPLIT_PATTERN.split(expanded):
            if not token:
                continue
            if token[0] in WHITESPACE_CHARACTERS:
                if current is not None:
                    fields.append(current)
                    current = None
            else:
                current = (current or "") + token
    if current is not None:
        fields.append(current)
    return fields


def expand_words(words: list[Word], state: ShellState, run_substitution: RunSubstitution) -> list[str]:
    """Return the fields a list of words expands to

    Args:
        words: The words to expand
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        Every field from every word, in order
    """
    return [field for word in words for field in expand_word(word, state, run_substitution)]


def expand_word_unsplit(word: Word, state: ShellState, run_substitution: RunSubstitution) -> str:
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
            pieces.append(expand_text(part.text, state, run_substitution, in_double_quotes=True))
        else:
            text = expand_tilde(part.text, state) if part_index == 0 else part.text
            pieces.append(expand_text(text, state, run_substitution, in_double_quotes=False))
    return "".join(pieces)


def expand_raw_word(text: str, state: ShellState, run_substitution: RunSubstitution) -> str:
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
    return expand_word_unsplit(words[0], state, run_substitution)
