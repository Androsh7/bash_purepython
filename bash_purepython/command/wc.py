"""Implement the wc command"""

# Standard libraries
from dataclasses import dataclass

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.gzip import read_stdin_bytes
from bash_purepython.shell_state import EXIT_CODE_FAILURE, EXIT_CODE_SUCCESS, NULL_DEVICE_PATH, ShellState
from bash_purepython.streams import TEXT_ENCODING

STDIN_PATH = "-"
TOTAL_LABEL = "total"
MINIMUM_NUMBER_WIDTH = 1
PIPE_NUMBER_WIDTH = 7
COLUMN_SEPARATOR = " "


@dataclass(frozen=True)
class Counts:
    """Hold every count wc can print for one input"""

    lines: int
    words: int
    characters: int
    bytes: int
    longest_line: int

    @classmethod
    def of(cls, data: bytes):
        """Return the counts of one input

        Args:
            data: The raw bytes of the input
        """
        text = data.decode(TEXT_ENCODING, errors="replace")
        line_lengths = [len(line) for line in text.split("\n")]
        return cls(
            lines=data.count(b"\n"),
            words=len(text.split()),
            characters=len(text),
            bytes=len(data),
            longest_line=max(line_lengths, default=0),
        )

    def add(self, other: "Counts") -> "Counts":
        """Return the sum of two inputs' counts

        Args:
            other: The counts to add

        Returns:
            The combined counts, with the longer of the two longest lines
        """
        return Counts(
            lines=self.lines + other.lines,
            words=self.words + other.words,
            characters=self.characters + other.characters,
            bytes=self.bytes + other.bytes,
            longest_line=max(self.longest_line, other.longest_line),
        )


@dataclass(frozen=True)
class Columns:
    """Name which counts are printed, in output order"""

    lines: bool
    words: bool
    characters: bool
    bytes: bool
    longest_line: bool

    @classmethod
    def from_options(cls, lines: bool, words: bool, characters: bool, byte_count: bool, longest_line: bool):
        """Return the columns the options select, defaulting to lines, words and bytes

        Args:
            lines: Whether -l was given
            words: Whether -w was given
            characters: Whether -m was given
            byte_count: Whether -c was given
            longest_line: Whether -L was given
        """
        if not any((lines, words, characters, byte_count, longest_line)):
            return cls(lines=True, words=True, characters=False, bytes=True, longest_line=False)
        return cls(lines, words, characters, byte_count, longest_line)

    def count(self) -> int:
        """Return how many columns are printed"""
        return sum((self.lines, self.words, self.characters, self.bytes, self.longest_line))

    def values(self, counts: Counts) -> list[int]:
        """Return the selected counts in output order

        Args:
            counts: The counts of one input

        Returns:
            The numbers to print
        """
        selected = (
            (self.lines, counts.lines),
            (self.words, counts.words),
            (self.characters, counts.characters),
            (self.bytes, counts.bytes),
            (self.longest_line, counts.longest_line),
        )
        return [value for shown, value in selected if shown]


def format_row(values: list[int], label: str, width: int) -> str:
    """Return one output line

    Args:
        values: The numbers in order
        label: The file name, or empty for standard input
        width: The width every number is padded to

    Returns:
        The line with a newline
    """
    cells = [f"{value:>{width}}" for value in values]
    if label:
        cells.append(label)
    return COLUMN_SEPARATOR.join(cells) + "\n"


def read_file(path_text: str, state: ShellState) -> bytes | None:
    """Return the bytes of one file, or None after reporting why it cannot be read

    Args:
        path_text: The path as written on the command line
        state: The shell state for resolving the path and reporting errors

    Returns:
        The bytes, or None
    """
    if path_text == NULL_DEVICE_PATH:
        return b""
    path = state.resolve_path(path_text)
    if path.is_dir():
        state.write_error(f"wc: {path_text}: Is a directory\n")
        return None
    if not path.exists():
        state.write_error(f"wc: {path_text}: No such file or directory\n")
        return None
    return path.read_bytes()


def number_width(sources: list[tuple[str, bytes]], column_count: int) -> int:
    """Return the width numbers are padded to, as GNU wc chooses it

    One number for one input is not padded. Otherwise the width fits the total size of the regular files,
    and is seven when standard input is among the inputs

    Args:
        sources: Each input's label and bytes, an empty label meaning standard input
        column_count: How many numbers are printed per input

    Returns:
        The padding width
    """
    if len(sources) + column_count <= MINIMUM_NUMBER_WIDTH + 1:
        return MINIMUM_NUMBER_WIDTH
    if any(label in ("", STDIN_PATH) for label, _ in sources):
        return PIPE_NUMBER_WIDTH
    total_size = sum(len(data) for _, data in sources)
    return max(len(str(total_size)), MINIMUM_NUMBER_WIDTH)


class WcCommand(Command):
    """Print newline, word and byte counts for each input"""

    name = "wc"
    summary = "print newline, word, and byte counts for each file"
    input_kinds = frozenset(
        {InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.STREAM_BYTES, InputKind.BYTES, InputKind.ARGUMENTS}
    )
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Count every input and return one row per input, plus a total for several

        Args:
            invocation: The call to perform

        Returns:
            The rows
        """
        parser = CommandArgumentParser("wc", "Print newline, word, and byte counts for each file")
        parser.add_argument("-l", "--lines", action="store_true", help="print the newline counts")
        parser.add_argument("-w", "--words", action="store_true", help="print the word counts")
        parser.add_argument("-m", "--chars", action="store_true", help="print the character counts")
        parser.add_argument("-c", "--bytes", action="store_true", help="print the byte counts")
        parser.add_argument("-L", "--max-line-length", action="store_true", help="print the maximum display width")
        parser.add_argument("paths", nargs="*", help="files to read, - for standard input")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        columns = Columns.from_options(parsed.lines, parsed.words, parsed.chars, parsed.bytes, parsed.max_line_length)
        exit_code = EXIT_CODE_SUCCESS
        sources: list[tuple[str, bytes]] = []
        for path_text in parsed.paths or [""]:
            if path_text in ("", STDIN_PATH):
                sources.append((path_text, await read_stdin_bytes(invocation)))
                continue
            data = read_file(path_text, invocation.state)
            if data is None:
                exit_code = EXIT_CODE_FAILURE
                continue
            sources.append((path_text, data))
        width = number_width(sources, columns.count())
        rows: list[str] = []
        total = Counts(lines=0, words=0, characters=0, bytes=0, longest_line=0)
        for label, data in sources:
            counts = Counts.of(data)
            total = total.add(counts)
            rows.append(format_row(columns.values(counts), label, width))
        if len(parsed.paths) > 1:
            rows.append(format_row(columns.values(total), TOTAL_LABEL, width))
        return CommandResult(stdout="".join(rows), exit_code=exit_code)
