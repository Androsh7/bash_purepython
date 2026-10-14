"""Implement the tail command"""

# Standard libraries
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.head import expand_numeric_shorthand
from bash_purepython.command.lines import file_lines, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_USAGE_ERROR, NULL_DEVICE_PATH
from bash_purepython.streams import as_async_iterator, close_iterator

DEFAULT_LINE_COUNT = 10
STDIN_PATH = "-"
STDIN_LABEL = "standard input"
COUNT_PATTERN = re.compile(r"^([+-]?)(\d+)$")
FROM_START_MARKER = "+"


@dataclass(frozen=True)
class Count:
    """Hold how much of a source tail keeps: the last N units, or everything from unit N on"""

    amount: int
    from_start: bool

    @classmethod
    def parse(cls, text: str):
        """Return the count a ``-n`` or ``-c`` argument asks for

        Args:
            text: The argument, ``N``, ``-N`` or ``+N``

        Raises:
            ValueError: If the argument is not a number
        """
        match = COUNT_PATTERN.match(text)
        if match is None:
            raise ValueError(text)
        return cls(amount=int(match.group(2)), from_start=match.group(1) == FROM_START_MARKER)

    def keep_lines(self, lines: list[str]) -> list[str]:
        """Return the lines this count keeps

        Args:
            lines: Every line of the source with newlines kept

        Returns:
            The last lines, or the lines from the given one on
        """
        if self.from_start:
            return lines[max(self.amount - 1, 0) :]
        return lines[-self.amount :] if self.amount else []

    def keep_characters(self, text: str) -> str:
        """Return the characters this count keeps

        Args:
            text: The whole source

        Returns:
            The last characters, or the text from the given character on
        """
        if self.from_start:
            return text[max(self.amount - 1, 0) :]
        return text[-self.amount :] if self.amount else ""


def source_lines(path_text: str, invocation: CommandInvocation) -> AsyncIterator[str] | None:
    """Return the lines of one source, or None after reporting why it cannot be read

    Args:
        path_text: A file path, or ``-`` for standard input
        invocation: The call, providing standard input and the shell state

    Returns:
        An async iterator over the lines, or None
    """
    if path_text == STDIN_PATH:
        if invocation.stdin_kind == InputKind.ARGUMENTS:
            return as_async_iterator(())
        return stdin_lines(invocation.stdin, invocation.stdin_kind)
    if path_text == NULL_DEVICE_PATH:
        return as_async_iterator(())
    path = invocation.state.resolve_path(path_text)
    if path.is_dir():
        invocation.state.write_error(f"tail: error reading '{path_text}': Is a directory\n")
        return None
    if not path.exists():
        invocation.state.write_error(f"tail: cannot open '{path_text}' for reading: No such file or directory\n")
        return None
    return file_lines(path)


async def read_source(path_text: str, invocation: CommandInvocation) -> list[str] | None:
    """Return every line of one source, or None when it cannot be read

    Args:
        path_text: A file path, or ``-`` for standard input
        invocation: The call, providing standard input and the shell state

    Returns:
        The lines with newlines kept, or None
    """
    lines = source_lines(path_text, invocation)
    if lines is None:
        return None
    try:
        return [line async for line in lines]
    finally:
        await close_iterator(lines)


class TailCommand(Command):
    """Print the last part of files or standard input"""

    name = "tail"
    summary = "output the last part of files"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Read each source whole and return its last lines or characters

        Args:
            invocation: The call to perform

        Returns:
            The tail of each source, with headers when several are named
        """
        parser = CommandArgumentParser("tail", "Print the last 10 lines of each file to standard output")
        parser.add_argument("-n", "--lines", default=str(DEFAULT_LINE_COUNT), help="output the last NUM lines, or +NUM")
        parser.add_argument("-c", "--bytes", default=None, help="output the last NUM characters, or +NUM")
        parser.add_argument("-q", "--quiet", "--silent", action="store_true", help="never output headers")
        parser.add_argument("-v", "--verbose", action="store_true", help="always output headers")
        parser.add_argument("paths", nargs="*", help="files to read, - for standard input")
        parsed = parse_command_arguments(parser, expand_numeric_shorthand(invocation.arguments), invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        try:
            line_count = Count.parse(parsed.lines)
            character_count = Count.parse(parsed.bytes) if parsed.bytes is not None else None
        except ValueError as error:
            invocation.state.write_error(f"tail: invalid number of lines: '{error}'\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_USAGE_ERROR)
        paths = parsed.paths or [STDIN_PATH]
        show_headers = parsed.verbose or (len(paths) > 1 and not parsed.quiet)
        pieces: list[str] = []
        exit_code = invocation.exit_status.code
        for path_text in paths:
            lines = await read_source(path_text, invocation)
            if lines is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            if show_headers:
                label = STDIN_LABEL if path_text == STDIN_PATH else path_text
                pieces.append(("\n" if pieces else "") + f"==> {label} <==\n")
            if character_count is not None:
                pieces.append(character_count.keep_characters("".join(lines)))
            else:
                pieces.append("".join(line_count.keep_lines(lines)))
        return CommandResult(stdout="".join(pieces), exit_code=exit_code)
