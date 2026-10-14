"""Implement the base64 command"""

# Standard libraries
import base64
import binascii

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.gzip import read_stdin_bytes
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

STDIN_PATH = "-"
DEFAULT_WRAP_COLUMNS = 76
NO_WRAP_COLUMNS = 0
LINE_END = b"\n"


def encode(data: bytes, wrap_columns: int) -> bytes:
    """Return data encoded as base64 text, wrapped to the column width

    Args:
        data: The bytes to encode
        wrap_columns: Characters per line, zero for one unbroken line

    Returns:
        The encoded text with a trailing newline, none when not wrapping, and empty for empty input
    """
    encoded = base64.b64encode(data)
    if not encoded:
        return b""
    if wrap_columns == NO_WRAP_COLUMNS:
        return encoded
    lines = [encoded[start : start + wrap_columns] for start in range(0, len(encoded), wrap_columns)]
    return LINE_END.join(lines) + LINE_END


def decode(text: bytes) -> bytes:
    """Return the bytes that base64 text stands for, ignoring line breaks

    Args:
        text: The encoded text

    Raises:
        binascii.Error: If the text is not valid base64

    Returns:
        The decoded bytes
    """
    stripped = b"".join(text.split())
    return base64.b64decode(stripped, validate=True)


class Base64Command(Command):
    """Encode files or standard input as base64, or decode them with -d"""

    name = "base64"
    summary = "encode or decode base64"
    input_kinds = frozenset(
        {InputKind.STREAM_BYTES, InputKind.BYTES, InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS}
    )
    output_kinds = frozenset({OutputKind.BYTES})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Encode or decode each file, or standard input when none is named

        Args:
            invocation: The call to perform

        Returns:
            The encoded text or decoded bytes, and the exit code
        """
        parser = CommandArgumentParser(self.name, "Encode or decode base64")
        parser.add_argument("-d", "--decode", action="store_true", help="decode instead of encoding")
        parser.add_argument(
            "-w", "--wrap", type=int, default=DEFAULT_WRAP_COLUMNS, help="wrap encoded lines after COLS, 0 to disable"
        )
        parser.add_argument("paths", nargs="*", help="files to read, - or none for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=b"", exit_code=parsed)
        state = invocation.state
        output = bytearray()
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths or [STDIN_PATH]:
            if path_text == STDIN_PATH:
                data = await read_stdin_bytes(invocation)
            else:
                path = state.resolve_path(path_text)
                if not path.is_file():
                    state.write_error(f"base64: {path_text}: No such file or directory\n")
                    exit_code = EXIT_CODE_FAILURE
                    continue
                data = path.read_bytes()
            if not parsed.decode:
                output.extend(encode(data, parsed.wrap))
                continue
            try:
                output.extend(decode(data))
            except binascii.Error:
                state.write_error("base64: invalid input\n")
                exit_code = EXIT_CODE_FAILURE
        return CommandResult(stdout=bytes(output), exit_code=exit_code)
