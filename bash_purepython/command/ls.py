"""Implement the ls command"""

# Standard libraries
import math
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState

SIZE_UNITS = ("K", "M", "G", "T", "P", "E")
SIZE_UNIT_FACTOR = 1024
SINGLE_DIGIT_LIMIT = 10
COLUMN_SEPARATOR = "  "
DEFAULT_PATH = "."


def format_size(size_bytes: int) -> str:
    """Return a byte count in the short form ls -lh uses, such as 4.0K or 12M

    Args:
        size_bytes: The size to format

    Returns:
        Plain bytes below one kilobyte, otherwise the size with a one-letter unit
    """
    if size_bytes < SIZE_UNIT_FACTOR:
        return str(size_bytes)
    value = size_bytes / SIZE_UNIT_FACTOR
    for unit in SIZE_UNITS:
        if value < SINGLE_DIGIT_LIMIT:
            tenths = math.ceil(value * 10)
            if tenths < SINGLE_DIGIT_LIMIT * 10:
                return f"{tenths / 10:.1f}{unit}"
        whole = math.ceil(value)
        if whole < SIZE_UNIT_FACTOR or unit == SIZE_UNITS[-1]:
            return f"{whole}{unit}"
        value /= SIZE_UNIT_FACTOR
    return f"{math.ceil(value)}{SIZE_UNITS[-1]}"


def entries_of(path: Path, show_all: bool, recursive: bool) -> list[Path]:
    """Return the entries a directory lists

    Args:
        path: The directory
        show_all: Whether hidden entries are included
        recursive: Whether every descendant is included

    Returns:
        The entries sorted by name
    """
    entries = list(path.rglob("*")) if recursive else list(path.iterdir())
    if not show_all:
        entries = [entry for entry in entries if not entry.name.startswith(".")]
    return sorted(entries)


def format_entries(entries: list[Path], base: Path, long_listing: bool, human_readable: bool) -> str:
    """Return the listing text for one group of entries

    Args:
        entries: The entries to show
        base: The directory the names are shown relative to
        long_listing: Whether each entry gets a line with its type and size
        human_readable: Whether sizes use K, M and G

    Returns:
        The listing, empty when there are no entries
    """
    names = [entry.relative_to(base).as_posix() if entry != base else entry.name for entry in entries]
    if long_listing:
        lines: list[str] = []
        for entry, shown in zip(entries, names, strict=True):
            size = entry.stat().st_size
            kind = "d" if entry.is_dir() else "f"
            lines.append(f"{kind} {format_size(size) if human_readable else size} {shown}\n")
        return "".join(lines)
    return COLUMN_SEPARATOR.join(names) + "\n" if names else ""


class LsCommand(Command):
    """List files and directories"""

    name = "ls"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """List each path, with a header per directory when several paths are given

        Args:
            invocation: The call to perform

        Returns:
            The listing and exit code one if any path was missing
        """
        parser = CommandArgumentParser("ls", "List files in the given directories")
        parser.add_argument("-l", "--long", action="store_true", help="long listing with type and size")
        parser.add_argument("-h", "--human-readable", action="store_true", help="with -l, sizes like 1.5K")
        parser.add_argument("-a", "--all", action="store_true", help="include hidden entries")
        parser.add_argument("-R", "-r", "--recursive", action="store_true", help="list every descendant")
        parser.add_argument("paths", nargs="*", default=[DEFAULT_PATH], help="files or directories to list")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        exit_code = EXIT_CODE_SUCCESS
        pieces: list[str] = []
        show_headers = len(parsed.paths) > 1
        for path_text in parsed.paths:
            text = self.list_one(path_text, parsed, state)
            if text is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            if show_headers and state.resolve_path(path_text).is_dir():
                pieces.append(f"{path_text}:\n")
            pieces.append(text)
        return CommandResult(stdout="".join(pieces), exit_code=exit_code)

    def list_one(self, path_text: str, parsed: object, state: ShellState) -> str | None:
        """Return the listing of one path, or None after reporting that it is missing

        Args:
            path_text: The path as written
            parsed: The parsed options
            state: The shell state for paths and errors

        Returns:
            The listing text, or None
        """
        path = state.resolve_path(path_text)
        if not path.exists():
            state.write_error(f"ls: cannot access '{path_text}': No such file or directory\n")
            return None
        if path.is_dir():
            entries = entries_of(path, parsed.all, parsed.recursive)
            return format_entries(entries, path, parsed.long, parsed.human_readable)
        return format_entries([path], path.parent, parsed.long, parsed.human_readable)
