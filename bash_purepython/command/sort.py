"""Implement the sort command"""

# Standard libraries
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import input_lines
from bash_purepython.shell_state import EXIT_CODE_USAGE_ERROR

LEADING_NUMBER_PATTERN = re.compile(r"^\s*(-?)(\d+\.?\d*|\.\d+)")
HUMAN_SUFFIX_PATTERN = re.compile(r"^\s*(-?)(\d+\.?\d*|\.\d+)\s*([kKMGTPEZY]?)")
HUMAN_SUFFIX_ORDER = "KMGTPEZY"
KEY_PATTERN = re.compile(r"^(\d+)(?:\.(\d+))?([bfnrh]*)(?:,(\d+)(?:\.(\d+))?([bfnrh]*))?$")
FIRST_FIELD_NUMBER = 1
FIRST_CHARACTER_NUMBER = 1
NO_NUMBER_VALUE = 0.0
NEGATIVE_SIGN = "-"
KEY_MODIFIER_NUMERIC = "n"
KEY_MODIFIER_HUMAN = "h"
KEY_MODIFIER_FOLD = "f"
KEY_MODIFIER_REVERSE = "r"
KEY_MODIFIER_BLANKS = "b"


@dataclass(frozen=True)
class ReversedKey:
    """Wrap a comparable value so it orders the other way round, for a key with the ``r`` modifier"""

    value: Any

    def __lt__(self, other: "ReversedKey") -> bool:
        """Return whether this key sorts before another, which is when its value is the larger

        Args:
            other: The key to compare with

        Returns:
            True when this key comes first in reversed order
        """
        return other.value < self.value


def numeric_value(text: str) -> float:
    """Return the number a line starts with, or zero when it starts with none

    Args:
        text: The key text

    Returns:
        The leading number as GNU sort -n reads it
    """
    match = LEADING_NUMBER_PATTERN.match(text)
    if match is None:
        return NO_NUMBER_VALUE
    sign = -1.0 if match.group(1) == NEGATIVE_SIGN else 1.0
    return sign * float(match.group(2))


def human_numeric_key(text: str) -> tuple[int, int, float]:
    """Return a key ordering a human-readable size by sign, then suffix, then magnitude

    Args:
        text: The key text, such as ``2K`` or ``1.5G``

    Returns:
        The sign, the rank of the suffix and the signed number
    """
    match = HUMAN_SUFFIX_PATTERN.match(text)
    if match is None:
        return (0, 0, NO_NUMBER_VALUE)
    sign = -1 if match.group(1) == NEGATIVE_SIGN else 1
    magnitude = float(match.group(2))
    if magnitude == 0:
        return (0, 0, NO_NUMBER_VALUE)
    suffix = match.group(3).upper()
    rank = HUMAN_SUFFIX_ORDER.index(suffix) + 1 if suffix else 0
    return (sign, sign * rank, sign * magnitude)


@dataclass(frozen=True)
class SortKey:
    """Describe one -k key: where it starts and ends and how its text is compared"""

    start_field: int
    start_character: int
    end_field: int | None
    end_character: int | None
    modifiers: str

    @classmethod
    def parse(cls, text: str):
        """Return the key a ``-k`` argument describes

        Args:
            text: The argument, ``START[.CHAR][OPTS][,END[.CHAR][OPTS]]``

        Raises:
            ValueError: If the argument is not a key definition or names field zero
        """
        match = KEY_PATTERN.match(text)
        if match is None:
            raise ValueError(f"invalid key definition {text!r}")
        start_field = int(match.group(1))
        if start_field < FIRST_FIELD_NUMBER:
            raise ValueError("field number is zero")
        start_character = int(match.group(2)) if match.group(2) else FIRST_CHARACTER_NUMBER
        end_field = int(match.group(4)) if match.group(4) else None
        end_character = int(match.group(5)) if match.group(5) else None
        modifiers = (match.group(3) or "") + (match.group(6) or "")
        return cls(start_field, start_character, end_field, end_character, modifiers)

    def extract(self, line: str, separator: str | None) -> str:
        """Return the part of a line this key compares

        Args:
            line: The whole line without its newline
            separator: The field separator, or None for runs of blanks

        Returns:
            The key text, empty when the line has too few fields
        """
        fields = split_fields(line, separator)
        joiner = separator if separator is not None else " "
        start_index = self.start_field - 1
        if start_index >= len(fields):
            return ""
        end_index = len(fields) if self.end_field is None else min(self.end_field, len(fields))
        selected = list(fields[start_index:end_index])
        if not selected:
            return ""
        if self.end_character is not None and self.end_field is not None and self.end_field <= len(fields):
            selected[-1] = selected[-1][: self.end_character]
        selected[0] = selected[0][self.start_character - 1 :]
        text = joiner.join(selected)
        if KEY_MODIFIER_BLANKS in self.modifiers:
            text = text.lstrip()
        return text


def split_fields(line: str, separator: str | None) -> list[str]:
    """Return the fields of a line

    Args:
        line: The whole line without its newline
        separator: The field separator, or None for runs of blanks, where each field keeps its leading blanks

    Returns:
        The fields in order
    """
    if separator is not None:
        return line.split(separator)
    return re.findall(r"\s*\S+", line)


def compare_key(text: str, numeric: bool, human: bool, fold_case: bool) -> Any:
    """Return the value one piece of key text sorts by

    Args:
        text: The key text
        numeric: Whether to compare as a leading number
        human: Whether to compare as a human-readable size
        fold_case: Whether to ignore case

    Returns:
        A comparable value
    """
    if human:
        return human_numeric_key(text)
    if numeric:
        return numeric_value(text)
    return text.casefold() if fold_case else text


def build_key_function(
    keys: list[SortKey], separator: str | None, numeric: bool, human: bool, fold_case: bool, ignore_blanks: bool
) -> Callable[[str], tuple[Any, ...]]:
    """Return the function mapping a line to the tuple it sorts by, without the last-resort whole line

    Args:
        keys: The -k keys in order, or none to compare whole lines
        separator: The field separator, or None for runs of blanks
        numeric: Whether -n was given
        human: Whether -h was given
        fold_case: Whether -f was given
        ignore_blanks: Whether -b was given

    Returns:
        The key function
    """
    if not keys:
        return lambda line: (compare_key(line.lstrip() if ignore_blanks else line, numeric, human, fold_case),)

    def key_of(line: str) -> tuple[Any, ...]:
        parts: list[Any] = []
        for key in keys:
            key_numeric = numeric or KEY_MODIFIER_NUMERIC in key.modifiers
            key_human = human or KEY_MODIFIER_HUMAN in key.modifiers
            key_fold = fold_case or KEY_MODIFIER_FOLD in key.modifiers
            value = compare_key(key.extract(line, separator), key_numeric, key_human, key_fold)
            parts.append(ReversedKey(value) if KEY_MODIFIER_REVERSE in key.modifiers else value)
        return tuple(parts)

    return key_of


def sort_lines(
    lines: list[str], key_function: Callable[[str], tuple[Any, ...]], reverse: bool, stable: bool, unique: bool
) -> list[str]:
    """Return the lines in sorted order

    Args:
        lines: The lines without newlines
        key_function: Maps a line to the tuple it sorts by
        reverse: Whether to reverse the order
        stable: Whether equal keys keep their input order instead of being compared as whole lines
        unique: Whether only the first of each run of equal keys is kept

    Returns:
        The sorted lines
    """
    if stable:
        ordered = sorted(lines, key=key_function, reverse=reverse)
    else:
        ordered = sorted(lines, key=lambda line: (key_function(line), line), reverse=reverse)
    if not unique:
        return ordered
    kept: list[str] = []
    previous_key: tuple[Any, ...] | None = None
    for line in ordered:
        line_key = key_function(line)
        if previous_key is None or line_key != previous_key:
            kept.append(line)
            previous_key = line_key
    return kept


class SortCommand(Command):
    """Sort the lines of files or standard input"""

    name = "sort"
    summary = "sort lines of text"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Read every source, sort the lines and return them

        Args:
            invocation: The call to perform

        Returns:
            The sorted lines, each ending in a newline
        """
        parser = CommandArgumentParser("sort", "Write sorted concatenation of all files to standard output")
        parser.add_argument("-r", "--reverse", action="store_true", help="reverse the result of comparisons")
        parser.add_argument("-u", "--unique", action="store_true", help="output only the first of an equal run")
        parser.add_argument("-n", "--numeric-sort", action="store_true", help="compare according to numerical value")
        parser.add_argument(
            "-h", "--human-numeric-sort", action="store_true", help="compare human readable numbers (e.g., 2K 1G)"
        )
        parser.add_argument("-f", "--ignore-case", action="store_true", help="fold lower case to upper case")
        parser.add_argument("-b", "--ignore-leading-blanks", action="store_true", help="ignore leading blanks")
        parser.add_argument("-s", "--stable", action="store_true", help="stabilize sort by disabling last-resort")
        parser.add_argument(
            "-k", "--key", action="append", default=[], metavar="KEYDEF", help="sort via a key; KEYDEF is F[.C][OPTS]"
        )
        parser.add_argument("-t", "--field-separator", default=None, metavar="SEP", help="use SEP instead of blanks")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        try:
            keys = [SortKey.parse(text) for text in parsed.key]
        except ValueError as error:
            invocation.state.write_error(f"sort: {error}\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        if parsed.field_separator is not None and len(parsed.field_separator) != 1:
            invocation.state.write_error(f"sort: multi-character tab '{parsed.field_separator}'\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        if parsed.ignore_leading_blanks:
            keys = [
                SortKey(key.start_field, key.start_character, key.end_field, key.end_character, key.modifiers + "b")
                for key in keys
            ]
        lines = [line async for line in input_lines("sort", invocation, parsed.paths)]
        key_function = build_key_function(
            keys,
            parsed.field_separator,
            parsed.numeric_sort,
            parsed.human_numeric_sort,
            parsed.ignore_case,
            parsed.ignore_leading_blanks,
        )
        ordered = sort_lines(lines, key_function, parsed.reverse, parsed.stable, parsed.unique)
        output = "".join(f"{line}\n" for line in ordered)
        return CommandResult(stdout=output, exit_code=invocation.exit_status.code)
