"""Implement the head command"""

# Standard libraries
import re
from collections.abc import Generator, Iterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import close_stdin, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, NULL_DEVICE_PATH, ShellState

DEFAULT_LINE_COUNT = 10
STDIN_PATH = "-"
STDIN_LABEL = "standard input"
NUMERIC_SHORTHAND_PATTERN = re.compile(r"^-([0-9]+)$")


def expand_numeric_shorthand(arguments: list[str]) -> list[str]:
    """Return the arguments with the legacy ``-<count>`` form rewritten as ``-n <count>``

    Args:
        arguments: The arguments after the command name

    Returns:
        The rewritten arguments
    """
    expanded: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == "--":
            expanded.extend(arguments[index:])
            break
        match = NUMERIC_SHORTHAND_PATTERN.match(argument)
        if match:
            expanded.extend(["-n", match.group(1)])
        else:
            expanded.append(argument)
    return expanded


def take_lines(lines: Iterator[str], limit: int) -> Iterator[str]:
    """Yield at most limit lines, pulling no more than needed

    Args:
        lines: The source lines
        limit: How many to keep

    Yields:
        The first lines
    """
    if limit <= 0:
        return
    for taken, line in enumerate(lines, start=1):
        yield line
        if taken >= limit:
            return


def take_characters(lines: Iterator[str], limit: int) -> Iterator[str]:
    """Yield text up to limit characters, pulling no more than needed

    Args:
        lines: The source lines
        limit: How many characters to keep

    Yields:
        Pieces of the first lines
    """
    remaining = limit
    for line in lines:
        if remaining <= 0:
            return
        piece = line[:remaining]
        remaining -= len(piece)
        yield piece


def source_lines(path_text: str, invocation: CommandInvocation) -> Iterator[str] | None:
    """Return the lines of one source, or None after reporting why it cannot be read

    Args:
        path_text: A file path, or ``-`` for standard input
        invocation: The call, providing standard input and the shell state

    Returns:
        An iterator over the lines, or None
    """
    if path_text == STDIN_PATH:
        return stdin_lines(invocation.stdin, invocation.stdin_kind)
    return read_file_lines(path_text, invocation.state)


def read_file_lines(path_text: str, state: ShellState) -> Iterator[str] | None:
    """Return the lines of one file, or None after reporting why it cannot be read

    Args:
        path_text: The path as written on the command line
        state: The shell state for resolving the path and reporting errors

    Returns:
        An iterator over the lines, or None
    """
    if path_text == NULL_DEVICE_PATH:
        return iter(())
    path = state.resolve_path(path_text)
    if path.is_dir():
        state.write_error(f"head: error reading '{path_text}': Is a directory\n")
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        state.write_error(f"head: cannot open '{path_text}' for reading: No such file or directory\n")
        return None
    return iter(text.splitlines(keepends=True))


def head_sources(
    invocation: CommandInvocation, paths: list[str], line_limit: int, character_limit: int | None, show_headers: bool
) -> Generator[str, None, int]:
    """Yield the head of every source, then close standard input so an endless producer stops

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The sources in order
        line_limit: Lines to keep when no character limit is given
        character_limit: Characters to keep, or None
        show_headers: Whether to print a ``==> name <==`` header before each source

    Returns:
        Zero when every source was read, otherwise one
    """
    exit_code = EXIT_CODE_SUCCESS
    printed_any_source = False
    try:
        for path_text in paths:
            lines = source_lines(path_text, invocation)
            if lines is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            if show_headers:
                label = STDIN_LABEL if path_text == STDIN_PATH else path_text
                yield ("\n" if printed_any_source else "") + f"==> {label} <==\n"
            printed_any_source = True
            if character_limit is None:
                yield from take_lines(lines, line_limit)
            else:
                yield from take_characters(lines, character_limit)
    finally:
        close_stdin(invocation.stdin)
    return exit_code


class HeadCommand(Command):
    """Print the first part of files or standard input"""

    name = "head"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
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
            close_stdin(invocation.stdin)
            return CommandResult(stdout=iter(()), exit_code=parsed)
        paths = parsed.paths or [STDIN_PATH]
        show_headers = parsed.verbose or (len(paths) > 1 and not parsed.quiet)
        stream = head_sources(invocation, paths, parsed.lines, parsed.bytes, show_headers)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
