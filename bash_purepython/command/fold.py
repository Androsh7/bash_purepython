"""Implement the fold command"""

# Standard libraries
import re
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import open_source, source_paths
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import as_async_iterator, close_iterator

DEFAULT_WIDTH = 80
TAB_STOP = 8
NUMERIC_SHORTHAND_PATTERN = re.compile(r"^-([0-9]+)$")
OPTIONS_END = "--"


def expand_numeric_shorthand(arguments: list[str]) -> list[str]:
    """Return the arguments with the legacy ``-<width>`` form rewritten as ``-w <width>``

    Args:
        arguments: The arguments after the command name

    Returns:
        The rewritten arguments
    """
    expanded: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == OPTIONS_END:
            expanded.extend(arguments[index:])
            break
        match = NUMERIC_SHORTHAND_PATTERN.match(argument)
        if match:
            expanded.extend(["-w", match.group(1)])
        else:
            expanded.append(argument)
    return expanded


def advance_column(column: int, character: str, count_bytes: bool) -> int:
    """Return the column after printing one character

    Args:
        column: The column before the character
        character: The character
        count_bytes: Whether every character is one column, ignoring tabs and control characters

    Returns:
        The new column
    """
    if count_bytes:
        return column + 1
    if character == "\t":
        return column + TAB_STOP - column % TAB_STOP
    if character == "\b":
        return max(column - 1, 0)
    if character == "\r":
        return 0
    return column + 1


def fold_line(line: str, width: int, break_at_spaces: bool, count_bytes: bool) -> list[str]:
    """Return the pieces one line is broken into so that none is wider than the width

    Args:
        line: The line without its newline
        width: The greatest column a piece may reach
        break_at_spaces: Whether a piece is cut after its last blank when it has one
        count_bytes: Whether every character is one column

    Returns:
        The pieces in order, a single empty piece for an empty line
    """
    pieces: list[str] = []
    current: list[str] = []
    column = 0
    for character in line:
        next_column = advance_column(column, character, count_bytes)
        if next_column > width and current:
            cut = len(current)
            if break_at_spaces:
                blank_positions = [index for index, held in enumerate(current) if held.isspace()]
                if blank_positions:
                    cut = blank_positions[-1] + 1
            pieces.append("".join(current[:cut]))
            current = current[cut:]
            column = 0
            for held in current:
                column = advance_column(column, held, count_bytes)
            next_column = advance_column(column, character, count_bytes)
        current.append(character)
        column = next_column
    pieces.append("".join(current))
    return pieces


async def folded_lines(
    invocation: CommandInvocation, paths: list[str], width: int, break_at_spaces: bool, count_bytes: bool
) -> AsyncIterator[str]:
    """Yield every input line broken to the width

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The files to read, or none for standard input
        width: The greatest column a line may reach
        break_at_spaces: Whether lines are cut after their last blank when they have one
        count_bytes: Whether every character is one column

    Yields:
        Each piece with a newline
    """
    for path_text in source_paths(invocation, paths):
        lines = open_source("fold", path_text, invocation)
        if lines is None:
            continue
        try:
            async for line in lines:
                ends_with_newline = line.endswith("\n")
                pieces = fold_line(line.rstrip("\n"), width, break_at_spaces, count_bytes)
                yield "\n".join(pieces) + ("\n" if ends_with_newline else "")
        finally:
            await close_iterator(lines)


class FoldCommand(Command):
    """Wrap each input line to fit a width"""

    name = "fold"
    summary = "wrap each input line to fit in a width"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of the wrapped lines

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream
        """
        parser = CommandArgumentParser("fold", "Wrap input lines in each file, writing to standard output")
        parser.add_argument("-w", "--width", type=int, default=DEFAULT_WIDTH, help="use WIDTH columns instead of 80")
        parser.add_argument("-s", "--spaces", action="store_true", help="break at spaces")
        parser.add_argument("-b", "--bytes", action="store_true", help="count bytes rather than columns")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, expand_numeric_shorthand(invocation.arguments), invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        if parsed.width < 1:
            invocation.state.write_error(f"fold: invalid number of columns: '{parsed.width}'\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        stream = folded_lines(invocation, parsed.paths, parsed.width, parsed.spaces, parsed.bytes)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
