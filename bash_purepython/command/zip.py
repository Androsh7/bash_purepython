"""Implement the zip command"""

# Standard libraries
import zipfile
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, ShellState

ZIP_SUFFIX = ".zip"
DEFAULT_COMPRESSION_LEVEL = 6
STORED_LEVEL = 0
PERCENT_SCALE = 100
MISSING_MEMBER_EXIT_CODE = 12
NOTHING_TO_DO_EXIT_CODE = 12
INVALID_ARCHIVE_EXIT_CODE = 3
CANNOT_CREATE_EXIT_CODE = 15
ADDED_VERB = "adding"
UPDATED_VERB = "updating"


def archive_path(archive_text: str, state: ShellState) -> Path:
    """Return where the archive is written, adding the zip suffix when the name has no suffix

    Args:
        archive_text: The archive name as written
        state: The shell state for resolving the path

    Returns:
        The archive path
    """
    path = state.resolve_path(archive_text)
    if path.suffix:
        return path
    return path.with_name(path.name + ZIP_SUFFIX)


def format_added_line(entry: zipfile.ZipInfo, verb: str) -> str:
    """Return the ``adding:`` or ``updating:`` line zip prints for one entry

    Args:
        entry: The entry just written
        verb: ``adding`` for a new entry or ``updating`` for one replaced

    Returns:
        The line naming the entry, its method and the space saved
    """
    if entry.file_size == 0:
        saved_percent = 0
    else:
        saved_percent = round((entry.file_size - entry.compress_size) * PERCENT_SCALE / entry.file_size)
    method = "stored" if entry.compress_type == zipfile.ZIP_STORED else "deflated"
    return f"{verb:>8}: {entry.filename} ({method} {saved_percent}%)\n"


def archive_entry_name(path: Path, entry_name: str) -> str:
    """Return the name an entry takes inside the archive, as the zip module normalises it

    Args:
        path: The file or directory on disk
        entry_name: The name as written on the command line

    Returns:
        The name without a drive or leading slashes, with a trailing slash for a directory
    """
    return zipfile.ZipInfo.from_file(path, arcname=entry_name).filename


class ZipCommand(Command):
    """Package files and directories into a zip archive"""

    name = "zip"
    summary = "package files into a zip archive"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Write every named source into the archive

        Args:
            invocation: The call to perform

        Returns:
            One ``adding:`` line per entry unless quiet, and the exit code
        """
        parser = CommandArgumentParser(self.name, "Package files into a zip archive")
        parser.add_argument("-r", "--recurse-paths", action="store_true", help="recurse into directories")
        parser.add_argument("-q", "--quiet", action="store_true", help="print nothing")
        parser.add_argument(
            "-0",
            dest="store_only",
            action="store_true",
            help="store entries without compressing them",
        )
        parser.add_argument("archive", help="the archive to write, .zip is added when it has no suffix")
        parser.add_argument("sources", nargs="+", help="files or directories to add")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        exit_code = EXIT_CODE_SUCCESS
        compression = zipfile.ZIP_STORED if parsed.store_only else zipfile.ZIP_DEFLATED
        destination = archive_path(parsed.archive, state)
        entries: list[tuple[Path, str]] = []
        for source_text in parsed.sources:
            source = state.resolve_path(source_text)
            if not source.exists():
                state.write_error(f"zip warning: name not matched: {source_text}\n")
                exit_code = MISSING_MEMBER_EXIT_CODE
                continue
            entries.extend(self.entries(source, Path(source_text).as_posix(), parsed.recurse_paths, destination))
        if not entries:
            state.write_error(f"zip error: Nothing to do! ({parsed.archive})\n")
            return CommandResult(stdout="", exit_code=NOTHING_TO_DO_EXIT_CODE)
        kept_members = self.existing_members(destination, {name for _, name in entries}, state)
        if kept_members is None:
            return CommandResult(stdout="", exit_code=INVALID_ARCHIVE_EXIT_CODE)
        replaced_names, kept = kept_members
        try:
            archive = zipfile.ZipFile(
                destination, "w", compression=compression, compresslevel=DEFAULT_COMPRESSION_LEVEL
            )
        except OSError as error:
            state.write_error(f"zip I/O error: {error.strerror}\n")
            state.write_error(f"zip error: Could not create output file ({parsed.archive})\n")
            return CommandResult(stdout="", exit_code=CANNOT_CREATE_EXIT_CODE)
        lines: list[str] = []
        with archive:
            for member, data in kept:
                archive.writestr(member, data)
            for path, entry_name in entries:
                archive.write(path, arcname=entry_name)
                verb = UPDATED_VERB if entry_name in replaced_names else ADDED_VERB
                lines.append(format_added_line(archive.getinfo(entry_name), verb))
        return CommandResult(stdout="" if parsed.quiet else "".join(lines), exit_code=exit_code)

    def existing_members(
        self, destination: Path, new_names: set[str], state: ShellState
    ) -> tuple[set[str], list[tuple[zipfile.ZipInfo, bytes]]] | None:
        """Return what an existing archive at the destination already holds

        Args:
            destination: The archive path
            new_names: The entry names about to be written, which replace existing ones
            state: The shell state for errors

        Returns:
            The existing names being replaced and the other members with their data, or None when the
            file is not a zip archive
        """
        if not destination.is_file():
            return set(), []
        replaced: set[str] = set()
        kept: list[tuple[zipfile.ZipInfo, bytes]] = []
        try:
            with zipfile.ZipFile(destination) as existing:
                for member in existing.infolist():
                    if member.filename in new_names:
                        replaced.add(member.filename)
                    else:
                        kept.append((member, existing.read(member)))
        except zipfile.BadZipFile:
            state.write_error(f"zip error: Zip file structure invalid ({destination.name})\n")
            return None
        return replaced, kept

    def entries(self, source: Path, entry_name: str, recurse: bool, excluded: Path) -> list[tuple[Path, str]]:
        """Return the paths one source contributes with the names they take in the archive

        Args:
            source: The file or directory
            entry_name: The name the source itself takes
            recurse: Whether a directory's contents are included
            excluded: The archive being written, which is never added to itself

        Returns:
            The path and archive name of each entry, a directory first and its contents after
        """
        if self.is_same_file(source, excluded):
            return []
        if not source.is_dir():
            return [(source, archive_entry_name(source, entry_name))]
        entries = [(source, archive_entry_name(source, entry_name))]
        if not recurse:
            return entries
        for child in sorted(source.rglob("*")):
            if self.is_same_file(child, excluded):
                continue
            child_name = entry_name.rstrip("/") + "/" + child.relative_to(source).as_posix()
            entries.append((child, archive_entry_name(child, child_name)))
        return entries

    def is_same_file(self, path: Path, other: Path) -> bool:
        """Return whether two paths name the same file on disk

        Args:
            path: One path
            other: The other path

        Returns:
            True when both resolve to the same location
        """
        try:
            return path.resolve() == other.resolve()
        except OSError:
            return False
