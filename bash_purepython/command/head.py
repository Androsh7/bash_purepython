"""Implement the head command"""

# Standard libraries
import re
from collections import deque
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import close_stdin, file_lines, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, NULL_DEVICE_PATH, ShellState
from bash_purepython.streams import as_async_iterator, close_iterator

DEFAULT_LINE_COUNT = 10
STDIN_PATH = "-"
STDIN_LABEL = "standard input"
NUMERIC_SHORTHAND_PATTERN = re.compile(r"^-([0-9]+)$")
COUNT_OPTIONS = frozenset({"-n", "-c", "--lines", "--bytes"})


def expand_numeric_shorthand(arguments: list[str]) -> list[str]:
    """Return the arguments with the legacy ``-<count>`` form rewritten as ``-n <count>``

    A number following ``-n`` or ``-c`` is that option's value, so ``-n -3`` is left alone

    Args:
        arguments: The arguments after the command name

    Returns:
        The rewritten arguments
    """
    expanded: list[str] = []
    previous_took_value = False
    for index, argument in enumerate(arguments):
        if argument == "--":
            expanded.extend(arguments[index:])
            break
        match = NUMERIC_SHORTHAND_PATTERN.match(argument)
        if match and not previous_took_value:
            expanded.extend(["-n", match.group(1)])
        else:
            expanded.append(argument)
        previous_took_value = argument in COUNT_OPTIONS
    return expanded


async def skip_last_lines(lines: AsyncIterator[str], count: int) -> AsyncIterator[str]:
    """Yield every line but the last count, holding back only that many at a time

    Args:
        lines: The source lines
        count: How many trailing lines to drop

    Yields:
        The lines before the last count
    """
    held: deque[str] = deque()
    try:
        async for line in lines:
            held.append(line)
            if len(held) > count:
                yield held.popleft()
    finally:
        await close_iterator(lines)


async def skip_last_characters(lines: AsyncIterator[str], count: int) -> AsyncIterator[str]:
    """Yield all text but the last count characters, holding back only that many at a time

    Args:
        lines: The source lines
        count: How many trailing characters to drop

    Yields:
        Pieces of the text before the last count characters
    """
    held = ""
    try:
        async for line in lines:
            held += line
            if len(held) > count:
                yield held[: len(held) - count]
                held = held[len(held) - count :]
    finally:
        await close_iterator(lines)


async def take_lines(lines: AsyncIterator[str], limit: int) -> AsyncIterator[str]:
    """Yield at most limit lines, pulling no more than needed

    Args:
        lines: The source lines
        limit: How many to keep

    Yields:
        The first lines
    """
    try:
        if limit <= 0:
            return
        taken = 0
        async for line in lines:
            yield line
            taken += 1
            if taken >= limit:
                return
    finally:
        await close_iterator(lines)


async def take_characters(lines: AsyncIterator[str], limit: int) -> AsyncIterator[str]:
    """Yield text up to limit characters, pulling no more than needed

    Args:
        lines: The source lines
        limit: How many characters to keep

    Yields:
        Pieces of the first lines
    """
    remaining = limit
    try:
        if remaining <= 0:
            return
        async for line in lines:
            piece = line[:remaining]
            remaining -= len(piece)
            yield piece
            if remaining <= 0:
                return
    finally:
        await close_iterator(lines)


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
    return read_file_lines(path_text, invocation.state)


def read_file_lines(path_text: str, state: ShellState) -> AsyncIterator[str] | None:
    """Return the lines of one file, or None after reporting why it cannot be read

    Args:
        path_text: The path as written on the command line
        state: The shell state for resolving the path and reporting errors

    Returns:
        An async iterator over the lines, or None
    """
    if path_text == NULL_DEVICE_PATH:
        return as_async_iterator(())
    path = state.resolve_path(path_text)
    if path.is_dir():
        state.write_error(f"head: error reading '{path_text}': Is a directory\n")
        return None
    if not path.exists():
        state.write_error(f"head: cannot open '{path_text}' for reading: No such file or directory\n")
        return None
    return file_lines(path)


def limit_source(lines: AsyncIterator[str], line_limit: int, character_limit: int | None) -> AsyncIterator[str]:
    """Return the source cut to the first lines or characters, or to all but the last when the limit is negative

    Args:
        lines: The source lines
        line_limit: Lines to keep when no character limit is given
        character_limit: Characters to keep, or None

    Returns:
        An async iterator over the kept text
    """
    if character_limit is None:
        return skip_last_lines(lines, -line_limit) if line_limit < 0 else take_lines(lines, line_limit)
    if character_limit < 0:
        return skip_last_characters(lines, -character_limit)
    return take_characters(lines, character_limit)


async def head_sources(
    invocation: CommandInvocation, paths: list[str], line_limit: int, character_limit: int | None, show_headers: bool
) -> AsyncIterator[str]:
    """Yield the head of every source, then close standard input so an endless producer stops

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The sources in order
        line_limit: Lines to keep when no character limit is given
        character_limit: Characters to keep, or None
        show_headers: Whether to print a ``==> name <==`` header before each source

    Yields:
        The first lines or characters of each source, with headers when asked
    """
    printed_any_source = False
    try:
        for path_text in paths:
            lines = source_lines(path_text, invocation)
            if lines is None:
                invocation.exit_status.code = EXIT_CODE_FAILURE
                continue
            if show_headers:
                label = STDIN_LABEL if path_text == STDIN_PATH else path_text
                yield ("\n" if printed_any_source else "") + f"==> {label} <==\n"
            printed_any_source = True
            limited = limit_source(lines, line_limit, character_limit)
            try:
                async for piece in limited:
                    yield piece
            finally:
                await close_iterator(limited)
    finally:
        await close_stdin(invocation.stdin)


class HeadCommand(Command):
    """Print the first part of files or standard input"""

    name = "head"
    summary = "output the first part of files"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of the first lines or characters of each source

        Args:
            invocation: The call to perform

        Returns:
            A lazy stream that stops pulling from its input once the limit is reached
        """
        parser = CommandArgumentParser("head", "Print the first 10 lines of each file to standard output")
        parser.add_argument("-n", "--lines", type=int, default=DEFAULT_LINE_COUNT, help="print the first NUM lines")
        parser.add_argument("-c", "--bytes", type=int, default=None, help="print the first NUM characters")
        parser.add_argument("-q", "--quiet", "--silent", action="store_true", help="never print headers")
        parser.add_argument("-v", "--verbose", action="store_true", help="always print headers")
        parser.add_argument("paths", nargs="*", help="files to read, - for standard input")
        parsed = parse_command_arguments(parser, expand_numeric_shorthand(invocation.arguments), invocation.state)
        if isinstance(parsed, int):
            await close_stdin(invocation.stdin)
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        paths = parsed.paths or [STDIN_PATH]
        show_headers = parsed.verbose or (len(paths) > 1 and not parsed.quiet)
        stream = head_sources(invocation, paths, parsed.lines, parsed.bytes, show_headers)
        return CommandResult(stdout=stream, exit_code=invocation.exit_status.code)
