"""Implement the md5sum, sha1sum, sha256sum and sha512sum commands"""

# Standard libraries
import hashlib
from typing import ClassVar

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.gzip import read_stdin_bytes
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState
from bash_purepython.streams import TEXT_ENCODING

STDIN_PATH = "-"
STDIN_LABEL = "'standard input'"
CHECKSUM_SEPARATOR = "  "
CHECK_LINE_FIELD_COUNT = 2
BINARY_MARKER = "*"


def digest_hex(algorithm: str, data: bytes) -> str:
    """Return the hex digest of data under one algorithm

    Args:
        algorithm: A hashlib algorithm name
        data: The bytes to hash

    Returns:
        The lowercase hex digest
    """
    return hashlib.new(algorithm, data).hexdigest()


def parse_check_line(line: str) -> tuple[str, str] | None:
    """Return the digest and name on one line of a checksum file

    Args:
        line: A line such as ``<hex>  <name>``

    Returns:
        The digest and the name, or None when the line is not in that form
    """
    stripped = line.rstrip("\r\n")
    fields = stripped.split(" ", 1)
    if len(fields) != CHECK_LINE_FIELD_COUNT or not fields[0]:
        return None
    name = fields[1].lstrip(" ")
    if name.startswith(BINARY_MARKER):
        name = name[len(BINARY_MARKER) :]
    return fields[0].lower(), name


class HashCommand(Command):
    """Print or check a message digest of files or standard input"""

    name = "sha256sum"
    summary = "print SHA-256 checksums"
    algorithm: ClassVar[str] = "sha256"
    algorithm_label: ClassVar[str] = "SHA-256"
    input_kinds = frozenset(
        {InputKind.STREAM_BYTES, InputKind.BYTES, InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS}
    )
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print ``<hex>  <name>`` for each file, or verify a checksum file under -c

        Args:
            invocation: The call to perform

        Returns:
            One line per file, and exit code one if any file was missing or failed to verify
        """
        parser = CommandArgumentParser(self.name, f"Print or check {self.algorithm_label} checksums")
        parser.add_argument("-c", "--check", action="store_true", help="read checksums from the files and check them")
        parser.add_argument("paths", nargs="*", help="files to read, - or none for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        lines: list[str] = []
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths or [STDIN_PATH]:
            data = await self.read_source(path_text, invocation)
            if data is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            if parsed.check:
                label = STDIN_LABEL if path_text == STDIN_PATH else path_text
                checksum_text = data.decode(TEXT_ENCODING, errors="replace")
                exit_code = max(exit_code, self.check(checksum_text, label, lines, invocation.state))
            else:
                lines.append(f"{digest_hex(self.algorithm, data)}{CHECKSUM_SEPARATOR}{path_text}\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)

    async def read_source(self, path_text: str, invocation: CommandInvocation) -> bytes | None:
        """Return the bytes of one file or of standard input, or None after reporting a missing file

        Args:
            path_text: The path as written, or ``-``
            invocation: The call providing standard input and the shell state

        Returns:
            The bytes, or None
        """
        if path_text == STDIN_PATH:
            return await read_stdin_bytes(invocation)
        path = invocation.state.resolve_path(path_text)
        if path.is_dir():
            invocation.state.write_error(f"{self.name}: {path_text}: Is a directory\n")
            return None
        if not path.is_file():
            invocation.state.write_error(f"{self.name}: {path_text}: No such file or directory\n")
            return None
        return path.read_bytes()

    def check(self, checksum_text: str, label: str, lines: list[str], state: ShellState) -> int:
        """Verify every ``<hex>  <name>`` line, appending ``name: OK`` or ``name: FAILED`` for each

        Args:
            checksum_text: The contents of a checksum file
            label: The checksum file's name as reported in errors
            lines: Where the verdict lines go
            state: The shell state for resolving names and reporting the summary

        Returns:
            Zero when every file matched, one when any failed or the file held no checksum line at all
        """
        failed = 0
        missing = 0
        improper = 0
        checked = 0
        for line in checksum_text.splitlines():
            parsed_line = parse_check_line(line)
            if parsed_line is None:
                improper += 1
                continue
            checked += 1
            expected, name = parsed_line
            path = state.resolve_path(name)
            if not path.is_file():
                state.write_error(f"{self.name}: {name}: No such file or directory\n")
                lines.append(f"{name}: FAILED open or read\n")
                missing += 1
                continue
            if digest_hex(self.algorithm, path.read_bytes()) == expected:
                lines.append(f"{name}: OK\n")
            else:
                lines.append(f"{name}: FAILED\n")
                failed += 1
        if not checked:
            state.write_error(
                f"{self.name}: {label}: no properly formatted {self.algorithm.upper()} checksum lines found\n"
            )
            return EXIT_CODE_FAILURE
        if improper:
            described = "1 line is" if improper == 1 else f"{improper} lines are"
            state.write_error(f"{self.name}: WARNING: {described} improperly formatted\n")
        if missing:
            state.write_error(f"{self.name}: WARNING: {missing} listed file could not be read\n")
        if failed:
            state.write_error(f"{self.name}: WARNING: {failed} computed checksum did NOT match\n")
        return EXIT_CODE_FAILURE if failed or missing else EXIT_CODE_SUCCESS


class Md5sumCommand(HashCommand):
    """Print or check MD5 checksums"""

    name = "md5sum"
    summary = "print MD5 checksums"
    algorithm = "md5"
    algorithm_label = "MD5"


class Sha1sumCommand(HashCommand):
    """Print or check SHA-1 checksums"""

    name = "sha1sum"
    summary = "print SHA-1 checksums"
    algorithm = "sha1"
    algorithm_label = "SHA-1"


class Sha256sumCommand(HashCommand):
    """Print or check SHA-256 checksums"""

    name = "sha256sum"
    summary = "print SHA-256 checksums"
    algorithm = "sha256"
    algorithm_label = "SHA-256"


class Sha512sumCommand(HashCommand):
    """Print or check SHA-512 checksums"""

    name = "sha512sum"
    summary = "print SHA-512 checksums"
    algorithm = "sha512"
    algorithm_label = "SHA-512"
