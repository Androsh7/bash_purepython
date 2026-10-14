"""Implement the uniq command"""

# Standard libraries
import re
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import input_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE
from bash_purepython.streams import TEXT_ENCODING, as_async_iterator

COUNT_WIDTH = 7
STDIN_PATH = "-"
FIELD_PATTERN = r"\s*\S+"


def comparison_key(line: str, ignore_case: bool, skip_fields: int, skip_characters: int) -> str:
    """Return the part of a line uniq compares

    Args:
        line: The line without its newline
        ignore_case: Whether case differences are ignored
        skip_fields: How many leading blank-separated fields are skipped
        skip_characters: How many characters after the skipped fields are skipped

    Returns:
        The text compared against the neighbouring line
    """
    skipped = re.match(f"(?:{FIELD_PATTERN}){{{skip_fields}}}", line)
    remaining = line[skipped.end() :] if skipped is not None else ""
    remaining = remaining[skip_characters:]
    return remaining.casefold() if ignore_case else remaining


async def grouped_lines(
    lines: AsyncIterator[str], ignore_case: bool, skip_fields: int, skip_characters: int
) -> AsyncIterator[tuple[str, int]]:
    """Yield each run of adjacent equal lines as its first line and the run length

    Args:
        lines: The input lines without newlines
        ignore_case: Whether case differences are ignored
        skip_fields: How many leading fields are ignored when comparing
        skip_characters: How many characters are ignored after the skipped fields

    Yields:
        The first line of each run and how many lines it held
    """
    current_line: str | None = None
    current_key = ""
    count = 0
    async for line in lines:
        key = comparison_key(line, ignore_case, skip_fields, skip_characters)
        if current_line is not None and key == current_key:
            count += 1
            continue
        if current_line is not None:
            yield current_line, count
        current_line, current_key, count = line, key, 1
    if current_line is not None:
        yield current_line, count


async def filtered_output(invocation: CommandInvocation, paths: list[str], parsed: object) -> AsyncIterator[str]:
    """Yield the lines uniq keeps, formatted with counts when asked

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The input file, or none for standard input
        parsed: The parsed options

    Yields:
        Each kept line with a newline
    """
    lines = input_lines("uniq", invocation, paths)
    async for line, count in grouped_lines(lines, parsed.ignore_case, parsed.skip_fields, parsed.skip_chars):
        repeated = count > 1
        if parsed.repeated and not repeated:
            continue
        if parsed.unique and repeated:
            continue
        yield f"{count:>{COUNT_WIDTH}} {line}\n" if parsed.count else f"{line}\n"


class UniqCommand(Command):
    """Report or omit repeated adjacent lines"""

    name = "uniq"
    summary = "report or omit repeated lines"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream with adjacent duplicate lines collapsed, or write it to the output file

        Args:
            invocation: The call to perform

        Returns:
            A lazy stream of the kept lines, empty when an output file was named
        """
        parser = CommandArgumentParser("uniq", "Filter adjacent matching lines from INPUT, writing to OUTPUT")
        parser.add_argument("-c", "--count", action="store_true", help="prefix lines by the number of occurrences")
        parser.add_argument("-d", "--repeated", action="store_true", help="only print duplicate lines, one for each")
        parser.add_argument("-u", "--unique", action="store_true", help="only print unique lines")
        parser.add_argument("-i", "--ignore-case", action="store_true", help="ignore differences in case")
        parser.add_argument("-f", "--skip-fields", type=int, default=0, metavar="N", help="avoid comparing N fields")
        parser.add_argument("-s", "--skip-chars", type=int, default=0, metavar="N", help="avoid comparing N chars")
        parser.add_argument("input", nargs="?", default=STDIN_PATH, help="file to read, - for standard input")
        parser.add_argument("output", nargs="?", default=None, help="file to write instead of standard output")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        stream = filtered_output(invocation, [parsed.input], parsed)
        if parsed.output is None:
            return CommandResult(stdout=stream, exit_code=invocation.exit_status.code)
        text = "".join([piece async for piece in stream])
        output_path = invocation.state.resolve_path(parsed.output)
        try:
            output_path.write_text(text, encoding=TEXT_ENCODING, newline="")
        except OSError as error:
            invocation.state.write_error(f"uniq: {parsed.output}: {error.strerror}\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_FAILURE)
        return CommandResult(stdout=as_async_iterator(()), exit_code=invocation.exit_status.code)
