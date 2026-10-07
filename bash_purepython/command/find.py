"""Implement the find command"""

# Standard libraries
import fnmatch
from collections.abc import AsyncIterator, Iterator
from enum import StrEnum
from pathlib import Path

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import as_async_iterator

DEFAULT_ROOT = "."
TEST_OPTIONS = frozenset({"-name", "-iname", "-type", "-maxdepth", "-mindepth"})


class EntryType(StrEnum):
    """Name the kinds of entry find can select with -type"""

    FILE = "f"
    DIRECTORY = "d"
    SYMLINK = "l"


def walk(root: Path, max_depth: int | None) -> Iterator[tuple[Path, int]]:
    """Yield every path at or below root with its depth, parents before children

    Args:
        root: The file or directory to start from, at depth zero
        max_depth: The deepest level to descend to, or None to descend fully

    Yields:
        Pairs of path and depth
    """
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        path, depth = pending.pop()
        yield path, depth
        if max_depth is not None and depth >= max_depth:
            continue
        if path.is_symlink() or not path.is_dir():
            continue
        pending.extend((child, depth + 1) for child in sorted(path.iterdir(), reverse=True))


def type_matches(path: Path, wanted: EntryType | None) -> bool:
    """Return whether a path is of the requested type

    Args:
        path: The path to test
        wanted: The type, or None for any

    Returns:
        True when the path should be reported
    """
    if wanted is None:
        return True
    if wanted == EntryType.SYMLINK:
        return path.is_symlink()
    if wanted == EntryType.DIRECTORY:
        return path.is_dir()
    return path.is_file()


def name_matches(path: Path, pattern: str | None, ignore_case: bool) -> bool:
    """Return whether a path's own name matches a glob

    Args:
        path: The path whose name is tested
        pattern: The glob, or None for any
        ignore_case: Whether the comparison folds case

    Returns:
        True when the name matches or no pattern was given
    """
    if pattern is None:
        return True
    if ignore_case:
        return fnmatch.fnmatch(path.name.lower(), pattern.lower())
    return fnmatch.fnmatchcase(path.name, pattern)


def split_roots_and_tests(arguments: list[str]) -> tuple[list[str], list[str]]:
    """Return the root paths, which come first, and the test options that follow

    Args:
        arguments: The arguments after the command name

    Returns:
        The roots, defaulting to the current directory, and the remaining arguments
    """
    roots: list[str] = []
    index = 0
    while index < len(arguments) and arguments[index] not in TEST_OPTIONS and not arguments[index].startswith("-"):
        roots.append(arguments[index])
        index += 1
    return roots or [DEFAULT_ROOT], arguments[index:]


async def found_paths(
    invocation: CommandInvocation,
    roots: list[str],
    name: str | None,
    iname: str | None,
    entry_type: EntryType | None,
    max_depth: int | None,
    min_depth: int,
) -> AsyncIterator[str]:
    """Yield every matching path under each root, as written relative to how the root was given

    Args:
        invocation: The call, whose state resolves roots and reports errors
        roots: The roots as written
        name: A case-sensitive name glob, or None
        iname: A case-insensitive name glob, or None
        entry_type: The type to select, or None
        max_depth: The deepest level to descend to, or None
        min_depth: The shallowest level to report

    Yields:
        Each matching path with a newline
    """
    for root_text in roots:
        root = invocation.state.resolve_path(root_text)
        if not root.exists():
            invocation.state.write_error(f"find: '{root_text}': No such file or directory\n")
            invocation.exit_status.code = EXIT_CODE_FAILURE
            continue
        for path, depth in walk(root, max_depth):
            if depth < min_depth or not type_matches(path, entry_type):
                continue
            if not name_matches(path, name, ignore_case=False) or not name_matches(path, iname, ignore_case=True):
                continue
            relative = path.relative_to(root)
            shown = root_text if depth == 0 else f"{root_text.rstrip('/')}/{relative.as_posix()}"
            yield shown + "\n"


class FindCommand(Command):
    """Search for files in a directory hierarchy"""

    name = "find"
    input_kinds = frozenset({InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of the matching paths

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream, or a usage error
        """
        roots, test_arguments = split_roots_and_tests(invocation.arguments)
        parser = CommandArgumentParser("find", "Search for files in a directory hierarchy")
        parser.add_argument("-name", dest="name", help="match the entry name against a glob")
        parser.add_argument("-iname", dest="iname", help="match the entry name against a case-insensitive glob")
        parser.add_argument("-type", dest="entry_type", choices=[entry.value for entry in EntryType], help="f, d or l")
        parser.add_argument("-maxdepth", dest="max_depth", type=int, default=None, help="deepest level to descend to")
        parser.add_argument("-mindepth", dest="min_depth", type=int, default=0, help="shallowest level to report")
        parsed = parse_command_arguments(parser, test_arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        if (parsed.max_depth is not None and parsed.max_depth < 0) or parsed.min_depth < 0:
            invocation.state.write_error("find: depth must not be negative\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        entry_type = EntryType(parsed.entry_type) if parsed.entry_type else None
        stream = found_paths(
            invocation, roots, parsed.name, parsed.iname, entry_type, parsed.max_depth, parsed.min_depth
        )
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
