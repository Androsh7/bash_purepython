"""Implement the tee command"""

# Standard libraries
from collections.abc import AsyncIterator
from typing import IO

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import close_stdin, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, ShellState
from bash_purepython.streams import TEXT_ENCODING, as_async_iterator, close_iterator

WRITE_MODE = "w"
APPEND_MODE = "a"


def open_outputs(paths: list[str], append: bool, state: ShellState) -> tuple[list[IO[str]], bool]:
    """Open every output file, reporting the ones that cannot be opened

    Args:
        paths: The files to write
        append: Whether to append rather than truncate
        state: The shell state for resolving paths and reporting errors

    Returns:
        The open files and whether any failed to open
    """
    handles: list[IO[str]] = []
    failed = False
    for path_text in paths:
        path = state.resolve_path(path_text)
        try:
            handles.append(path.open(APPEND_MODE if append else WRITE_MODE, encoding=TEXT_ENCODING, newline=""))
        except IsADirectoryError:
            state.write_error(f"tee: {path_text}: Is a directory\n")
            failed = True
        except PermissionError:
            state.write_error(f"tee: {path_text}: Permission denied\n")
            failed = True
        except FileNotFoundError:
            state.write_error(f"tee: {path_text}: No such file or directory\n")
            failed = True
    return handles, failed


async def copy_through(invocation: CommandInvocation, handles: list[IO[str]]) -> AsyncIterator[str]:
    """Yield each chunk of standard input after writing it to every open file

    Args:
        invocation: The call, providing standard input
        handles: The files every chunk is written to, closed once the input ends or the consumer stops

    Yields:
        Each chunk unchanged
    """
    if invocation.stdin_kind == InputKind.ARGUMENTS:
        chunks: AsyncIterator[str] = as_async_iterator(())
    else:
        chunks = stdin_lines(invocation.stdin, invocation.stdin_kind)
    try:
        async for chunk in chunks:
            for handle in handles:
                handle.write(chunk)
                handle.flush()
            yield chunk
    finally:
        await close_iterator(chunks)
        await close_stdin(invocation.stdin)
        for handle in handles:
            handle.close()


class TeeCommand(Command):
    """Copy standard input to standard output and to files"""

    name = "tee"
    summary = "read from standard input and write to standard output and files"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Open the files, then return a stream that writes each chunk to them as it passes through

        Args:
            invocation: The call to perform

        Returns:
            A lazy stream of the input
        """
        parser = CommandArgumentParser("tee", "Copy standard input to each file, and also to standard output")
        parser.add_argument("-a", "--append", action="store_true", help="append to the files, do not overwrite")
        parser.add_argument("-i", "--ignore-interrupts", action="store_true", help="ignore interrupt signals")
        parser.add_argument("paths", nargs="*", help="files to write")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        handles, failed = open_outputs(parsed.paths, parsed.append, invocation.state)
        if failed:
            invocation.exit_status.code = EXIT_CODE_FAILURE
        return CommandResult(stdout=copy_through(invocation, handles), exit_code=invocation.exit_status.code)
