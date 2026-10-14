"""Implement the file command, which guesses what a file holds from its first bytes"""

# Standard libraries
import struct
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS
from bash_purepython.streams import TEXT_ENCODING

SAMPLE_SIZE_BYTES = 8192
ELF_MAGIC = b"\x7fELF"
ELF_CLASS_OFFSET = 4
ELF_DATA_OFFSET = 5
ELF_TYPE_OFFSET = 16
ELF_64_BIT = 2
ELF_BIG_ENDIAN = 2
ELF_TYPES = {1: "relocatable", 2: "executable", 3: "shared object", 4: "core file"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_DIMENSIONS_OFFSET = 16
PNG_DIMENSIONS_FORMAT = ">II"
JPEG_MAGIC = b"\xff\xd8\xff"
GZIP_MAGIC = b"\x1f\x8b"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
PDF_MAGIC = b"%PDF-"
PDF_VERSION_LENGTH = 3
DOS_MAGIC = b"MZ"
PE_HEADER_POINTER_OFFSET = 0x3C
PE_MAGIC = b"PE\0\0"
PE_MACHINE_OFFSET = 4
PE_MACHINE_64 = {0x8664, 0xAA64}
TAR_MAGIC = b"ustar"
TAR_MAGIC_OFFSET = 257
SHEBANG = b"#!"
ENV_INTERPRETER = "env"
TEXT_CONTROL_CHARACTERS = frozenset(b"\t\n\r\x0b\x0c\x1b\b")
ASCII_LIMIT = 0x80
FIRST_PRINTABLE = 0x20
DELETE_CHARACTER = 0x7F


def describe_elf(sample: bytes) -> str:
    """Return the description of an ELF file

    Args:
        sample: The first bytes of the file

    Returns:
        The word size, byte order and object type, or a note that the header is cut short
    """
    if len(sample) <= ELF_DATA_OFFSET:
        return "ELF (truncated)"
    bits = "64-bit" if sample[ELF_CLASS_OFFSET] == ELF_64_BIT else "32-bit"
    byte_order = "MSB" if sample[ELF_DATA_OFFSET] == ELF_BIG_ENDIAN else "LSB"
    object_type = ELF_TYPES.get(sample[ELF_TYPE_OFFSET] if len(sample) > ELF_TYPE_OFFSET else 0, "file")
    return f"ELF {bits} {byte_order} {object_type}"


def describe_png(sample: bytes) -> str:
    """Return the description of a PNG file with its dimensions when the header holds them

    Args:
        sample: The first bytes of the file

    Returns:
        The description
    """
    dimensions_end = PNG_DIMENSIONS_OFFSET + struct.calcsize(PNG_DIMENSIONS_FORMAT)
    if len(sample) < dimensions_end:
        return "PNG image data"
    width, height = struct.unpack(PNG_DIMENSIONS_FORMAT, sample[PNG_DIMENSIONS_OFFSET:dimensions_end])
    return f"PNG image data, {width} x {height}"


def describe_dos_executable(sample: bytes) -> str:
    """Return the description of a file that starts with the MZ header

    Args:
        sample: The first bytes of the file

    Returns:
        A PE32 or PE32+ executable when the PE header is found, otherwise an MS-DOS executable
    """
    pointer_end = PE_HEADER_POINTER_OFFSET + 4
    if len(sample) < pointer_end:
        return "MS-DOS executable"
    (header_offset,) = struct.unpack("<I", sample[PE_HEADER_POINTER_OFFSET:pointer_end])
    machine_end = header_offset + PE_MACHINE_OFFSET + 2
    if sample[header_offset : header_offset + len(PE_MAGIC)] != PE_MAGIC or len(sample) < machine_end:
        return "MS-DOS executable"
    (machine,) = struct.unpack("<H", sample[header_offset + PE_MACHINE_OFFSET : machine_end])
    return "PE32+ executable" if machine in PE_MACHINE_64 else "PE32 executable"


def describe_text(sample: bytes) -> str:
    """Return the description of a file that is text, or ``data`` when it is not

    Args:
        sample: The first bytes of the file

    Returns:
        The character set, with the line terminator style when it is notable
    """
    if any(
        (value < FIRST_PRINTABLE and value not in TEXT_CONTROL_CHARACTERS) or value == DELETE_CHARACTER
        for value in sample
    ):
        return "data"
    if all(value < ASCII_LIMIT for value in sample):
        character_set = "ASCII text"
    else:
        try:
            sample.decode(TEXT_ENCODING)
        except UnicodeDecodeError:
            return "data"
        character_set = "UTF-8 Unicode text"
    if b"\n" not in sample:
        return f"{character_set}, with no line terminators"
    if b"\r\n" in sample:
        return f"{character_set}, with CRLF line terminators"
    return character_set


def describe_script(sample: bytes) -> str:
    """Return the description of a file that starts with a shebang line

    Args:
        sample: The first bytes of the file

    Returns:
        The interpreter and the text kind
    """
    first_line = sample.split(b"\n", 1)[0][len(SHEBANG) :].strip().decode(TEXT_ENCODING, errors="replace")
    words = first_line.split()
    if not words:
        return f"{describe_text(sample)} executable"
    interpreter = words[1] if Path(words[0]).name == ENV_INTERPRETER and len(words) > 1 else words[0]
    return f"a {Path(interpreter).name} script, {describe_text(sample)} executable"


def describe_bytes(sample: bytes) -> str:
    """Return what the first bytes of a file say it holds

    Args:
        sample: The first bytes of the file

    Returns:
        The description file prints after the name
    """
    if not sample:
        return "empty"
    if sample.startswith(ELF_MAGIC):
        return describe_elf(sample)
    if sample.startswith(PNG_MAGIC):
        return describe_png(sample)
    if sample.startswith(JPEG_MAGIC):
        return "JPEG image data"
    if sample.startswith(GZIP_MAGIC):
        return "gzip compressed data"
    if sample.startswith(ZIP_MAGICS):
        return "Zip archive data"
    if sample.startswith(PDF_MAGIC):
        version = sample[len(PDF_MAGIC) : len(PDF_MAGIC) + PDF_VERSION_LENGTH].decode(TEXT_ENCODING, errors="replace")
        return f"PDF document, version {version}"
    if sample.startswith(DOS_MAGIC):
        return describe_dos_executable(sample)
    if sample[TAR_MAGIC_OFFSET : TAR_MAGIC_OFFSET + len(TAR_MAGIC)] == TAR_MAGIC:
        return "POSIX tar archive"
    if sample.startswith(SHEBANG):
        return describe_script(sample)
    return describe_text(sample)


class FileCommand(Command):
    """Print what kind of data each file holds"""

    name = "file"
    summary = "guess what a file holds"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print ``name: description`` for each path

        Args:
            invocation: The call to perform

        Returns:
            One line per path, and exit code one if any path was missing
        """
        parser = CommandArgumentParser(self.name, "Guess what a file holds")
        parser.add_argument("-b", "--brief", action="store_true", help="leave out the file name")
        parser.add_argument("paths", nargs="+", help="files to examine")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        lines: list[str] = []
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            if path.is_dir():
                description = "directory"
            elif path.is_file():
                with path.open("rb") as handle:
                    description = describe_bytes(handle.read(SAMPLE_SIZE_BYTES))
            else:
                description = f"cannot open '{path_text}' (No such file or directory)"
                exit_code = EXIT_CODE_FAILURE
            lines.append(f"{description}\n" if parsed.brief else f"{path_text}: {description}\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)
