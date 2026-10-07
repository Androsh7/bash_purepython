"""Implement the ls command"""

# Standard libraries
import math
import os
import stat
import time
from dataclasses import dataclass
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
CURRENT_DIRECTORY_NAME = "."
PARENT_DIRECTORY_NAME = ".."
HIDDEN_PREFIX = "."
STAT_BLOCK_SIZE_BYTES = 512
LISTING_BLOCK_SIZE_BYTES = 1024
RECENT_PERIOD_S = 182 * 24 * 60 * 60
RECENT_TIME_FORMAT = "%b %e %H:%M"
OLD_TIME_FORMAT = "%b %e  %Y"
DAY_OF_MONTH_DIRECTIVE = "%e"
USER_VARIABLE_NAME = "USER"
DEFAULT_OWNER = "user"
DIRECTORY_SUFFIX = "/"
SYMLINK_ARROW = " -> "


@dataclass(frozen=True)
class ListedEntry:
    """Hold one line of a listing: the name shown, the path behind it, and its status"""

    name: str
    path: Path
    status: os.stat_result


@dataclass(frozen=True)
class ListingOptions:
    """Hold the options that shape a listing"""

    long_listing: bool
    human_readable: bool
    show_all: bool
    show_almost_all: bool
    recursive: bool
    reverse: bool
    sort_by_time: bool
    sort_by_size: bool
    one_per_line: bool
    directory_itself: bool
    show_blocks: bool
    classify: bool
    owner: str


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


def allocated_blocks(status: os.stat_result) -> int:
    """Return the space an entry takes in the one-kilobyte blocks ls counts in

    Args:
        status: The entry's status

    Returns:
        The allocated blocks, estimated from the size where the platform does not report them
    """
    stat_blocks = getattr(status, "st_blocks", None)
    if stat_blocks is None:
        return math.ceil(status.st_size / LISTING_BLOCK_SIZE_BYTES)
    return math.ceil(stat_blocks * STAT_BLOCK_SIZE_BYTES / LISTING_BLOCK_SIZE_BYTES)


def format_blocks(blocks: int, human_readable: bool) -> str:
    """Return a block count as ls prints it

    Args:
        blocks: The count of one-kilobyte blocks
        human_readable: Whether to use K, M and G

    Returns:
        The count, or the size it stands for in short form
    """
    return format_size(blocks * LISTING_BLOCK_SIZE_BYTES) if human_readable else str(blocks)


def format_modification_time(modified_s: float, now_s: float) -> str:
    """Return a modification time as ls -l prints it

    Args:
        modified_s: When the entry was modified, in seconds since the epoch
        now_s: The current time, in seconds since the epoch

    Returns:
        The month, day and time of day for a recent entry, otherwise the month, day and year
    """
    is_recent = now_s - RECENT_PERIOD_S < modified_s <= now_s
    moment = time.localtime(modified_s)
    pattern = RECENT_TIME_FORMAT if is_recent else OLD_TIME_FORMAT
    return time.strftime(pattern.replace(DAY_OF_MONTH_DIRECTIVE, f"{moment.tm_mday:2d}"), moment)


def read_entry(name: str, path: Path) -> ListedEntry:
    """Return an entry with its own status, not that of a link's target

    Args:
        name: The name to show
        path: The path to look at

    Returns:
        The entry
    """
    return ListedEntry(name=name, path=path, status=path.lstat())


def directory_entries(directory: Path, options: ListingOptions) -> list[ListedEntry]:
    """Return the entries a directory lists, before sorting

    Args:
        directory: The directory
        options: Which hidden entries are included and whether descendants are

    Returns:
        The directory's children, with ``.`` and ``..`` first under -a
    """
    children = list(directory.rglob("*")) if options.recursive else list(directory.iterdir())
    entries = [read_entry(child.relative_to(directory).as_posix(), child) for child in children]
    if not (options.show_all or options.show_almost_all):
        entries = [entry for entry in entries if not entry.path.name.startswith(HIDDEN_PREFIX)]
    if options.show_all:
        entries.append(read_entry(CURRENT_DIRECTORY_NAME, directory))
        entries.append(read_entry(PARENT_DIRECTORY_NAME, directory.parent))
    return entries


def sort_entries(entries: list[ListedEntry], options: ListingOptions) -> list[ListedEntry]:
    """Return entries in the order the options ask for

    Args:
        entries: The entries to order
        options: Whether to sort by time or size instead of name, and whether to reverse

    Returns:
        The entries by name, or newest or largest first, reversed under -r
    """
    ordered = sorted(entries, key=lambda entry: entry.name)
    if options.sort_by_size:
        ordered = sorted(ordered, key=lambda entry: entry.status.st_size, reverse=True)
    elif options.sort_by_time:
        ordered = sorted(ordered, key=lambda entry: entry.status.st_mtime, reverse=True)
    return ordered[::-1] if options.reverse else ordered


def shown_name(entry: ListedEntry, options: ListingOptions) -> str:
    """Return an entry's name with the decorations the options add

    Args:
        entry: The entry
        options: Whether to mark directories and whether a link's target is shown

    Returns:
        The name, with a slash after a directory under -F and the target after a link under -l
    """
    name = entry.name
    if options.classify and stat.S_ISDIR(entry.status.st_mode):
        name += DIRECTORY_SUFFIX
    if options.long_listing and stat.S_ISLNK(entry.status.st_mode):
        name += SYMLINK_ARROW + str(entry.path.readlink())
    return name


def format_long_lines(entries: list[ListedEntry], options: ListingOptions, now_s: float) -> list[str]:
    """Return one line per entry with its mode, links, owner, group, size, time and name

    Args:
        entries: The entries in the order to print
        options: The listing options
        now_s: The current time, which decides whether a year or a time of day is shown

    Returns:
        The lines, with the link count and size columns right-aligned to their widest value
    """
    link_counts = [str(entry.status.st_nlink) for entry in entries]
    sizes = [
        format_size(entry.status.st_size) if options.human_readable else str(entry.status.st_size) for entry in entries
    ]
    blocks = [format_blocks(allocated_blocks(entry.status), options.human_readable) for entry in entries]
    link_width = max((len(count) for count in link_counts), default=0)
    size_width = max((len(size) for size in sizes), default=0)
    block_width = max((len(block) for block in blocks), default=0)
    lines: list[str] = []
    for entry, link_count, size, block in zip(entries, link_counts, sizes, blocks, strict=True):
        fields = [
            stat.filemode(entry.status.st_mode),
            link_count.rjust(link_width),
            options.owner,
            options.owner,
            size.rjust(size_width),
            format_modification_time(entry.status.st_mtime, now_s),
            shown_name(entry, options),
        ]
        prefix = f"{block.rjust(block_width)} " if options.show_blocks else ""
        lines.append(prefix + " ".join(fields))
    return lines


def format_listing(entries: list[ListedEntry], options: ListingOptions, with_total: bool) -> str:
    """Return the text listing one group of entries

    Args:
        entries: The entries in the order to print
        options: The listing options
        with_total: Whether the group is a directory's content, which -l and -s head with a total line

    Returns:
        The listing, empty when there is nothing to print
    """
    lines: list[str] = []
    if with_total and (options.long_listing or options.show_blocks):
        total = sum(allocated_blocks(entry.status) for entry in entries)
        lines.append(f"total {format_blocks(total, options.human_readable)}")
    if options.long_listing:
        lines.extend(format_long_lines(entries, options, time.time()))
        return "".join(f"{line}\n" for line in lines)
    names = [shown_name(entry, options) for entry in entries]
    if options.show_blocks:
        blocks = [format_blocks(allocated_blocks(entry.status), options.human_readable) for entry in entries]
        names = [f"{block} {name}" for block, name in zip(blocks, names, strict=True)]
    if options.one_per_line or options.show_blocks:
        lines.extend(names)
        return "".join(f"{line}\n" for line in lines)
    heading = "".join(f"{line}\n" for line in lines)
    return heading + (COLUMN_SEPARATOR.join(names) + "\n" if names else "")


class LsCommand(Command):
    """List files and directories"""

    name = "ls"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """List the named files, then each named directory under a header when several paths are given

        Args:
            invocation: The call to perform

        Returns:
            The listing and exit code one if any path was missing
        """
        parser = CommandArgumentParser("ls", "List files in the given directories")
        parser.add_argument("-l", "--long", action="store_true", help="long listing: mode, links, owner, size, time")
        parser.add_argument("-h", "--human-readable", action="store_true", help="with -l or -s, sizes like 1.5K")
        parser.add_argument("-a", "--all", action="store_true", help="include hidden entries, . and ..")
        parser.add_argument("-A", "--almost-all", action="store_true", help="include hidden entries but not . and ..")
        parser.add_argument("-R", "--recursive", action="store_true", help="list every descendant")
        parser.add_argument("-r", "--reverse", action="store_true", help="reverse the order")
        parser.add_argument("-t", dest="sort_by_time", action="store_true", help="sort by time, newest first")
        parser.add_argument("-S", dest="sort_by_size", action="store_true", help="sort by size, largest first")
        parser.add_argument("-1", dest="one_per_line", action="store_true", help="one entry per line")
        parser.add_argument("-d", "--directory", action="store_true", help="list directories themselves")
        parser.add_argument("-s", "--size", action="store_true", help="print the allocated blocks of each entry")
        parser.add_argument("-F", "--classify", action="store_true", help="append / to directories")
        parser.add_argument("paths", nargs="*", default=[DEFAULT_PATH], help="files or directories to list")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        state = invocation.state
        options = ListingOptions(
            long_listing=parsed.long,
            human_readable=parsed.human_readable,
            show_all=parsed.all,
            show_almost_all=parsed.almost_all,
            recursive=parsed.recursive,
            reverse=parsed.reverse,
            sort_by_time=parsed.sort_by_time,
            sort_by_size=parsed.sort_by_size,
            one_per_line=parsed.one_per_line or not invocation.attached_to_terminal,
            directory_itself=parsed.directory,
            show_blocks=parsed.size,
            classify=parsed.classify,
            owner=state.variables.get(USER_VARIABLE_NAME) or DEFAULT_OWNER,
        )
        exit_code = EXIT_CODE_SUCCESS
        files: list[ListedEntry] = []
        directories: list[tuple[str, Path]] = []
        for path_text in parsed.paths:
            path = state.resolve_path(path_text)
            if not path.exists() and not path.is_symlink():
                state.write_error(f"ls: cannot access '{path_text}': No such file or directory\n")
                exit_code = EXIT_CODE_FAILURE
            elif path.is_dir() and not options.directory_itself:
                directories.append((path_text, path))
            else:
                files.append(read_entry(path_text, path))
        pieces: list[str] = []
        if files:
            pieces.append(format_listing(sort_entries(files, options), options, with_total=False))
        show_headers = len(parsed.paths) > 1
        for path_text, directory in directories:
            listing = self.list_directory(path_text, directory, options, state)
            if listing is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            header = f"{path_text}:\n" if show_headers else ""
            separator = "\n" if pieces and show_headers else ""
            pieces.append(separator + header + listing)
        return CommandResult(stdout="".join(pieces), exit_code=exit_code)

    def list_directory(self, path_text: str, directory: Path, options: ListingOptions, state: ShellState) -> str | None:
        """Return the listing of one directory, or None after reporting that it cannot be read

        Args:
            path_text: The directory as written
            directory: The resolved directory
            options: The listing options
            state: The shell state errors are written through

        Returns:
            The listing text, or None
        """
        try:
            entries = directory_entries(directory, options)
        except OSError as error:
            state.write_error(f"ls: cannot open directory '{path_text}': {error.strerror}\n")
            return None
        return format_listing(sort_entries(entries, options), options, with_total=True)
