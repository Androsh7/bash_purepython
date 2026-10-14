"""Implement the tree command"""

# Standard libraries
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS

BRANCH = "├── "
LAST_BRANCH = "└── "
VERTICAL = "│   "
BLANK = "    "
HIDDEN_PREFIX = "."
DEFAULT_PATH = "."
MINIMUM_LEVEL = 1
ERROR_OPENING_DIRECTORY = "[error opening dir]"


def visible_children(directory: Path, show_all: bool, directories_only: bool) -> list[Path]:
    """Return the entries of a directory in display order

    Args:
        directory: The directory to list
        show_all: Whether entries whose name starts with a dot are included
        directories_only: Whether files are dropped from the listing

    Returns:
        The entries sorted by name
    """
    entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    if not show_all:
        entries = [entry for entry in entries if not entry.name.startswith(HIDDEN_PREFIX)]
    if directories_only:
        entries = [entry for entry in entries if entry.is_dir()]
    return entries


def render_directory(
    directory: Path, prefix: str, depth: int, level: int | None, show_all: bool, directories_only: bool
) -> tuple[list[str], int, int]:
    """Return the lines for one level of the tree and everything below it, with the counts

    Args:
        directory: The directory being listed
        prefix: The indentation inherited from the parent levels
        depth: How far below the starting point this directory sits
        level: The deepest level to display, or None for no limit
        show_all: Whether entries whose name starts with a dot are included
        directories_only: Whether files are dropped from the listing

    Returns:
        The lines, the number of directories and the number of files listed
    """
    if level is not None and depth >= level:
        return [], 0, 0
    try:
        entries = visible_children(directory, show_all, directories_only)
    except OSError:
        return [f"{prefix}{ERROR_OPENING_DIRECTORY}"], 0, 0
    lines: list[str] = []
    directory_count = 0
    file_count = 0
    for position, entry in enumerate(entries):
        last = position == len(entries) - 1
        lines.append(f"{prefix}{LAST_BRANCH if last else BRANCH}{entry.name}")
        if entry.is_dir() and not entry.is_symlink():
            directory_count += 1
            nested_lines, nested_directories, nested_files = render_directory(
                entry, prefix + (BLANK if last else VERTICAL), depth + 1, level, show_all, directories_only
            )
            lines.extend(nested_lines)
            directory_count += nested_directories
            file_count += nested_files
        else:
            file_count += 1
    return lines, directory_count, file_count


def summary_line(directory_count: int, file_count: int, directories_only: bool) -> str:
    """Return the closing count line

    Args:
        directory_count: How many directories were listed
        file_count: How many files were listed
        directories_only: Whether files were omitted, which drops them from the summary too

    Returns:
        The summary in GNU tree wording
    """
    directories = f"{directory_count} director{'y' if directory_count == 1 else 'ies'}"
    if directories_only:
        return directories
    return f"{directories}, {file_count} file{'' if file_count == 1 else 's'}"


class TreeCommand(Command):
    """List the contents of directories as a tree"""

    name = "tree"
    summary = "list contents of directories in a tree-like format"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print each directory as a tree followed by a summary count

        Args:
            invocation: The call to perform

        Returns:
            The trees and the summary
        """
        parser = CommandArgumentParser("tree", "List contents of directories in a tree-like format")
        parser.add_argument("-a", "--all", action="store_true", help="all files are listed")
        parser.add_argument("-d", "--directories", action="store_true", help="list directories only")
        parser.add_argument("-L", "--level", type=int, default=None, metavar="LEVEL", help="max display depth")
        parser.add_argument("paths", nargs="*", default=[DEFAULT_PATH], help="directories to list")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        if parsed.level is not None and parsed.level < MINIMUM_LEVEL:
            invocation.state.write_error("tree: Invalid level, must be greater than 0.\n")
            return CommandResult(stdout="", exit_code=EXIT_CODE_FAILURE)
        lines: list[str] = []
        total_directories = 0
        total_files = 0
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths:
            root = invocation.state.resolve_path(path_text)
            if not root.exists():
                lines.append(f"{path_text}  {ERROR_OPENING_DIRECTORY}")
                exit_code = EXIT_CODE_FAILURE
                continue
            lines.append(path_text)
            if root.is_dir():
                rendered, directory_count, file_count = render_directory(
                    root, "", 0, parsed.level, parsed.all, parsed.directories
                )
                lines.extend(rendered)
                total_directories += directory_count
                total_files += file_count
            else:
                total_files += 1
        lines.extend(["", summary_line(total_directories, total_files, parsed.directories)])
        return CommandResult(stdout="".join(f"{line}\n" for line in lines), exit_code=exit_code)
