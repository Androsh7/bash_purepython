"""Implement the diff command"""

# Standard libraries
from dataclasses import dataclass
from difflib import SequenceMatcher

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import stdin_lines
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, EXIT_CODE_USAGE_ERROR
from bash_purepython.streams import TEXT_ENCODING, close_iterator

STDIN_PATH = "-"
STDIN_LABEL = "-"
EXIT_CODE_SAME = EXIT_CODE_SUCCESS
EXIT_CODE_DIFFERENT = EXIT_CODE_FAILURE
EXIT_CODE_TROUBLE = EXIT_CODE_USAGE_ERROR
DEFAULT_CONTEXT_LINES = 3
NO_NEWLINE_MARKER = "\\ No newline at end of file\n"
MISSING_NEWLINE_KEY_SUFFIX = "\0"
OLD_PREFIX = "< "
NEW_PREFIX = "> "
CHANGE_SEPARATOR = "---\n"


@dataclass(frozen=True)
class DiffSide:
    """Hold one input of a comparison: its label, its lines and whether it ended without a newline"""

    label: str
    lines: list[str]
    missing_final_newline: bool


def line_range(start: int, end: int) -> str:
    """Return a half-open zero-based range in diff's one-based normal notation

    Args:
        start: The first index
        end: The index after the last

    Returns:
        ``N`` for one line, ``N,M`` for several, and the preceding line number for none
    """
    if end <= start:
        return str(start)
    if end - start == 1:
        return str(start + 1)
    return f"{start + 1},{end}"


def unified_range(start: int, end: int) -> str:
    """Return a half-open zero-based range in unified hunk notation

    Args:
        start: The first index
        end: The index after the last

    Returns:
        ``N`` for one line, ``N,LEN`` otherwise
    """
    length = end - start
    beginning = start + 1 if length else start
    return str(beginning) if length == 1 else f"{beginning},{length}"


def comparison_key(line: str, ignore_case: bool, ignore_all_space: bool) -> str:
    """Return the form of a line that is compared

    Args:
        line: The line without its newline
        ignore_case: Whether letter case is disregarded
        ignore_all_space: Whether every blank is disregarded

    Returns:
        The key
    """
    key = line.lower() if ignore_case else line
    return "".join(key.split()) if ignore_all_space else key


def comparison_keys(side: DiffSide, ignore_case: bool, ignore_all_space: bool) -> list[str]:
    """Return the keys every line of one side is compared by, marking a last line that lacks its newline

    Args:
        side: The input
        ignore_case: Whether letter case is disregarded
        ignore_all_space: Whether every blank is disregarded

    Returns:
        One key per line
    """
    keys = [comparison_key(line, ignore_case, ignore_all_space) for line in side.lines]
    if side.missing_final_newline:
        keys[-1] += MISSING_NEWLINE_KEY_SUFFIX
    return keys


def side_lines(side: DiffSide, start: int, end: int, prefix: str) -> list[str]:
    """Return the lines of one side with a prefix, marking a missing final newline after the last line

    Args:
        side: The input
        start: The first index
        end: The index after the last
        prefix: What to put before every line

    Returns:
        The output lines with newlines
    """
    output: list[str] = []
    for index in range(start, end):
        output.append(f"{prefix}{side.lines[index]}\n")
        if index == len(side.lines) - 1 and side.missing_final_newline:
            output.append(NO_NEWLINE_MARKER)
    return output


def format_normal(old: DiffSide, new: DiffSide, matcher: SequenceMatcher) -> str:
    """Return the differences in diff's normal format

    Args:
        old: The first input
        new: The second input
        matcher: The matcher over the two inputs' comparison keys

    Returns:
        The hunks, empty when the inputs compare equal
    """
    output: list[str] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            output.append(f"{line_range(old_start, old_end)}c{line_range(new_start, new_end)}\n")
            output.extend(side_lines(old, old_start, old_end, OLD_PREFIX))
            output.append(CHANGE_SEPARATOR)
            output.extend(side_lines(new, new_start, new_end, NEW_PREFIX))
        elif tag == "delete":
            output.append(f"{line_range(old_start, old_end)}d{new_start}\n")
            output.extend(side_lines(old, old_start, old_end, OLD_PREFIX))
        elif tag == "insert":
            output.append(f"{old_start}a{line_range(new_start, new_end)}\n")
            output.extend(side_lines(new, new_start, new_end, NEW_PREFIX))
    return "".join(output)


def format_unified(old: DiffSide, new: DiffSide, matcher: SequenceMatcher, context_lines: int) -> str:
    """Return the differences in unified format with GNU's date-free headers

    Args:
        old: The first input
        new: The second input
        matcher: The matcher over the two inputs' comparison keys
        context_lines: How many unchanged lines surround each hunk

    Returns:
        The headers and hunks, empty when the inputs compare equal
    """
    groups = list(matcher.get_grouped_opcodes(context_lines))
    if not groups:
        return ""
    output = [f"--- {old.label}\n", f"+++ {new.label}\n"]
    for group in groups:
        old_start, old_end = group[0][1], group[-1][2]
        new_start, new_end = group[0][3], group[-1][4]
        output.append(f"@@ -{unified_range(old_start, old_end)} +{unified_range(new_start, new_end)} @@\n")
        for tag, group_old_start, group_old_end, group_new_start, group_new_end in group:
            if tag == "equal":
                output.extend(side_lines(old, group_old_start, group_old_end, " "))
                continue
            if tag in ("replace", "delete"):
                output.extend(side_lines(old, group_old_start, group_old_end, "-"))
            if tag in ("replace", "insert"):
                output.extend(side_lines(new, group_new_start, group_new_end, "+"))
    return "".join(output)


async def read_side(path_text: str, invocation: CommandInvocation) -> DiffSide | None:
    """Return one input of the comparison, or None after reporting why it cannot be read

    Args:
        path_text: A file path, or ``-`` for standard input
        invocation: The call, providing standard input and the shell state

    Returns:
        The side, or None
    """
    if path_text == STDIN_PATH:
        if invocation.stdin_kind == InputKind.ARGUMENTS:
            return DiffSide(label=STDIN_LABEL, lines=[], missing_final_newline=False)
        source = stdin_lines(invocation.stdin, invocation.stdin_kind)
        try:
            raw_lines = [line async for line in source]
        finally:
            await close_iterator(source)
    else:
        path = invocation.state.resolve_path(path_text)
        if path.is_dir():
            invocation.state.write_error(f"diff: {path_text}: Is a directory\n")
            return None
        if not path.exists():
            invocation.state.write_error(f"diff: {path_text}: No such file or directory\n")
            return None
        raw_lines = path.read_text(encoding=TEXT_ENCODING, errors="replace").splitlines(keepends=True)
    missing_final_newline = bool(raw_lines) and not raw_lines[-1].endswith("\n")
    return DiffSide(
        label=path_text, lines=[line.rstrip("\n") for line in raw_lines], missing_final_newline=missing_final_newline
    )


class DiffCommand(Command):
    """Compare two files line by line"""

    name = "diff"
    summary = "compare files line by line"
    input_kinds = frozenset({InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Print the differences, exiting zero when the files are the same, one when they differ and two on trouble

        Args:
            invocation: The call to perform

        Returns:
            The differences in the requested format and the exit code
        """
        parser = CommandArgumentParser("diff", "Compare files line by line")
        parser.add_argument("-u", "--unified", action="store_true", help="output three lines of unified context")
        parser.add_argument("-q", "--brief", action="store_true", help="report only when files differ")
        parser.add_argument(
            "-s", "--report-identical-files", action="store_true", help="report when files are the same"
        )
        parser.add_argument("-i", "--ignore-case", action="store_true", help="ignore case differences")
        parser.add_argument("-w", "--ignore-all-space", action="store_true", help="ignore all white space")
        parser.add_argument("paths", nargs=2, metavar="FILE", help="the two files to compare, - for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        old = await read_side(parsed.paths[0], invocation)
        new = await read_side(parsed.paths[1], invocation)
        if old is None or new is None:
            return CommandResult(stdout="", exit_code=EXIT_CODE_TROUBLE)
        old_keys = comparison_keys(old, parsed.ignore_case, parsed.ignore_all_space)
        new_keys = comparison_keys(new, parsed.ignore_case, parsed.ignore_all_space)
        matcher = SequenceMatcher(None, old_keys, new_keys, autojunk=False)
        if old_keys == new_keys:
            report = f"Files {old.label} and {new.label} are identical\n" if parsed.report_identical_files else ""
            return CommandResult(stdout=report, exit_code=EXIT_CODE_SAME)
        if parsed.brief:
            return CommandResult(stdout=f"Files {old.label} and {new.label} differ\n", exit_code=EXIT_CODE_DIFFERENT)
        if parsed.unified:
            output = format_unified(old, new, matcher, DEFAULT_CONTEXT_LINES)
        else:
            output = format_normal(old, new, matcher)
        return CommandResult(stdout=output, exit_code=EXIT_CODE_DIFFERENT)
