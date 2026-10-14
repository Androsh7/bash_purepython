"""Implement the paste command"""

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import STDIN_PATH, open_source, source_paths
from bash_purepython.streams import close_iterator

DEFAULT_DELIMITERS = "\t"
DELIMITER_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "0": ""}


def parse_delimiters(text: str) -> list[str]:
    """Return the delimiters named by ``-d``, resolving its backslash escapes

    Args:
        text: The list as written, where a backslash zero is an empty delimiter

    Returns:
        The delimiters, used in turn and cycled
    """
    delimiters: list[str] = []
    position = 0
    while position < len(text):
        character = text[position]
        position += 1
        if character == "\\" and position < len(text):
            escaped = text[position]
            position += 1
            delimiters.append(DELIMITER_ESCAPES.get(escaped, escaped))
        else:
            delimiters.append(character)
    return delimiters or [""]


def join_with_cycle(fields: list[str], delimiters: list[str]) -> str:
    """Return the fields joined by the delimiters taken in turn

    Args:
        fields: The pieces of one output line
        delimiters: The delimiters, restarting from the first when they run out

    Returns:
        The joined line without a newline
    """
    pieces: list[str] = []
    for index, field in enumerate(fields):
        if index:
            pieces.append(delimiters[(index - 1) % len(delimiters)])
        pieces.append(field)
    return "".join(pieces)


async def read_sources(invocation: CommandInvocation, paths: list[str]) -> list[list[str] | None]:
    """Return the lines of every source, sharing standard input between every ``-`` in turn

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The sources in order

    Returns:
        One list of lines without newlines per source, or None for a source that could not be read
    """
    sources: list[list[str] | None] = []
    stdin_positions = [index for index, path_text in enumerate(paths) if path_text == STDIN_PATH]
    for path_text in paths:
        if path_text == STDIN_PATH:
            sources.append([])
            continue
        lines = open_source("paste", path_text, invocation)
        if lines is None:
            sources.append(None)
            continue
        try:
            sources.append([line.rstrip("\n") async for line in lines])
        finally:
            await close_iterator(lines)
    if stdin_positions:
        stdin = open_source("paste", STDIN_PATH, invocation)
        if stdin is not None:
            try:
                line_number = 0
                async for line in stdin:
                    target = sources[stdin_positions[line_number % len(stdin_positions)]]
                    if target is not None:
                        target.append(line.rstrip("\n"))
                    line_number += 1
            finally:
                await close_iterator(stdin)
    return sources


def paste_parallel(sources: list[list[str]], delimiters: list[str]) -> str:
    """Return the sources merged line by line, each output line holding one line from every source

    Args:
        sources: The lines of every source
        delimiters: The delimiters placed between fields, in turn

    Returns:
        The output text
    """
    row_count = max((len(lines) for lines in sources), default=0)
    output: list[str] = []
    for row_number in range(row_count):
        fields = [lines[row_number] if row_number < len(lines) else "" for lines in sources]
        output.append(join_with_cycle(fields, delimiters) + "\n")
    return "".join(output)


def paste_serial(sources: list[list[str]], delimiters: list[str]) -> str:
    """Return every source on its own line with its lines joined by the delimiters

    Args:
        sources: The lines of every source
        delimiters: The delimiters placed between fields, in turn

    Returns:
        The output text
    """
    return "".join(join_with_cycle(lines, delimiters) + "\n" for lines in sources)


class PasteCommand(Command):
    """Merge lines of files side by side"""

    name = "paste"
    summary = "merge lines of files"
    input_kinds = frozenset({InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Merge the sources line by line, or one source per line under -s

        Args:
            invocation: The call to perform

        Returns:
            The merged text and exit code one if any source could not be read
        """
        parser = CommandArgumentParser("paste", "Write lines consisting of the corresponding lines of each file")
        parser.add_argument("-d", "--delimiters", default=DEFAULT_DELIMITERS, help="reuse characters from LIST")
        parser.add_argument("-s", "--serial", action="store_true", help="paste one file at a time")
        parser.add_argument("paths", nargs="*", help="files to read, - for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        delimiters = parse_delimiters(parsed.delimiters)
        sources = await read_sources(invocation, source_paths(invocation, parsed.paths))
        readable = [lines for lines in sources if lines is not None]
        output = paste_serial(readable, delimiters) if parsed.serial else paste_parallel(readable, delimiters)
        return CommandResult(stdout=output, exit_code=invocation.exit_status.code)
