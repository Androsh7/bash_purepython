"""Implement the cat command"""

# Standard libraries
from collections.abc import Generator, Iterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, NULL_DEVICE_PATH, ShellState

STDIN_PATH = "-"
LINE_NUMBER_WIDTH = 6


def file_lines(path_text: str, state: ShellState) -> Iterator[str] | None:
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
        state.write_error(f"cat: {path_text}: Is a directory\n")
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        state.write_error(f"cat: {path_text}: No such file or directory\n")
        return None
    return iter(text.splitlines(keepends=True))


def concatenate(invocation: CommandInvocation, paths: list[str], number_lines: bool) -> Generator[str, None, int]:
    """Yield every line of every source, numbering them when asked

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The files to read in order, ``-`` meaning standard input
        number_lines: Whether to prefix each line with its number

    Returns:
        Zero when every source was read, otherwise one
    """
    exit_code = EXIT_CODE_SUCCESS
    line_number = 0
    for path_text in paths:
        if path_text == STDIN_PATH:
            lines: Iterator[str] | None = stdin_lines(invocation.stdin, invocation.stdin_kind)
        else:
            lines = file_lines(path_text, invocation.state)
        if lines is None:
            exit_code = EXIT_CODE_FAILURE
            continue
        for line in lines:
            line_number += 1
            yield f"{line_number:>{LINE_NUMBER_WIDTH}}\t{line}" if number_lines else line
    return exit_code


class CatCommand(Command):
    """Concatenate files or standard input"""

    name = "cat"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of every file in order, or of standard input when no file is named

        Args:
            invocation: The call to perform

        Returns:
            A lazy stream of lines
        """
        parser = CommandArgumentParser("cat", "Concatenate files and print on the standard output")
        parser.add_argument("-n", "--number", action="store_true", help="number all output lines")
        parser.add_argument("paths", nargs="*", help="files to read, - for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=iter(()), exit_code=parsed)
        paths = parsed.paths or [STDIN_PATH]
        if invocation.stdin_kind == InputKind.ARGUMENTS:
            paths = [path for path in paths if path != STDIN_PATH]
        return CommandResult(stdout=concatenate(invocation, paths, parsed.number), exit_code=EXIT_CODE_SUCCESS)
