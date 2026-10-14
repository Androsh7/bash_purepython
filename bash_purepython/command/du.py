"""Implement the du command"""

# Standard libraries
from dataclasses import dataclass
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.ls import allocated_blocks, format_size
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, ShellState

DEFAULT_PATH = "."
BLOCK_SIZE_BYTES = 1024
UNLIMITED_DEPTH = -1
TOP_LEVEL_DEPTH = 0
TOTAL_LABEL = "total"


@dataclass(frozen=True)
class UsageOptions:
    """Hold the options that shape a usage report"""

    summarize: bool
    human_readable: bool
    all_files: bool
    max_depth: int
    apparent_bytes: bool


def entry_size(path: Path, options: UsageOptions) -> int:
    """Return the space one entry takes on its own, in bytes under -b and 1K blocks otherwise

    Args:
        path: The entry
        options: Whether apparent bytes are wanted

    Returns:
        The size
    """
    status = path.lstat()
    return status.st_size if options.apparent_bytes else allocated_blocks(status)


def format_usage(size: int, options: UsageOptions) -> str:
    """Return a size as du prints it

    Args:
        size: The size in bytes under -b and 1K blocks otherwise
        options: Whether a short human-readable form is wanted

    Returns:
        The size text
    """
    if not options.human_readable:
        return str(size)
    return format_size(size if options.apparent_bytes else size * BLOCK_SIZE_BYTES)


def report_tree(path: Path, shown: str, depth: int, options: UsageOptions, lines: list[str]) -> int:
    """Append the lines for one entry and everything under it, deepest first, and return its total

    Args:
        path: The entry
        shown: The name to print for it
        depth: How many levels below the command-line argument it is
        options: The report options
        lines: Where the report lines go

    Returns:
        The entry's size including everything under it
    """
    total = entry_size(path, options)
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.iterdir()):
            total += report_tree(child, f"{shown}/{child.name}", depth + 1, options, lines)
    is_shown = path.is_dir() or options.all_files or depth == TOP_LEVEL_DEPTH
    within_depth = options.max_depth == UNLIMITED_DEPTH or depth <= options.max_depth
    if is_shown and within_depth:
        lines.append(f"{format_usage(total, options)}\t{shown}\n")
    return total


class DuCommand(Command):
    """Report the disk space files and directories take"""

    name = "du"
    summary = "report disk usage"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Report each path, directories after their contents

        Args:
            invocation: The call to perform

        Returns:
            One line per reported entry, and exit code one if any path was missing
        """
        parser = CommandArgumentParser(self.name, "Report disk usage")
        parser.add_argument("-s", "--summarize", action="store_true", help="one total per argument")
        parser.add_argument("-h", "--human-readable", action="store_true", help="sizes like 1.5K")
        parser.add_argument("-a", "--all", action="store_true", help="report files as well as directories")
        parser.add_argument("-d", "--max-depth", type=int, default=UNLIMITED_DEPTH, help="report this deep only")
        parser.add_argument("-b", "--bytes", action="store_true", help="apparent size in bytes")
        parser.add_argument("-c", "--total", action="store_true", help="add a grand total")
        parser.add_argument("paths", nargs="*", default=[DEFAULT_PATH], help="files or directories to report")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        options = UsageOptions(
            summarize=parsed.summarize,
            human_readable=parsed.human_readable,
            all_files=parsed.all,
            max_depth=TOP_LEVEL_DEPTH if parsed.summarize else parsed.max_depth,
            apparent_bytes=parsed.bytes,
        )
        lines: list[str] = []
        grand_total = 0
        exit_code = EXIT_CODE_SUCCESS
        for path_text in parsed.paths:
            total = self.report_path(path_text, options, lines, invocation.state)
            if total is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            grand_total += total
        if parsed.total:
            lines.append(f"{format_usage(grand_total, options)}\t{TOTAL_LABEL}\n")
        return CommandResult(stdout="".join(lines), exit_code=exit_code)

    def report_path(self, path_text: str, options: UsageOptions, lines: list[str], state: ShellState) -> int | None:
        """Report one command-line path, or None after reporting that it is missing

        Args:
            path_text: The path as written
            options: The report options
            lines: Where the report lines go
            state: The shell state for paths and errors

        Returns:
            The path's total size, or None
        """
        path = state.resolve_path(path_text)
        if not path.exists() and not path.is_symlink():
            state.write_error(f"du: cannot access '{path_text}': No such file or directory\n")
            return None
        return report_tree(path, path_text.rstrip("/") or path_text, TOP_LEVEL_DEPTH, options, lines)
