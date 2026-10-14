"""Implement the grep command"""

# Standard libraries
import re
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import file_lines
from bash_purepython.command.sed import translate_regex
from bash_purepython.command.sources import STDIN_LABEL, STDIN_PATH, open_source, source_paths
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import as_async_iterator

NO_MATCH_EXIT_CODE = 1
LABEL_SEPARATOR = ":"
CONTEXT_SEPARATOR = "-"
GROUP_SEPARATOR = "--"
NO_CONTEXT = 0
CURRENT_DIRECTORY = "."
OPTIONS_END = "--"
NUMERIC_SHORTHAND_PATTERN = re.compile(r"^-([0-9]+)$")
VALUE_OPTION_LONG_NAMES = {
    "-e": "--regexp",
    "--regexp": "--regexp",
    "-A": "--after-context",
    "--after-context": "--after-context",
    "-B": "--before-context",
    "--before-context": "--before-context",
    "-C": "--context",
    "--context": "--context",
}


@dataclass(frozen=True)
class MatchOptions:
    """Hold the options that shape what grep prints for each target"""

    invert: bool
    show_filename: bool
    line_numbers: bool
    count_only: bool
    files_only: bool
    quiet: bool
    only_matching: bool
    before_context: int
    after_context: int
    separate_groups: bool


def expand_numeric_shorthand(arguments: list[str]) -> list[str]:
    """Return the arguments with the ``-<count>`` form rewritten as ``-C <count>``

    An option that takes a value is joined to it as ``--long=value``, so a value starting with a dash, as in
    ``-e -1``, is kept as the value rather than read as an option or as the shorthand

    Args:
        arguments: The arguments after the command name

    Returns:
        The rewritten arguments
    """
    expanded: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == OPTIONS_END:
            expanded.extend(arguments[index:])
            break
        long_name = VALUE_OPTION_LONG_NAMES.get(argument)
        match = NUMERIC_SHORTHAND_PATTERN.match(argument)
        if long_name is not None and index + 1 < len(arguments):
            expanded.append(f"{long_name}={arguments[index + 1]}")
            index += 1
        elif match:
            expanded.extend(["-C", match.group(1)])
        else:
            expanded.append(argument)
        index += 1
    return expanded


def search_targets(invocation: CommandInvocation, paths: list[str], recursive: bool) -> list[tuple[str, str]]:
    """Return the label and path text of every source grep should read

    Args:
        invocation: The call, whose state resolves paths and reports errors
        paths: The paths named on the command line, or none for standard input
        recursive: Whether directories are walked instead of refused, the current one when none is named

    Returns:
        Pairs of the label to print and the path text to open
    """
    targets: list[tuple[str, str]] = []
    if recursive and not paths:
        return [(label, path_text) for label, path_text in walk_directory(invocation, CURRENT_DIRECTORY, prefix="")]
    for path_text in source_paths(invocation, paths):
        if path_text == STDIN_PATH:
            targets.append((STDIN_LABEL, STDIN_PATH))
            continue
        path = invocation.state.resolve_path(path_text)
        if path.is_dir() and recursive:
            targets.extend(walk_directory(invocation, path_text, prefix=f"{path_text.rstrip('/')}/"))
        else:
            targets.append((path_text, path_text))
    return targets


def walk_directory(invocation: CommandInvocation, path_text: str, prefix: str) -> list[tuple[str, str]]:
    """Return every file under a directory, labelled relative to it with the prefix

    Args:
        invocation: The call, whose state resolves paths
        path_text: The directory as written
        prefix: What to put before each relative path in its label

    Returns:
        Pairs of the label to print and the path text to open, in sorted order
    """
    directory = invocation.state.resolve_path(path_text)
    targets: list[tuple[str, str]] = []
    for child in sorted(directory.rglob("*")):
        if child.is_file():
            targets.append((prefix + child.relative_to(directory).as_posix(), str(child)))
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


def format_line(label: str, line_number: int, text: str, separator: str, options: MatchOptions) -> str:
    """Return one output line with the file and line number prefixes the options ask for

    Args:
        label: The target's label
        line_number: The line's number
        text: The line or matched part
        separator: ``:`` for a selected line, ``-`` for a context line
        options: Whether the label and number are shown

    Returns:
        The line with a newline
    """
    prefix = ([label] if options.show_filename else []) + ([str(line_number)] if options.line_numbers else [])
    return separator.join([*prefix, text]) + "\n"


class ContextPrinter:
    """Print selected lines with their surrounding context and the separator between distant groups"""

    def __init__(self, label: str, options: MatchOptions, printed_any_group: bool):
        """Start a target

        Args:
            label: The target's label
            options: How lines are prefixed and how much context surrounds them
            printed_any_group: Whether an earlier target already printed a group
        """
        self.label = label
        self.options = options
        self.printed_any_group = printed_any_group
        self.before: deque[tuple[int, str]] = deque(maxlen=options.before_context or None)
        self.after_remaining = 0
        self.last_printed_line_number = 0

    def selected(self, line_number: int, text: str, matches: list[str]) -> list[str]:
        """Return the output for a selected line: a separator if needed, its leading context, then the line

        Args:
            line_number: The line's number
            text: The line
            matches: The matched parts, printed one per line under -o

        Returns:
            The output lines
        """
        output: list[str] = []
        first_context_number = self.before[0][0] if self.before else line_number
        starts_new_group = (
            self.last_printed_line_number == 0 or first_context_number > self.last_printed_line_number + 1
        )
        if self.options.separate_groups and starts_new_group and self.printed_any_group:
            output.append(GROUP_SEPARATOR + "\n")
        for context_number, context_text in self.before:
            output.append(format_line(self.label, context_number, context_text, CONTEXT_SEPARATOR, self.options))
        self.before.clear()
        if self.options.only_matching:
            for matched in matches:
                output.append(format_line(self.label, line_number, matched, LABEL_SEPARATOR, self.options))
        else:
            output.append(format_line(self.label, line_number, text, LABEL_SEPARATOR, self.options))
        self.last_printed_line_number = line_number
        self.after_remaining = self.options.after_context
        self.printed_any_group = True
        return output

    def unselected(self, line_number: int, text: str) -> list[str]:
        """Return the output for a line that was not selected: itself when trailing context is still owed

        Args:
            line_number: The line's number
            text: The line

        Returns:
            The output lines
        """
        if self.after_remaining > 0:
            self.after_remaining -= 1
            self.last_printed_line_number = line_number
            return [format_line(self.label, line_number, text, CONTEXT_SEPARATOR, self.options)]
        if self.options.before_context > NO_CONTEXT:
            self.before.append((line_number, text))
        return []


async def grep_targets(
    invocation: CommandInvocation, targets: list[tuple[str, str]], regex: re.Pattern[str], options: MatchOptions
) -> AsyncIterator[str]:
    """Yield the matching lines, counts or file names, and set the exit status to one when nothing matched

    Args:
        invocation: The call, providing standard input and the shell state
        targets: The labels and paths to search
        regex: The compiled pattern
        options: What is printed for each match

    Yields:
        Output lines with newlines
    """
    any_match = False
    printed_any_group = False
    for label, path_text in targets:
        lines = match_lines(invocation, label, path_text)
        if lines is None:
            continue
        matches = 0
        printer = ContextPrinter(label, options, printed_any_group)
        try:
            line_number = 0
            async for raw_line in lines:
                line_number += 1
                line = raw_line.rstrip("\n")
                found = [match.group(0) for match in regex.finditer(line) if match.group(0)]
                if bool(regex.search(line)) == options.invert:
                    if not options.count_only and not options.files_only and not options.quiet:
                        for piece in printer.unselected(line_number, line):
                            yield piece
                    continue
                matches += 1
                any_match = True
                if options.quiet:
                    return
                if options.count_only or options.files_only:
                    continue
                for piece in printer.selected(line_number, line, found):
                    yield piece
        finally:
            aclose = getattr(lines, "aclose", None)
            if aclose is not None:
                await aclose()
        printed_any_group = printer.printed_any_group
        if options.files_only and matches:
            yield label + "\n"
        elif options.count_only:
            yield (f"{label}{LABEL_SEPARATOR}{matches}" if options.show_filename else str(matches)) + "\n"
    if not any_match and invocation.exit_status.code == EXIT_CODE_SUCCESS:
        invocation.exit_status.code = NO_MATCH_EXIT_CODE


class GrepCommand(Command):
    """Print lines matching a pattern"""

    name = "grep"
    summary = "print lines that match patterns"
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
            help="patterns are extended regular expressions",
        )
        parser.add_argument("-l", "--files-with-matches", action="store_true", help="print only matching file names")
        parser.add_argument("-H", "--with-filename", action="store_true", help="always print the file name")
        parser.add_argument("-h", "--no-filename", action="store_true", help="never print the file name")
        parser.add_argument(
            "-q", "--quiet", "--silent", action="store_true", help="print nothing, exit zero on a match"
        )
        parser.add_argument("-o", "--only-matching", action="store_true", help="print only the matched parts")
        parser.add_argument("-w", "--word-regexp", action="store_true", help="match only whole words")
        parser.add_argument("-x", "--line-regexp", action="store_true", help="match only whole lines")
        parser.add_argument("-A", "--after-context", type=int, default=None, help="print NUM lines after")
        parser.add_argument("-B", "--before-context", type=int, default=None, help="print NUM lines before")
        parser.add_argument("-C", "--context", type=int, default=None, help="print NUM lines of context")
        parser.add_argument("-e", "--regexp", dest="patterns", action="append", default=[], help="a pattern")
        parser.add_argument("pattern_and_paths", nargs="*", help="the pattern, then files to search")
        parsed = parse_command_arguments(parser, expand_numeric_shorthand(invocation.arguments), invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        patterns = list(parsed.patterns)
        remaining = list(parsed.pattern_and_paths)
        if not patterns:
            if not remaining:
                invocation.state.write_error("grep: no pattern given\n")
                return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
            patterns.append(remaining.pop(0))
        try:
            alternatives = [
                re.escape(pattern) if parsed.fixed_strings else translate_regex(pattern, parsed.extended_regexp)
                for pattern in patterns
            ]
            combined = "|".join(f"(?:{alternative})" for alternative in alternatives)
            if parsed.line_regexp:
                combined = f"^(?:{combined})$"
            elif parsed.word_regexp:
                combined = rf"(?<!\w)(?:{combined})(?!\w)"
            regex = re.compile(combined, re.IGNORECASE if parsed.ignore_case else 0)
        except re.error as error:
            invocation.state.write_error(f"grep: invalid pattern: {error}\n")
            return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_USAGE_ERROR)
        targets = search_targets(invocation, remaining, parsed.recursive)
        show_filename = (parsed.with_filename or len(targets) > 1 or parsed.recursive) and not parsed.no_filename
        context_values = (parsed.after_context, parsed.before_context, parsed.context)
        context = parsed.context if parsed.context is not None else NO_CONTEXT
        after_context = parsed.after_context if parsed.after_context is not None else NO_CONTEXT
        before_context = parsed.before_context if parsed.before_context is not None else NO_CONTEXT
        options = MatchOptions(
            invert=parsed.invert_match,
            show_filename=show_filename,
            line_numbers=parsed.line_number,
            count_only=parsed.count,
            files_only=parsed.files_with_matches,
            quiet=parsed.quiet,
            only_matching=parsed.only_matching,
            before_context=before_context if parsed.before_context is not None else context,
            after_context=after_context if parsed.after_context is not None else context,
            separate_groups=any(value is not None for value in context_values),
        )
        stream = grep_targets(invocation, targets, regex, options)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)
