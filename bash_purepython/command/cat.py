"""Implement the cat command"""

# Standard libraries
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import file_lines, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, NULL_DEVICE_PATH, ShellState
from bash_purepython.streams import TEXT_ENCODING, as_async_iterator, close_iterator

STDIN_PATH = "-"
LINE_NUMBER_WIDTH = 6
NEWLINE = "\n"
TAB = "\t"
TAB_DISPLAY = "^I"
LINE_END_DISPLAY = "$"
CONTROL_PREFIX = "^"
META_PREFIX = "M-"
DELETE_CODE = 0x7F
CONTROL_LIMIT = 0x20
CONTROL_OFFSET = 0x40
META_BIT = 0x80
ASCII_LIMIT = 0x80


def show_byte(code: int, show_tabs: bool) -> str:
    """Return how cat -v displays one byte

    Args:
        code: The byte value
        show_tabs: Whether a tab is shown as ``^I`` rather than kept

    Returns:
        The visible form
    """
    if code >= META_BIT:
        return META_PREFIX + show_ascii_byte(code - META_BIT)
    if code == ord(NEWLINE):
        return NEWLINE
    if code == ord(TAB) and not show_tabs:
        return TAB
    return show_ascii_byte(code)


def show_ascii_byte(code: int) -> str:
    """Return how cat -v displays one seven-bit byte, with every control character in caret notation

    Args:
        code: The byte value, below 128

    Returns:
        The visible form
    """
    if code == DELETE_CODE:
        return CONTROL_PREFIX + "?"
    if code < CONTROL_LIMIT:
        return CONTROL_PREFIX + chr(code + CONTROL_OFFSET)
    return chr(code)


def show_nonprinting(text: str, show_tabs: bool) -> str:
    """Return text with control characters and non-ASCII bytes made visible as cat -v does

    Args:
        text: One line
        show_tabs: Whether tabs are shown as ``^I``

    Returns:
        The line with every non-printing character replaced by its notation
    """
    pieces: list[str] = []
    for character in text:
        if ord(character) < ASCII_LIMIT:
            pieces.append(show_byte(ord(character), show_tabs))
        else:
            pieces.extend(show_byte(code, show_tabs) for code in character.encode(TEXT_ENCODING))
    return "".join(pieces)


@dataclass(frozen=True)
class Display:
    """Hold how cat marks up each line"""

    number_all: bool
    number_nonblank: bool
    show_ends: bool
    show_tabs: bool
    show_nonprinting: bool
    squeeze_blank: bool

    def decorate(self, line: str) -> str:
        """Return one line with the display options applied, numbering aside

        Args:
            line: The line with its newline kept, if it had one

        Returns:
            The marked-up line
        """
        has_newline = line.endswith(NEWLINE)
        body = line[:-1] if has_newline else line
        if self.show_nonprinting:
            body = show_nonprinting(body, self.show_tabs)
        elif self.show_tabs:
            body = body.replace(TAB, TAB_DISPLAY)
        if self.show_ends and has_newline:
            body += LINE_END_DISPLAY
        return body + (NEWLINE if has_newline else "")


def source_lines(path_text: str, state: ShellState) -> AsyncIterator[str] | None:
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
        state.write_error(f"cat: {path_text}: Is a directory\n")
        return None
    if not path.exists():
        state.write_error(f"cat: {path_text}: No such file or directory\n")
        return None
    return file_lines(path)


async def concatenate(invocation: CommandInvocation, paths: list[str], display: Display) -> AsyncIterator[str]:
    """Yield every line of every source, marked up as the display options ask

    A source that cannot be read is reported and the exit status set to one

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The files to read in order, ``-`` meaning standard input
        display: How each line is marked up

    Yields:
        Each line, numbered and decorated when asked
    """
    line_number = 0
    previous_blank = False
    for path_text in paths:
        if path_text == STDIN_PATH:
            lines: AsyncIterator[str] | None = stdin_lines(invocation.stdin, invocation.stdin_kind)
        else:
            lines = source_lines(path_text, invocation.state)
        if lines is None:
            invocation.exit_status.code = EXIT_CODE_FAILURE
            continue
        try:
            async for line in lines:
                blank = line == NEWLINE
                if display.squeeze_blank and blank and previous_blank:
                    continue
                previous_blank = blank
                decorated = display.decorate(line)
                if display.number_all or (display.number_nonblank and not blank):
                    line_number += 1
                    yield f"{line_number:>{LINE_NUMBER_WIDTH}}\t{decorated}"
                else:
                    yield decorated
        finally:
            await close_iterator(lines)


class CatCommand(Command):
    """Concatenate files or standard input"""

    name = "cat"
    summary = "concatenate files and print on the standard output"
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
        parser.add_argument("-A", "--show-all", action="store_true", help="equivalent to -vET")
        parser.add_argument("-b", "--number-nonblank", action="store_true", help="number nonempty output lines")
        parser.add_argument("-e", action="store_true", dest="show_ends_nonprinting", help="equivalent to -vE")
        parser.add_argument("-E", "--show-ends", action="store_true", help="display $ at end of each line")
        parser.add_argument("-n", "--number", action="store_true", help="number all output lines")
        parser.add_argument("-s", "--squeeze-blank", action="store_true", help="suppress repeated empty output lines")
        parser.add_argument("-t", action="store_true", dest="show_tabs_nonprinting", help="equivalent to -vT")
        parser.add_argument("-T", "--show-tabs", action="store_true", help="display TAB characters as ^I")
        parser.add_argument("-v", "--show-nonprinting", action="store_true", help="use ^ and M- notation")
        parser.add_argument("paths", nargs="*", help="files to read, - for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        display = Display(
            number_all=parsed.number and not parsed.number_nonblank,
            number_nonblank=parsed.number_nonblank,
            show_ends=parsed.show_ends or parsed.show_all or parsed.show_ends_nonprinting,
            show_tabs=parsed.show_tabs or parsed.show_all or parsed.show_tabs_nonprinting,
            show_nonprinting=(
                parsed.show_nonprinting
                or parsed.show_all
                or parsed.show_ends_nonprinting
                or parsed.show_tabs_nonprinting
            ),
            squeeze_blank=parsed.squeeze_blank,
        )
        paths = parsed.paths or [STDIN_PATH]
        if invocation.stdin_kind == InputKind.ARGUMENTS:
            paths = [path for path in paths if path != STDIN_PATH]
        return CommandResult(stdout=concatenate(invocation, paths, display), exit_code=EXIT_CODE_SUCCESS)
