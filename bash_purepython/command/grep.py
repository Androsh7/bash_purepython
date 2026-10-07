"""Implement the grep command"""

# Standard libraries
import re
from collections.abc import AsyncIterator

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import file_lines
from bash_purepython.command.sources import STDIN_LABEL, STDIN_PATH, open_source, source_paths
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import as_async_iterator

NO_MATCH_EXIT_CODE = 1
LABEL_SEPARATOR = ":"


def search_targets(invocation: CommandInvocation, paths: list[str], recursive: bool) -> list[tuple[str, str]]:
    """Return the label and path text of every source grep should read

    Args:
        invocation: The call, whose state resolves paths and reports errors
        paths: The paths named on the command line, or none for standard input
        recursive: Whether directories are walked instead of refused

    Returns:
        Pairs of the label to print and the path text to open
    """
    targets: list[tuple[str, str]] = []
    for path_text in source_paths(invocation, paths):
        if path_text == STDIN_PATH:
            targets.append((STDIN_LABEL, STDIN_PATH))
            continue
        path = invocation.state.resolve_path(path_text)
        if path.is_dir() and recursive:
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    relative = child.relative_to(path).as_posix()
                    targets.append((f"{path_text.rstrip('/')}/{relative}", str(child)))
        else:
            targets.append((path_text, path_text))
    return targets


def match_lines(invocation: CommandInvocation, label: str, path_text: str) -> AsyncIterator[str] | None:
    """Return the lines of one target, or None after reporting why it cannot be read

    Args:
        invocation: The call, providing standard input and the shell state
        label: The label the target is printed under
        path_text: The path to open, or ``-`` for standard input

    Returns:
        An async iterator over the lines, or None
    """
    if path_text == STDIN_PATH:
        return open_source("grep", STDIN_PATH, invocation)
    path = invocation.state.resolve_path(path_text)
    if path.is_dir():
        invocation.state.write_error(f"grep: {label}: Is a directory\n")
        invocation.exit_status.code = EXIT_CODE_USAGE_ERROR
        return None
    if not path.exists():
        invocation.state.write_error(f"grep: {label}: No such file or directory\n")
        invocation.exit_status.code = EXIT_CODE_USAGE_ERROR
        return None
    return file_lines(path)


async def grep_targets(
    invocation: CommandInvocation,
    targets: list[tuple[str, str]],
    regex: re.Pattern[str],
    invert: bool,
    show_filename: bool,
    line_numbers: bool,
    count_only: bool,
    files_only: bool,
) -> AsyncIterator[str]:
    """Yield the matching lines, counts or file names, and set the exit status to one when nothing matched

    Args:
        invocation: The call, providing standard input and the shell state
        targets: The labels and paths to search
        regex: The compiled pattern
        invert: Whether non-matching lines are selected
        show_filename: Whether each line is prefixed with its label
        line_numbers: Whether each line is prefixed with its number
        count_only: Whether only the count per target is printed
        files_only: Whether only the names of matching targets are printed

    Yields:
        Output lines with newlines
    """
    any_match = False
    for label, path_text in targets:
        lines = match_lines(invocation, label, path_text)
        if lines is None:
            continue
        matches = 0
        try:
            line_number = 0
            async for raw_line in lines:
                line_number += 1
                line = raw_line.rstrip("\n")
                if bool(regex.search(line)) == invert:
                    continue
                matches += 1
                any_match = True
                if count_only or files_only:
                    continue
                prefix = ([label] if show_filename else []) + ([str(line_number)] if line_numbers else [])
                yield LABEL_SEPARATOR.join([*prefix, line]) + "\n"
        finally:
            aclose = getattr(lines, "aclose", None)
            if aclose is not None:
                await aclose()
        if files_only and matches:
            yield label + "\n"
        elif count_only:
            yield (f"{label}{LABEL_SEPARATOR}{matches}" if show_filename else str(matches)) + "\n"
    if not any_match and invocation.exit_status.code == EXIT_CODE_SUCCESS:
        invocation.exit_status.code = NO_MATCH_EXIT_CODE


class GrepCommand(Command):
    """Print lines matching a pattern"""

    name = "grep"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of matches, exiting one when there were none and two on a bad pattern or file

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream
        """
        parser = CommandArgumentParser("grep", "Search lines matching a pattern")
        parser.add_argument("-i", "--ignore-case", action="store_true", help="case insensitive match")
        parser.add_argument("-v", "--invert-match", action="store_true", help="select non-matching lines")
        parser.add_argument("-n", "--line-number", action="store_true", help="prefix lines with their number")
        parser.add_argument("-c", "--count", action="store_true", help="print only a count per file")
        parser.add_argument("-r", "-R", "--recursive", action="store_true", help="recurse into directories")
        parser.add_argument("-F", "--fixed-strings", action="store_true", help="treat the pattern as plain text")
        parser.add_argument(
            "-E",
            "--extended-regexp",
            action="store_true",
            help="accepted, patterns are always Python regular expressions",
        )
        parser.add_argument("-l", "--files-with-matches", action="store_true", help="print only matching file names")
        parser.add_argument("-H", "--with-filename", action="store_true", help="always print the file name")
        parser.add_argument("-h", "--no-filename", action="store_true", help="never print the file name")
        parser.add_argument("-e", "--regexp", dest="patterns", action="append", default=[], help="a pattern")
        parser.add_argument("pattern_and_paths", nargs="*", help="the pattern, then files to search")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        patterns = list(parsed.patterns)
        remaining = list(parsed.pattern_and_paths)
        if not patterns:
            if not remaining:
                invocation.state.write_error("grep: no pattern given\n")
                return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
            patterns.append(remaining.pop(0))
        alternatives = [re.escape(pattern) if parsed.fixed_strings else pattern for pattern in patterns]
        try:
            regex = re.compile(
                "|".join(f"(?:{alternative})" for alternative in alternatives),
                re.IGNORECASE if parsed.ignore_case else 0,
            )
        except re.error as error:
            invocation.state.write_error(f"grep: invalid pattern: {error}\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        targets = search_targets(invocation, remaining, parsed.recursive)
        show_filename = (parsed.with_filename or len(targets) > 1 or parsed.recursive) and not parsed.no_filename
        stream = grep_targets(
            invocation,
            targets,
            regex,
            parsed.invert_match,
            show_filename,
            parsed.line_number,
            parsed.count,
            parsed.files_with_matches,
        )
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
