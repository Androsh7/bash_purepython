"""Implement the cut command"""

# Standard libraries
from collections.abc import AsyncIterator
from enum import StrEnum

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import input_lines
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import TEXT_ENCODING, as_async_iterator

DEFAULT_DELIMITER = "\t"
OPEN_RANGE_END = 10**9


class Selection(StrEnum):
    """Name what cut selects from each line"""

    FIELDS = "fields"
    CHARACTERS = "characters"
    BYTES = "bytes"


def parse_ranges(specification: str) -> list[tuple[int, int]] | None:
    """Return the inclusive one-based ranges named by a list such as ``1,3-5``

    Args:
        specification: The comma separated positions and ranges

    Returns:
        One pair per entry, open ends capped at a large bound, or None when an entry is malformed
    """
    ranges: list[tuple[int, int]] = []
    for raw_entry in specification.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            if "-" in entry:
                start_text, end_text = entry.split("-", 1)
                start = int(start_text) if start_text else 1
                end = int(end_text) if end_text else OPEN_RANGE_END
            else:
                start = end = int(entry)
        except ValueError:
            return None
        if start < 1 or end < start:
            return None
        ranges.append((start, end))
    return ranges


def in_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    """Return whether a one-based position falls inside any range

    Args:
        position: The position to test
        ranges: The inclusive pairs

    Returns:
        True when some range contains the position
    """
    return any(start <= position <= end for start, end in ranges)


def cut_line(
    line: str, selection: Selection, ranges: list[tuple[int, int]], delimiter: str, only_delimited: bool
) -> str | None:
    """Return the selected part of one line

    Args:
        line: The line without its newline
        selection: Whether fields, characters or bytes are selected
        ranges: The positions to keep
        delimiter: The field delimiter
        only_delimited: Whether lines without the delimiter are dropped rather than printed whole

    Returns:
        The cut line, or None when it should be dropped
    """
    if selection == Selection.FIELDS:
        if delimiter not in line:
            return None if only_delimited else line
        columns = line.split(delimiter)
        return delimiter.join(column for position, column in enumerate(columns, start=1) if in_ranges(position, ranges))
    if selection == Selection.CHARACTERS:
        return "".join(character for position, character in enumerate(line, start=1) if in_ranges(position, ranges))
    data = line.encode(TEXT_ENCODING)
    kept = bytes(byte for position, byte in enumerate(data, start=1) if in_ranges(position, ranges))
    return kept.decode(TEXT_ENCODING, errors="replace")


async def cut_lines(
    invocation: CommandInvocation,
    paths: list[str],
    selection: Selection,
    ranges: list[tuple[int, int]],
    delimiter: str,
    only_delimited: bool,
) -> AsyncIterator[str]:
    """Yield the selected part of every input line

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The files to read, or none for standard input
        selection: Whether fields, characters or bytes are selected
        ranges: The positions to keep
        delimiter: The field delimiter
        only_delimited: Whether lines without the delimiter are dropped

    Yields:
        Each cut line with a newline
    """
    async for line in input_lines("cut", invocation, paths):
        cut = cut_line(line, selection, ranges, delimiter, only_delimited)
        if cut is not None:
            yield cut + "\n"


class CutCommand(Command):
    """Remove sections from each line"""

    name = "cut"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of cut lines

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream, or a usage error when the selection is missing or malformed
        """
        parser = CommandArgumentParser("cut", "Remove sections from each line")
        parser.add_argument("-d", "--delimiter", default=DEFAULT_DELIMITER, help="field delimiter, TAB by default")
        parser.add_argument("-f", "--fields", help="field list")
        parser.add_argument("-c", "--characters", help="character list")
        parser.add_argument("-b", "--bytes", help="byte list")
        parser.add_argument("-s", "--only-delimited", action="store_true", help="skip lines without the delimiter")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        chosen = [
            (selection, specification)
            for selection, specification in (
                (Selection.FIELDS, parsed.fields),
                (Selection.CHARACTERS, parsed.characters),
                (Selection.BYTES, parsed.bytes),
            )
            if specification is not None
        ]
        if len(chosen) != 1:
            invocation.state.write_error("cut: you must specify exactly one of -b, -c or -f\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        selection, specification = chosen[0]
        ranges = parse_ranges(specification)
        if not ranges:
            invocation.state.write_error(f"cut: invalid list: {specification}\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        stream = cut_lines(invocation, parsed.paths, selection, ranges, parsed.delimiter, parsed.only_delimited)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
