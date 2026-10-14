"""Implement the xxd command"""

# Standard libraries
import re
from dataclasses import dataclass

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.gzip import read_stdin_bytes
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS
from bash_purepython.streams import TEXT_ENCODING

STDIN_PATH = "-"
DEFAULT_COLUMNS = 16
DEFAULT_PLAIN_COLUMNS = 30
DEFAULT_GROUP_SIZE = 2
NO_GROUPING = 0
OFFSET_WIDTH = 8
HEX_ASCII_SEPARATOR = "  "
FIRST_PRINTABLE = 0x20
LAST_PRINTABLE = 0x7E
UNPRINTABLE_MARK = "."
HEX_DIGITS_PER_BYTE = 2
DUMP_LINE_PATTERN = re.compile(r"^([0-9a-fA-F]+):(.*)$")
NON_HEX_PATTERN = re.compile(r"[^0-9a-fA-F]")


@dataclass(frozen=True)
class DumpOptions:
    """Hold the shape of a hex dump"""

    columns: int
    group_size: int
    plain: bool


def hex_field_width(columns: int, group_size: int) -> int:
    """Return the width of the hex column of a full line

    Args:
        columns: Bytes per line
        group_size: Bytes per space-separated group, zero for no spaces

    Returns:
        The characters a full line's hex column takes
    """
    if group_size == NO_GROUPING:
        return columns * HEX_DIGITS_PER_BYTE
    group_count = (columns + group_size - 1) // group_size
    return columns * HEX_DIGITS_PER_BYTE + group_count - 1


def format_hex_groups(chunk: bytes, group_size: int) -> str:
    """Return the bytes as lowercase hex, a space between each group

    Args:
        chunk: The bytes of one line
        group_size: Bytes per group, zero for no spaces

    Returns:
        The hex text
    """
    if group_size == NO_GROUPING:
        return chunk.hex()
    return " ".join(chunk[start : start + group_size].hex() for start in range(0, len(chunk), group_size))


def format_ascii(chunk: bytes) -> str:
    """Return the bytes as printable characters, a dot for every other value

    Args:
        chunk: The bytes of one line

    Returns:
        The text column
    """
    return "".join(chr(value) if FIRST_PRINTABLE <= value <= LAST_PRINTABLE else UNPRINTABLE_MARK for value in chunk)


def format_dump(data: bytes, options: DumpOptions, first_offset: int) -> str:
    """Return the hex dump xxd prints

    Args:
        data: The bytes to dump
        options: The line shape
        first_offset: The offset shown on the first line

    Returns:
        One line per group of columns bytes
    """
    lines: list[str] = []
    for start in range(0, len(data), options.columns):
        chunk = data[start : start + options.columns]
        if options.plain:
            lines.append(chunk.hex())
            continue
        offset = f"{first_offset + start:0{OFFSET_WIDTH}x}"
        hex_text = format_hex_groups(chunk, options.group_size).ljust(
            hex_field_width(options.columns, options.group_size)
        )
        lines.append(f"{offset}: {hex_text}{HEX_ASCII_SEPARATOR}{format_ascii(chunk)}")
    return "".join(f"{line}\n" for line in lines)


def reverse_plain(text: str) -> bytes:
    """Return the bytes a plain hex dump stands for, ignoring whitespace

    Args:
        text: The hex text

    Raises:
        ValueError: If the text holds a character that is not a hex digit or an odd number of digits

    Returns:
        The decoded bytes
    """
    digits = "".join(text.split())
    if NON_HEX_PATTERN.search(digits):
        raise ValueError(digits)
    return bytes.fromhex(digits)


def reverse_dump(text: str, columns: int) -> bytes:
    """Return the bytes a normal hex dump stands for, honouring each line's offset

    Args:
        text: The dump text
        columns: Bytes per line, which caps how much hex is read from each line

    Raises:
        ValueError: If a line's hex column is malformed

    Returns:
        The decoded bytes, zero-filled where the offsets leave gaps
    """
    output = bytearray()
    for line in text.splitlines():
        match = DUMP_LINE_PATTERN.match(line)
        if match is None:
            continue
        offset = int(match.group(1), 16)
        hex_column = match.group(2).lstrip(" ").split(HEX_ASCII_SEPARATOR, 1)[0]
        chunk = reverse_plain(hex_column)[:columns]
        if len(output) < offset:
            output.extend(bytes(offset - len(output)))
        output[offset : offset + len(chunk)] = chunk
    return bytes(output)


class XxdCommand(Command):
    """Make a hex dump of a file or standard input, or turn one back into bytes"""

    name = "xxd"
    summary = "make a hex dump, or reverse one"
    input_kinds = frozenset(
        {InputKind.STREAM_BYTES, InputKind.BYTES, InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS}
    )
    output_kinds = frozenset({OutputKind.BYTES})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Dump the input as hex, or reverse a dump under -r

        Args:
            invocation: The call to perform

        Returns:
            The dump text or the reversed bytes, and the exit code
        """
        parser = CommandArgumentParser(self.name, "Make a hex dump, or reverse one")
        parser.add_argument("-p", "--plain", action="store_true", help="plain hex, no offsets or text column")
        parser.add_argument("-r", "--revert", action="store_true", help="turn a dump back into bytes")
        parser.add_argument("-l", "--len", dest="length", type=int, default=None, help="stop after this many bytes")
        parser.add_argument("-s", "--seek", type=int, default=0, help="start at this offset")
        parser.add_argument("-c", "--cols", type=int, default=None, help="bytes per line")
        parser.add_argument("-g", "--groupsize", type=int, default=DEFAULT_GROUP_SIZE, help="bytes per group")
        parser.add_argument("source", nargs="?", default=STDIN_PATH, help="the file to read, - for standard input")
        parser.add_argument("destination", nargs="?", default=None, help="the file to write instead of standard output")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=b"", exit_code=parsed)
        state = invocation.state
        if parsed.source == STDIN_PATH:
            data = await read_stdin_bytes(invocation)
        else:
            source = state.resolve_path(parsed.source)
            if not source.is_file():
                state.write_error(f"xxd: {parsed.source}: No such file or directory\n")
                return CommandResult(stdout=b"", exit_code=EXIT_CODE_FAILURE)
            data = source.read_bytes()
        columns = (
            parsed.cols if parsed.cols is not None else (DEFAULT_PLAIN_COLUMNS if parsed.plain else DEFAULT_COLUMNS)
        )
        if columns <= 0 or parsed.groupsize < 0:
            state.write_error("xxd: invalid number of columns or group size\n")
            return CommandResult(stdout=b"", exit_code=EXIT_CODE_FAILURE)
        if parsed.revert:
            text = data.decode(TEXT_ENCODING, errors="replace")
            try:
                output = reverse_plain(text) if parsed.plain else reverse_dump(text, columns)
            except ValueError:
                state.write_error("xxd: not a hex dump\n")
                return CommandResult(stdout=b"", exit_code=EXIT_CODE_FAILURE)
        else:
            selected = data[parsed.seek :]
            if parsed.length is not None:
                selected = selected[: parsed.length]
            options = DumpOptions(columns=columns, group_size=min(parsed.groupsize, columns), plain=parsed.plain)
            output = format_dump(selected, options, parsed.seek).encode(TEXT_ENCODING)
        if parsed.destination is not None:
            state.resolve_path(parsed.destination).write_bytes(output)
            return CommandResult(stdout=b"", exit_code=EXIT_CODE_SUCCESS)
        return CommandResult(stdout=output, exit_code=EXIT_CODE_SUCCESS)
