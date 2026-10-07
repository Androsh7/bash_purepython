"""Implement the nl command"""

# Standard libraries
from collections.abc import AsyncIterator
from enum import StrEnum

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import input_lines
from bash_purepython.shell_state import EXIT_CODE_SUCCESS
from bash_purepython.streams import as_async_iterator

DEFAULT_NUMBER_WIDTH = 6
DEFAULT_SEPARATOR = "\t"
DEFAULT_INCREMENT = 1


class BodyNumbering(StrEnum):
    """Name which lines nl numbers"""

    ALL = "a"
    NON_EMPTY = "t"
    NONE = "n"


async def numbered_lines(
    invocation: CommandInvocation,
    paths: list[str],
    numbering: BodyNumbering,
    separator: str,
    width: int,
    increment: int,
) -> AsyncIterator[str]:
    """Yield each input line with its number, or with blank padding when it is not numbered

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The files to read, or none for standard input
        numbering: Which lines get numbers
        separator: Text between the number and the line
        width: The width of the number column
        increment: The step between numbers

    Yields:
        Each line, numbered or padded, with a newline
    """
    counter = 0
    async for line in input_lines("nl", invocation, paths):
        is_blank = line.strip() == ""
        should_number = numbering == BodyNumbering.ALL or (numbering == BodyNumbering.NON_EMPTY and not is_blank)
        if should_number:
            counter += increment
            yield f"{str(counter).rjust(width)}{separator}{line}\n"
        else:
            yield f"{' ' * width}{separator}{line}\n"


class NlCommand(Command):
    """Number the lines of files"""

    name = "nl"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of numbered lines

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream
        """
        parser = CommandArgumentParser("nl", "Number lines of files")
        parser.add_argument(
            "-b",
            "--body-numbering",
            choices=[numbering.value for numbering in BodyNumbering],
            default=BodyNumbering.NON_EMPTY.value,
            help="a all lines, t non-empty lines, n no lines",
        )
        parser.add_argument("-s", "--number-separator", default=DEFAULT_SEPARATOR, help="text after the number")
        parser.add_argument("-w", "--number-width", type=int, default=DEFAULT_NUMBER_WIDTH, help="number column width")
        parser.add_argument("-i", "--line-increment", type=int, default=DEFAULT_INCREMENT, help="step between numbers")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        stream = numbered_lines(
            invocation,
            parsed.paths,
            BodyNumbering(parsed.body_numbering),
            parsed.number_separator,
            parsed.number_width,
            parsed.line_increment,
        )
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
