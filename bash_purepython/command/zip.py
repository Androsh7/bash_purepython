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


def format_added_line(entry: zipfile.ZipInfo) -> str:
    """Return the ``adding:`` line zip prints for one entry

    Args:
        entry: The entry just written

    Returns:
        The line naming the entry, its method and the space saved
    """
    if entry.file_size == 0:
        saved_percent = 0
    else:
        saved_percent = round((entry.file_size - entry.compress_size) * PERCENT_SCALE / entry.file_size)
    method = "stored" if entry.compress_type == zipfile.ZIP_STORED else "deflated"
    return f"  adding: {entry.filename} ({method} {saved_percent}%)\n"


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
        lines: list[str] = []
        destination = archive_path(parsed.archive, state)
        with zipfile.ZipFile(
            destination, "w", compression=compression, compresslevel=DEFAULT_COMPRESSION_LEVEL
        ) as archive:
            for source_text in parsed.sources:
                source = state.resolve_path(source_text)
                if not source.exists():
                    state.write_error(f"zip warning: name not matched: {source_text}\n")
                    exit_code = MISSING_MEMBER_EXIT_CODE
                    continue
                for path, entry_name in self.entries(source, Path(source_text).as_posix(), parsed.recurse_paths):
                    archive.write(path, arcname=entry_name)
                    lines.append(format_added_line(archive.getinfo(entry_name)))
        if not archive.namelist():
            destination.unlink()
            state.write_error("zip error: Nothing to do!\n")
            return CommandResult(stdout="", exit_code=NOTHING_TO_DO_EXIT_CODE)
        return CommandResult(stdout="" if parsed.quiet else "".join(lines), exit_code=exit_code)

    def entries(self, source: Path, entry_name: str, recurse: bool) -> list[tuple[Path, str]]:
        """Return the paths one source contributes with the names they take in the archive

        Args:
            source: The file or directory
            entry_name: The name the source itself takes
            recurse: Whether a directory's contents are included

        Returns:
            The path and archive name of each entry, a directory first and its contents after
        """
        if not source.is_dir():
            return [(source, entry_name)]
        directory_name = entry_name.rstrip("/") + "/"
        entries = [(source, directory_name)]
        if not recurse:
            return entries
        for child in sorted(source.rglob("*")):
            child_name = directory_name + child.relative_to(source).as_posix()
            entries.append((child, child_name + "/" if child.is_dir() else child_name))
        return entries
