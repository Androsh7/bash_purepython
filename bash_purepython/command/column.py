"""Implement the column command"""

# Standard libraries
import math

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.sources import input_lines

DEFAULT_OUTPUT_WIDTH = 80
TABLE_COLUMN_GAP = "  "
FILL_COLUMN_GAP = 2


def split_fields(line: str, separators: str | None) -> list[str]:
    """Return the fields of one line, split on whitespace or on any of the separator characters

    Args:
        line: The line without its newline
        separators: The separator characters, or None for runs of whitespace

    Returns:
        The non-empty fields
    """
    if separators is None:
        return line.split()
    fields: list[str] = []
    current: list[str] = []
    for character in line:
        if character in separators:
            if current:
                fields.append("".join(current))
                current = []
        else:
            current.append(character)
    if current:
        fields.append("".join(current))
    return fields


def format_table(rows: list[list[str]]) -> str:
    """Return the rows as a table whose columns are padded to their widest field

    Args:
        rows: The fields of every line

    Returns:
        The text with the last field of every row left unpadded
    """
    column_count = max((len(row) for row in rows), default=0)
    widths = [0] * column_count
    for row in rows:
        for index, field in enumerate(row):
            widths[index] = max(widths[index], len(field))
    lines: list[str] = []
    for row in rows:
        padded = [field.ljust(widths[index]) for index, field in enumerate(row)]
        lines.append(TABLE_COLUMN_GAP.join(padded).rstrip())
    return "".join(f"{line}\n" for line in lines)


def format_columns(items: list[str], output_width: int) -> str:
    """Return the items filled down then across into as many columns as fit the width

    Args:
        items: The non-empty input lines
        output_width: The width to fill

    Returns:
        The text with every row's trailing padding removed
    """
    if not items:
        return ""
    column_width = max(len(item) for item in items) + FILL_COLUMN_GAP
    column_count = max(1, output_width // column_width)
    row_count = math.ceil(len(items) / column_count)
    lines: list[str] = []
    for row_number in range(row_count):
        cells = [items[index] for index in range(row_number, len(items), row_count)]
        lines.append("".join(cell.ljust(column_width) for cell in cells).rstrip())
    return "".join(f"{line}\n" for line in lines)


class ColumnCommand(Command):
    """Columnate lists, or align whitespace-separated fields into a table"""

    name = "column"
    summary = "columnate lists"
    input_kinds = frozenset({InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Lay the input out in columns, or as an aligned table under -t

        Args:
            invocation: The call to perform

        Returns:
            The laid-out text and exit code one if any source could not be read
        """
        parser = CommandArgumentParser("column", "Columnate lists")
        parser.add_argument("-t", "--table", action="store_true", help="create a table from the fields of each line")
        parser.add_argument("-s", "--separator", default=None, help="the characters that separate fields with -t")
        parser.add_argument("-c", "--output-width", type=int, default=DEFAULT_OUTPUT_WIDTH, help="accepted and ignored")
        parser.add_argument("paths", nargs="*", help="files to read, standard input if none")
        parsed = parse_command_arguments(parser, invocation.arguments, invocation.state)
        if isinstance(parsed, int):
            return CommandResult(stdout="", exit_code=parsed)
        lines = [line async for line in input_lines("column", invocation, parsed.paths) if line.strip()]
        if parsed.table:
            output = format_table([split_fields(line, parsed.separator) for line in lines])
        else:
            output = format_columns(lines, DEFAULT_OUTPUT_WIDTH)
        return CommandResult(stdout=output, exit_code=invocation.exit_status.code)
