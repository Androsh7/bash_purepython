"""Implement the unzip command"""

# Standard libraries
import zipfile
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState

ZIP_SUFFIX = ".zip"
CANNOT_OPEN_EXIT_CODE = 9
LENGTH_WIDTH = 9
LISTING_HEADER = "  Length      Date    Time    Name\n---------  ---------- -----   ----\n"
LISTING_FOOTER_RULE = "---------                     -------\n"
DATE_TIME_FIELDS = 5


def find_archive(archive_text: str, state: ShellState) -> Path | None:
    """Return the archive named, trying the zip suffix when the name as written does not exist

    Args:
        archive_text: The archive as written
        state: The shell state for resolving the path

    Returns:
        The archive path, or None when neither spelling exists
    """
    path = state.resolve_path(archive_text)
    if path.is_file():
        return path
    with_suffix = path.with_name(path.name + ZIP_SUFFIX)
    return with_suffix if with_suffix.is_file() else None


def format_listing(archive: zipfile.ZipFile, members: list[zipfile.ZipInfo]) -> str:
    """Return the table unzip -l prints

    Args:
        archive: The open archive, for its name
        members: The entries to list

    Returns:
        The header, one line per entry and the totals
    """
    lines = [f"Archive:  {archive.filename}\n", LISTING_HEADER]
    for member in members:
        year, month, day, hour, minute = member.date_time[:DATE_TIME_FIELDS]
        lines.append(
            f"{member.file_size:>{LENGTH_WIDTH}}  {year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}   "
            f"{member.filename}\n"
        )
    total = sum(member.file_size for member in members)
    count = len(members)
    lines.append(LISTING_FOOTER_RULE)
    lines.append(f"{total:>{LENGTH_WIDTH}}                     {count} file{'' if count == 1 else 's'}\n")
    return "".join(lines)


def extraction_verb(member: zipfile.ZipInfo) -> str:
    """Return the word unzip prints while extracting one entry

    Args:
        member: The entry

    Returns:
        ``creating`` for a directory, ``extracting`` for a stored file, ``inflating`` otherwise
    """
    if member.is_dir():
        return "   creating:"
    if member.compress_type == zipfile.ZIP_STORED:
        return " extracting:"
    return "  inflating:"


class UnzipCommand(Command):
    """List and extract the members of a zip archive"""

    name = "unzip"
    summary = "list and extract zip archives"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """List the archive, or extract its members into the target directory

        Args:
            invocation: The call to perform

        Returns:
            The listing or the extraction log, and the exit code
        """
        parser = CommandArgumentParser(self.name, "List and extract zip archives")
        parser.add_argument("-l", "--list", action="store_true", help="list the archive's entries")
        parser.add_argument("-o", "--overwrite", action="store_true", help="overwrite existing files")
        parser.add_argument("-q", "--quiet", action="store_true", help="print nothing while extracting")
        parser.add_argument("-d", "--directory", default=None, help="extract into this directory")
        parser.add_argument("archive", help="the archive to read")
        parser.add_argument("members", nargs="*", help="entries to list or extract, all when none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        archive_path = find_archive(parsed.archive, state)
        if archive_path is None:
            state.write_error(f"unzip:  cannot find or open {parsed.archive}, {parsed.archive}{ZIP_SUFFIX}.\n")
            return CommandResult(stdout="", exit_code=CANNOT_OPEN_EXIT_CODE)
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile:
            state.write_error(f"unzip:  {parsed.archive}: End-of-central-directory signature not found.\n")
            return CommandResult(stdout="", exit_code=CANNOT_OPEN_EXIT_CODE)
        with archive:
            archive.filename = parsed.archive
            members = [
                member
                for member in archive.infolist()
                if not parsed.members or self.member_selected(member.filename, parsed.members)
            ]
            exit_code = EXIT_CODE_SUCCESS
            for requested in parsed.members:
                if not any(self.member_selected(member.filename, [requested]) for member in members):
                    state.write_error(f"caution: filename not matched:  {requested}\n")
                    exit_code = EXIT_CODE_FAILURE
            if parsed.list:
                return CommandResult(stdout=format_listing(archive, members), exit_code=exit_code)
            target = state.resolve_path(parsed.directory) if parsed.directory else state.cwd
            log = self.extract(archive, members, target, parsed.overwrite, state)
            if log is None:
                return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
            text = "" if parsed.quiet else f"Archive:  {parsed.archive}\n" + log
            return CommandResult(stdout=text, exit_code=exit_code)

    def member_selected(self, member_name: str, selected: list[str]) -> bool:
        """Return whether an entry is one of those named, or inside a directory that was

        Args:
            member_name: The entry's name in the archive
            selected: The names given on the command line

        Returns:
            True when the entry should be listed or extracted
        """
        normalised = member_name.rstrip("/")
        return any(normalised == name.rstrip("/") or normalised.startswith(name.rstrip("/") + "/") for name in selected)

    def extract(
        self, archive: zipfile.ZipFile, members: list[zipfile.ZipInfo], target: Path, overwrite: bool, state: ShellState
    ) -> str | None:
        """Write the entries under the target directory

        Args:
            archive: The open archive
            members: The entries to extract
            target: The directory to extract into
            overwrite: Whether an existing file is replaced
            state: The shell state for errors

        Returns:
            One line per entry, or None when an existing file was refused
        """
        lines: list[str] = []
        for member in members:
            destination = target / member.filename
            if destination.is_file() and not overwrite:
                state.write_error(f"unzip: {member.filename} already exists, use -o to overwrite\n")
                return None
            archive.extract(member, target)
            lines.append(f"{extraction_verb(member)} {member.filename}\n")
        return "".join(lines)
