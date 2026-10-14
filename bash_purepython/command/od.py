"""Implement the od command"""

# Standard libraries
import re
from dataclasses import dataclass
from enum import StrEnum

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.gzip import read_stdin_bytes
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

STDIN_PATH = "-"
BYTES_PER_LINE = 16
ADDRESS_WIDTH = 7
ADDRESS_HEX_WIDTH = 6
CHARACTER_FIELD_WIDTH = 4
BITS_PER_BYTE = 8
BITS_PER_OCTAL_DIGIT = 3
DEFAULT_ELEMENT_SIZE = 2
BYTE_ELEMENT_SIZE = 1
DUPLICATE_MARK = "*"
TYPE_PATTERN = re.compile(r"^([acdoux])([1248]?)$")
ESCAPED_CHARACTERS = {
    0: "\\0",
    7: "\\a",
    8: "\\b",
    9: "\\t",
    10: "\\n",
    11: "\\v",
    12: "\\f",
    13: "\\r",
}
FIRST_PRINTABLE = 0x20
LAST_PRINTABLE = 0x7E


class AddressRadix(StrEnum):
    """Name how od prints the offset at the start of each line"""

    OCTAL = "o"
    DECIMAL = "d"
    HEXADECIMAL = "x"
    NONE = "n"


class ElementFormat(StrEnum):
    """Name how od prints each element"""

    CHARACTER = "c"
    NAMED_CHARACTER = "a"
    OCTAL = "o"
    SIGNED_DECIMAL = "d"
    UNSIGNED_DECIMAL = "u"
    HEXADECIMAL = "x"


@dataclass(frozen=True)
class ElementType:
    """Hold one -t type: how each element is printed and how many bytes it spans"""

    element_format: ElementFormat
    size: int


def parse_type(text: str) -> ElementType | None:
    """Return the type a -t argument names

    Args:
        text: The argument, such as ``x1``, ``o2`` or ``c``

    Returns:
        The type, or None when the argument is not one od knows
    """
    match = TYPE_PATTERN.match(text)
    if match is None:
        return None
    element_format = ElementFormat(match.group(1))
    if element_format in (ElementFormat.CHARACTER, ElementFormat.NAMED_CHARACTER):
        return ElementType(element_format=element_format, size=BYTE_ELEMENT_SIZE)
    size = int(match.group(2)) if match.group(2) else DEFAULT_ELEMENT_SIZE
    return ElementType(element_format=element_format, size=size)


def field_width(element_type: ElementType) -> int:
    """Return the width of one printed element, which fits the largest value of its size

    Args:
        element_type: The type

    Returns:
        The character width
    """
    bits = element_type.size * BITS_PER_BYTE
    if element_type.element_format in (ElementFormat.CHARACTER, ElementFormat.NAMED_CHARACTER):
        return CHARACTER_FIELD_WIDTH - 1
    if element_type.element_format == ElementFormat.HEXADECIMAL:
        return element_type.size * 2
    if element_type.element_format == ElementFormat.OCTAL:
        return (bits + BITS_PER_OCTAL_DIGIT - 1) // BITS_PER_OCTAL_DIGIT
    if element_type.element_format == ElementFormat.UNSIGNED_DECIMAL:
        return len(str(2**bits - 1))
    return len(str(-(2 ** (bits - 1))))


def format_character(value: int) -> str:
    """Return one byte as od -c prints it

    Args:
        value: The byte

    Returns:
        The character, its backslash escape, or its three-digit octal value
    """
    if value in ESCAPED_CHARACTERS:
        return ESCAPED_CHARACTERS[value]
    if FIRST_PRINTABLE <= value <= LAST_PRINTABLE:
        return chr(value)
    return f"{value:03o}"


def format_element(chunk: bytes, element_type: ElementType) -> str:
    """Return one element, zero-padded to its size when the input ends early

    Args:
        chunk: The bytes of the element, little-endian
        element_type: How to print them

    Returns:
        The element right-aligned in its field
    """
    width = field_width(element_type)
    if element_type.element_format in (ElementFormat.CHARACTER, ElementFormat.NAMED_CHARACTER):
        return format_character(chunk[0]).rjust(width)
    padded = chunk.ljust(element_type.size, b"\0")
    signed = element_type.element_format == ElementFormat.SIGNED_DECIMAL
    value = int.from_bytes(padded, "little", signed=signed)
    if element_type.element_format == ElementFormat.HEXADECIMAL:
        return f"{value:0{width}x}"
    if element_type.element_format == ElementFormat.OCTAL:
        return f"{value:0{width}o}"
    return f"{value:>{width}}"


def format_address(offset: int, radix: AddressRadix) -> str:
    """Return the offset column for one line

    Args:
        offset: The byte offset
        radix: How to print it

    Returns:
        The offset, empty when no address is wanted
    """
    if radix == AddressRadix.NONE:
        return ""
    if radix == AddressRadix.HEXADECIMAL:
        return f"{offset:0{ADDRESS_HEX_WIDTH}x}"
    if radix == AddressRadix.DECIMAL:
        return f"{offset:0{ADDRESS_WIDTH}d}"
    return f"{offset:0{ADDRESS_WIDTH}o}"


def format_line(chunk: bytes, element_type: ElementType) -> str:
    """Return the elements of one line, each preceded by a space

    Args:
        chunk: The bytes of the line
        element_type: How to print them

    Returns:
        The element columns
    """
    elements = [
        format_element(chunk[start : start + element_type.size], element_type)
        for start in range(0, len(chunk), element_type.size)
    ]
    return "".join(f" {element}" for element in elements)


def format_dump(
    data: bytes, element_type: ElementType, radix: AddressRadix, first_offset: int, show_duplicates: bool
) -> str:
    """Return the whole dump, collapsing repeated lines into a star unless asked not to

    Args:
        data: The bytes to dump
        element_type: How each element is printed
        radix: How offsets are printed
        first_offset: The offset of the first byte
        show_duplicates: Whether repeated lines are printed rather than collapsed

    Returns:
        The lines, ending with the offset just past the last byte
    """
    lines: list[str] = []
    previous_body: str | None = None
    collapsed = False
    for start in range(0, len(data), BYTES_PER_LINE):
        chunk = data[start : start + BYTES_PER_LINE]
        body = format_line(chunk, element_type)
        if not show_duplicates and body == previous_body and len(chunk) == BYTES_PER_LINE:
            if not collapsed:
                lines.append(DUPLICATE_MARK)
                collapsed = True
            continue
        collapsed = False
        previous_body = body
        lines.append(format_address(first_offset + start, radix) + body)
    final_address = format_address(first_offset + len(data), radix)
    if final_address:
        lines.append(final_address)
    return "".join(f"{line}\n" for line in lines)


class OdCommand(Command):
    """Dump files or standard input in octal, hex, decimal or as characters"""

    name = "od"
    summary = "dump bytes in octal and other formats"
    input_kinds = frozenset(
        {InputKind.STREAM_BYTES, InputKind.BYTES, InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS}
    )
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Dump the named files one after another, or standard input

        Args:
            invocation: The call to perform

        Returns:
            The dump and the exit code
        """
        parser = CommandArgumentParser(self.name, "Dump files in octal and other formats")
        parser.add_argument("-A", "--address-radix", default=AddressRadix.OCTAL, help="offset radix: o, d, x or n")
        parser.add_argument("-t", "--format", default=None, help="element type such as x1, o2, d4, u1, c")
        parser.add_argument("-c", dest="characters", action="store_true", help="print bytes as characters")
        parser.add_argument("-x", dest="hex_shorts", action="store_true", help="print two-byte hex units")
        parser.add_argument("-o", dest="octal_shorts", action="store_true", help="print two-byte octal units")
        parser.add_argument("-d", dest="decimal_shorts", action="store_true", help="print two-byte unsigned units")
        parser.add_argument("-b", dest="octal_bytes", action="store_true", help="print one-byte octal units")
        parser.add_argument("-N", "--read-bytes", type=int, default=None, help="dump at most this many bytes")
        parser.add_argument("-j", "--skip-bytes", type=int, default=0, help="skip this many bytes first")
        parser.add_argument("-v", "--output-duplicates", action="store_true", help="print repeated lines")
        parser.add_argument("paths", nargs="*", help="files to read, - or none for standard input")
        parsed = parse_command_arguments(parser, self.split_joined_options(invocation.arguments), invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        try:
            radix = AddressRadix(parsed.address_radix)
        except ValueError:
            state.write_error(f"od: invalid radix '{parsed.address_radix}'; it must be one character from [doxn]\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        element_type = self.element_type(parsed)
        if element_type is None:
            state.write_error(f"od: invalid type string '{parsed.format}'\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        pieces: list[bytes] = []
        for path_text in parsed.paths or [STDIN_PATH]:
            if path_text == STDIN_PATH:
                pieces.append(await read_stdin_bytes(invocation))
                continue
            path = state.resolve_path(path_text)
            if not path.is_file():
                state.write_error(f"od: {path_text}: No such file or directory\n")
                return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
            pieces.append(path.read_bytes())
        data = b"".join(pieces)[parsed.skip_bytes :]
        if parsed.read_bytes is not None:
            data = data[: parsed.read_bytes]
        dump = format_dump(data, element_type, radix, parsed.skip_bytes, parsed.output_duplicates)
        return CommandResult(stdout=dump, exit_code=EXIT_CODE_SUCCESS)

    def split_joined_options(self, arguments: list[str]) -> list[str]:
        """Return the arguments with ``-An`` and ``-tx1`` split into an option and its value

        Args:
            arguments: The arguments after the command name

        Returns:
            The arguments argparse can read
        """
        split: list[str] = []
        for argument in arguments:
            if len(argument) > 2 and argument[:2] in ("-A", "-t", "-N", "-j"):
                split.extend([argument[:2], argument[2:]])
            else:
                split.append(argument)
        return split

    def element_type(self, parsed: object) -> ElementType | None:
        """Return the element type the options ask for, octal shorts by default

        Args:
            parsed: The parsed options

        Returns:
            The type, or None when the -t argument is not one od knows
        """
        if parsed.format is not None:
            return parse_type(parsed.format)
        if parsed.characters:
            return ElementType(element_format=ElementFormat.CHARACTER, size=BYTE_ELEMENT_SIZE)
        if parsed.hex_shorts:
            return ElementType(element_format=ElementFormat.HEXADECIMAL, size=DEFAULT_ELEMENT_SIZE)
        if parsed.decimal_shorts:
            return ElementType(element_format=ElementFormat.UNSIGNED_DECIMAL, size=DEFAULT_ELEMENT_SIZE)
        if parsed.octal_bytes:
            return ElementType(element_format=ElementFormat.OCTAL, size=BYTE_ELEMENT_SIZE)
        return ElementType(element_format=ElementFormat.OCTAL, size=DEFAULT_ELEMENT_SIZE)
