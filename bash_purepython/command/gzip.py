"""Implement the gzip and gunzip commands"""

# Standard libraries
import gzip
from pathlib import Path
from typing import ClassVar

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState
from bash_purepython.streams import TEXT_ENCODING

GZIP_SUFFIX = ".gz"
DECOMPRESSED_SUFFIX = ".out"
DEFAULT_COMPRESSION_LEVEL = 6
FIXED_MODIFICATION_TIME = 0


async def read_stdin_bytes(invocation: CommandInvocation) -> bytes:
    """Return the whole of standard input as bytes

    Args:
        invocation: The call whose input is read

    Returns:
        The bytes, empty when there is no input
    """
    if invocation.stdin_kind == InputKind.ARGUMENTS:
        return b""
    if invocation.stdin_kind == InputKind.BYTES:
        return invocation.stdin
    if invocation.stdin_kind == InputKind.TEXT:
        return invocation.stdin.encode(TEXT_ENCODING)
    pieces: list[bytes] = []
    async for chunk in invocation.stdin:
        pieces.append(chunk if isinstance(chunk, bytes) else chunk.encode(TEXT_ENCODING))
    return b"".join(pieces)


def transform(data: bytes, decompress: bool, level: int) -> bytes:
    """Return data compressed or decompressed

    Args:
        data: The input bytes
        decompress: Whether to decompress rather than compress
        level: The compression level

    Raises:
        gzip.BadGzipFile: If decompressing data that is not gzip
    """
    if decompress:
        return gzip.decompress(data)
    return gzip.compress(data, compresslevel=level, mtime=FIXED_MODIFICATION_TIME)


def output_path(source: Path, decompress: bool) -> Path:
    """Return where the transformed file goes

    Args:
        source: The input file
        decompress: Whether the output is the decompressed file

    Returns:
        The input path with the gzip suffix added or removed
    """
    if not decompress:
        return source.with_name(source.name + GZIP_SUFFIX)
    if source.name.endswith(GZIP_SUFFIX):
        return source.with_name(source.name[: -len(GZIP_SUFFIX)])
    return source.with_name(source.name + DECOMPRESSED_SUFFIX)


class GzipCommand(Command):
    """Compress files with gzip, or decompress them with -d"""

    name = "gzip"
    input_kinds = frozenset(
        {InputKind.STREAM_BYTES, InputKind.BYTES, InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS}
    )
    output_kinds = frozenset({OutputKind.BYTES})
    decompress_by_default: ClassVar[bool] = False

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Compress or decompress each file, or standard input to standard output

        Args:
            invocation: The call to perform

        Returns:
            The transformed bytes when writing to standard output, otherwise nothing
        """
        parser = CommandArgumentParser(self.name, "Compress or decompress files with gzip")
        parser.add_argument("-d", "--decompress", action="store_true", help="decompress")
        parser.add_argument("-k", "--keep", action="store_true", help="keep input files")
        parser.add_argument("-c", "--stdout", action="store_true", help="write to standard output")
        parser.add_argument("-f", "--force", action="store_true", help="overwrite existing output")
        parser.add_argument(
            "-l", "--level", type=int, default=DEFAULT_COMPRESSION_LEVEL, choices=range(1, 10), help="compression level"
        )
        parser.add_argument("paths", nargs="*", help="input files, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=b"", exit_code=parsed)
        decompress = parsed.decompress or self.decompress_by_default
        state = invocation.state
        if not parsed.paths:
            try:
                data = transform(await read_stdin_bytes(invocation), decompress, parsed.level)
            except gzip.BadGzipFile:
                state.write_error(f"{self.name}: stdin: not in gzip format\n")
                return CommandResult(stdout=b"", exit_code=EXIT_CODE_FAILURE)
            return CommandResult(stdout=data, exit_code=EXIT_CODE_SUCCESS)
        output = bytearray()
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths:
            exit_code = max(exit_code, self.transform_file(path_text, decompress, parsed, output, state))
        return CommandResult(stdout=bytes(output), exit_code=exit_code)

    def transform_file(
        self, path_text: str, decompress: bool, parsed: object, output: bytearray, state: ShellState
    ) -> int:
        """Transform one file in place, or append its result to the output when writing to standard output

        Args:
            path_text: The input path as written
            decompress: Whether to decompress
            parsed: The parsed options
            output: Where bytes go when -c was given
            state: The shell state for paths and errors

        Returns:
            Zero on success, one on failure
        """
        source = state.resolve_path(path_text)
        if not source.is_file():
            state.write_error(f"{self.name}: {path_text}: No such file or directory\n")
            return EXIT_CODE_FAILURE
        try:
            data = transform(source.read_bytes(), decompress, parsed.level)
        except gzip.BadGzipFile:
            state.write_error(f"{self.name}: {path_text}: not in gzip format\n")
            return EXIT_CODE_FAILURE
        if parsed.stdout:
            output.extend(data)
            return EXIT_CODE_SUCCESS
        destination = output_path(source, decompress)
        if destination.exists() and not parsed.force:
            state.write_error(f"{self.name}: {destination.name} already exists; not overwritten\n")
            return EXIT_CODE_FAILURE
        destination.write_bytes(data)
        if not parsed.keep:
            source.unlink()
        return EXIT_CODE_SUCCESS


class GunzipCommand(GzipCommand):
    """Decompress gzip files"""

    name = "gunzip"
    decompress_by_default = True
