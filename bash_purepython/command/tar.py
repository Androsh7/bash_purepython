"""Implement the tar command"""

# Standard libraries
import io
import stat
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.gzip import read_stdin_bytes
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, ShellState
from bash_purepython.streams import TEXT_ENCODING

STDIO_PATH = "-"
TAR_FAILURE_EXIT_CODE = 2
BUNDLED_FLAG_CHARACTERS = frozenset("cxtfzvjJC")
GZIP_WRITE_MODE = "w:gz"
BZIP2_WRITE_MODE = "w:bz2"
XZ_WRITE_MODE = "w:xz"
PLAIN_WRITE_MODE = "w"
AUTO_READ_MODE = "r:*"
DEFAULT_OWNER = "user"
LISTING_TIME_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class TarOptions:
    """Hold the options that shape one tar call"""

    create: bool
    extract: bool
    list_members: bool
    archive: str
    verbose: bool
    write_mode: str
    directory: str | None
    members: list[str]


def normalise_arguments(arguments: list[str]) -> list[str]:
    """Return the arguments with an old-style bundled first argument such as ``czf`` rewritten as ``-czf``

    Args:
        arguments: The arguments after the command name

    Returns:
        The arguments argparse can read
    """
    if not arguments:
        return arguments
    first = arguments[0]
    if first and not first.startswith("-") and set(first) <= BUNDLED_FLAG_CHARACTERS:
        return ["-" + first, *arguments[1:]]
    return arguments


def write_mode_for(gzip_requested: bool, bzip2_requested: bool, xz_requested: bool) -> str:
    """Return the tarfile mode that writes with the requested compression

    Args:
        gzip_requested: Whether -z was given
        bzip2_requested: Whether -j was given
        xz_requested: Whether -J was given

    Returns:
        The mode string for tarfile.open
    """
    if gzip_requested:
        return GZIP_WRITE_MODE
    if bzip2_requested:
        return BZIP2_WRITE_MODE
    if xz_requested:
        return XZ_WRITE_MODE
    return PLAIN_WRITE_MODE


def format_member_line(member: tarfile.TarInfo) -> str:
    """Return the long listing line tar -tv prints for one member

    Args:
        member: The archive member

    Returns:
        The mode, owner, size, time and name
    """
    mode = stat.filemode(member.mode | (stat.S_IFDIR if member.isdir() else stat.S_IFREG))
    owner = f"{member.uname or DEFAULT_OWNER}/{member.gname or DEFAULT_OWNER}"
    moment = time.strftime(LISTING_TIME_FORMAT, time.localtime(member.mtime))
    name = member.name + ("/" if member.isdir() and not member.name.endswith("/") else "")
    return f"{mode} {owner} {member.size:>8} {moment} {name}"


class TarCommand(Command):
    """Create, list and extract tar archives, optionally compressed"""

    name = "tar"
    summary = "create, list and extract tar archives"
    input_kinds = frozenset({InputKind.BYTES, InputKind.STREAM_BYTES, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.BYTES})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Create, list or extract one archive, which may be standard input or output

        Args:
            invocation: The call to perform

        Returns:
            The archive bytes when creating to standard output, otherwise the listing or nothing
        """
        parser = CommandArgumentParser(self.name, "Create, list and extract tar archives")
        parser.add_argument("-c", "--create", action="store_true", help="create a new archive")
        parser.add_argument("-x", "--extract", action="store_true", help="extract files from an archive")
        parser.add_argument("-t", "--list", action="store_true", help="list the contents of an archive")
        parser.add_argument("-f", "--file", default=None, help="the archive, - for standard input or output")
        parser.add_argument("-v", "--verbose", action="store_true", help="list each file processed")
        parser.add_argument("-z", "--gzip", action="store_true", help="filter the archive through gzip")
        parser.add_argument("-j", "--bzip2", action="store_true", help="filter the archive through bzip2")
        parser.add_argument("-J", "--xz", action="store_true", help="filter the archive through xz")
        parser.add_argument("-C", "--directory", default=None, help="change to this directory first")
        parser.add_argument("members", nargs="*", help="files to add, or members to extract")
        parsed = parse_command_arguments(parser, normalise_arguments(invocation.arguments), invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=b"", exit_code=parsed)
        state = invocation.state
        if sum([parsed.create, parsed.extract, parsed.list]) != 1:
            state.write_error("tar: You must specify exactly one of the '-ctx' options\n")
            return CommandResult(stdout=b"", exit_code=TAR_FAILURE_EXIT_CODE)
        if parsed.file is None:
            state.write_error("tar: no archive given, use -f\n")
            return CommandResult(stdout=b"", exit_code=TAR_FAILURE_EXIT_CODE)
        options = TarOptions(
            create=parsed.create,
            extract=parsed.extract,
            list_members=parsed.list,
            archive=parsed.file,
            verbose=parsed.verbose,
            write_mode=write_mode_for(parsed.gzip, parsed.bzip2, parsed.xz),
            directory=parsed.directory,
            members=parsed.members,
        )
        base = state.resolve_path(options.directory) if options.directory else state.cwd
        if options.directory and not base.is_dir():
            state.write_error(f"tar: {options.directory}: Cannot open: No such file or directory\n")
            return CommandResult(stdout=b"", exit_code=TAR_FAILURE_EXIT_CODE)
        if options.create:
            return self.create(options, base, state)
        archive_bytes = await self.read_archive(options.archive, invocation)
        if archive_bytes is None:
            return CommandResult(stdout=b"", exit_code=TAR_FAILURE_EXIT_CODE)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode=AUTO_READ_MODE) as archive:
                if options.list_members:
                    return CommandResult(stdout=self.list_archive(archive, options), exit_code=EXIT_CODE_SUCCESS)
                return self.extract(archive, options, base, state)
        except tarfile.ReadError:
            state.write_error(f"tar: {options.archive}: This does not look like a tar archive\n")
            return CommandResult(stdout=b"", exit_code=TAR_FAILURE_EXIT_CODE)

    async def read_archive(self, archive_text: str, invocation: CommandInvocation) -> bytes | None:
        """Return the bytes of the archive named, or of standard input for ``-``

        Args:
            archive_text: The archive path as written, or ``-``
            invocation: The call providing standard input and the shell state

        Returns:
            The archive bytes, or None after reporting a missing file
        """
        if archive_text == STDIO_PATH:
            return await read_stdin_bytes(invocation)
        path = invocation.state.resolve_path(archive_text)
        if not path.is_file():
            invocation.state.write_error(f"tar: {archive_text}: Cannot open: No such file or directory\n")
            return None
        return path.read_bytes()

    def create(self, options: TarOptions, base: Path, state: ShellState) -> CommandResult:
        """Build an archive from the named members

        Args:
            options: The call's options
            base: The directory member paths are relative to
            state: The shell state for errors

        Returns:
            The archive bytes when writing to standard output, otherwise nothing, and the exit code
        """
        to_stdout = options.archive == STDIO_PATH
        buffer = io.BytesIO()
        exit_code = EXIT_CODE_SUCCESS
        verbose_lines: list[str] = []
        with tarfile.open(fileobj=buffer, mode=options.write_mode) as archive:
            for member_text in options.members:
                target = base / member_text
                if not target.exists():
                    state.write_error(f"tar: {member_text}: Cannot stat: No such file or directory\n")
                    exit_code = TAR_FAILURE_EXIT_CODE
                    continue
                archive_name = Path(member_text).as_posix()
                archive.add(target, arcname=archive_name, recursive=False)
                verbose_lines.append(archive_name + ("/" if target.is_dir() else "") + "\n")
                if target.is_dir():
                    for child in sorted(target.rglob("*")):
                        child_name = (Path(archive_name) / child.relative_to(target)).as_posix()
                        archive.add(child, arcname=child_name, recursive=False)
                        verbose_lines.append(child_name + ("/" if child.is_dir() else "") + "\n")
        if exit_code != EXIT_CODE_SUCCESS:
            state.write_error("tar: Exiting with failure status due to previous errors\n")
        verbose_text = "".join(verbose_lines) if options.verbose else ""
        if to_stdout:
            if verbose_text:
                state.write_error(verbose_text)
            return CommandResult(stdout=buffer.getvalue(), exit_code=exit_code)
        state.resolve_path(options.archive).write_bytes(buffer.getvalue())
        return CommandResult(stdout=verbose_text.encode(TEXT_ENCODING), exit_code=exit_code)

    def list_archive(self, archive: tarfile.TarFile, options: TarOptions) -> bytes:
        """Return the names, or the long lines under -v, of every member

        Args:
            archive: The open archive
            options: The call's options

        Returns:
            One line per member
        """
        lines: list[str] = []
        for member in archive.getmembers():
            if options.members and not self.member_selected(member.name, options.members):
                continue
            if options.verbose:
                lines.append(format_member_line(member))
            else:
                lines.append(member.name + ("/" if member.isdir() and not member.name.endswith("/") else ""))
        return "".join(f"{line}\n" for line in lines).encode(TEXT_ENCODING)

    def member_selected(self, member_name: str, selected: list[str]) -> bool:
        """Return whether a member is one of those named, or inside a directory that was

        Args:
            member_name: The member's name in the archive
            selected: The names given on the command line

        Returns:
            True when the member should be listed or extracted
        """
        normalised = member_name.rstrip("/")
        return any(normalised == name.rstrip("/") or normalised.startswith(name.rstrip("/") + "/") for name in selected)

    def extract(self, archive: tarfile.TarFile, options: TarOptions, base: Path, state: ShellState) -> CommandResult:
        """Write the archive's members under the base directory

        Args:
            archive: The open archive
            options: The call's options
            base: The directory to extract into
            state: The shell state for errors

        Returns:
            The names extracted under -v, and the exit code
        """
        members = [
            member
            for member in archive.getmembers()
            if not options.members or self.member_selected(member.name, options.members)
        ]
        exit_code = EXIT_CODE_SUCCESS
        for requested in options.members:
            if not any(self.member_selected(member.name, [requested]) for member in members):
                state.write_error(f"tar: {requested}: Not found in archive\n")
                exit_code = TAR_FAILURE_EXIT_CODE
        try:
            archive.extractall(path=base, members=members, filter="data")
        except tarfile.FilterError as error:
            state.write_error(f"tar: {error}\n")
            return CommandResult(stdout=b"", exit_code=TAR_FAILURE_EXIT_CODE)
        if exit_code != EXIT_CODE_SUCCESS:
            state.write_error("tar: Exiting with failure status due to previous errors\n")
        verbose_text = "".join(f"{member.name}\n" for member in members) if options.verbose else ""
        return CommandResult(stdout=verbose_text.encode(TEXT_ENCODING), exit_code=exit_code)
