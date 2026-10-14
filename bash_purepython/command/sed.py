"""Implement the sed command"""

# Standard libraries
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import StrEnum

# Project libraries
from bash_purepython.command.arguments import CommandArgumentParser, parse_command_arguments
from bash_purepython.command.command import Command, CommandInvocation, CommandResult, InputKind, OutputKind
from bash_purepython.command.lines import close_stdin, file_lines, iterate_lines, stdin_lines
from bash_purepython.shell_state import EXIT_CODE_SUCCESS, NULL_DEVICE_PATH
from bash_purepython.streams import TEXT_ENCODING, as_async_iterator, close_iterator

STDIN_PATH = "-"
EXIT_CODE_INVALID_SCRIPT = 1
EXIT_CODE_UNREADABLE_INPUT = 2
EXIT_CODE_CANNOT_EDIT = 4
FIRST_EXPRESSION_NUMBER = 1
DEFAULT_OCCURRENCE = 1
WHOLE_MATCH_GROUP = 0
MAXIMUM_GROUP_REFERENCE = 9
BASIC_ESCAPED_OPERATORS = "(){}+?|"
PYTHON_SPECIAL_CHARACTERS = ".^$*+?()[]{}|\\"
GROUP_OPENERS = "(|"
BLANKS = " \t"
COMMAND_TERMINATORS = ";\n}#"
SUBSTITUTE_FLAG_CHARACTERS = "gpiImM"
IN_PLACE_OPTION = "--in-place"
IN_PLACE_OPTION_WITH_SUFFIX = "--in-place="
OPTIONS_END = "--"
SHORT_OPTIONS_WITH_VALUE = "efl"
USAGE_TEXT = "Usage: sed [OPTION]... {script-only-if-no-other-script} [input-file]...\n"
POSIX_CLASSES = {
    "alpha": "a-zA-Z",
    "digit": "0-9",
    "alnum": "a-zA-Z0-9",
    "upper": "A-Z",
    "lower": "a-z",
    "space": r"\s",
    "blank": r" \t",
    "punct": r"!-/:-@\[-`{-~",
    "xdigit": "0-9A-Fa-f",
    "cntrl": r"\x00-\x1f\x7f",
    "print": r"\x20-\x7e",
    "graph": r"\x21-\x7e",
    "word": r"\w",
}


class SedScriptError(Exception):
    """Signal a script sed cannot compile, with the message GNU sed prints after its name"""


class AddressKind(StrEnum):
    """Name the forms an address can take"""

    LINE = "line"
    LAST = "last"
    REGEX = "regex"
    STEP = "step"
    RELATIVE = "relative"
    MULTIPLE = "multiple"


class InstructionKind(StrEnum):
    """Name the script commands, by the character that introduces each"""

    SUBSTITUTE = "s"
    TRANSLITERATE = "y"
    PRINT = "p"
    DELETE = "d"
    QUIT = "q"
    QUIT_SILENT = "Q"
    LINE_NUMBER = "="
    APPEND = "a"
    INSERT = "i"
    CHANGE = "c"
    GROUP = "{"


class CycleOutcome(StrEnum):
    """Name how running the script over one line ended"""

    CONTINUE = "continue"
    DELETE = "delete"
    QUIT = "quit"
    QUIT_SILENT = "quit_silent"


@dataclass(frozen=True)
class Address:
    """Hold one address: a line number, the last line, a regex, a stepped sequence or a relative end"""

    kind: AddressKind
    number: int = 0
    step: int = 0
    regex: re.Pattern[str] | None = None


@dataclass
class Instruction:
    """Hold one script command with its addresses and the state of its range"""

    kind: InstructionKind
    start: Address | None = None
    end: Address | None = None
    negated: bool = False
    regex: re.Pattern[str] | None = None
    replacement: Callable[[re.Match[str]], str] | None = None
    replace_all: bool = False
    occurrence: int = DEFAULT_OCCURRENCE
    print_after: bool = False
    text: str = ""
    translation: dict[int, str] = field(default_factory=dict)
    exit_code: int = EXIT_CODE_SUCCESS
    children: list["Instruction"] = field(default_factory=list)
    range_active: bool = False
    range_end_line: int = 0


@dataclass
class Cycle:
    """Hold the pattern space and the output gathered while one line runs through the script"""

    pattern_space: str
    line_number: int
    is_last: bool
    output: list[str] = field(default_factory=list)
    appended: list[str] = field(default_factory=list)


def translate_bracket(pattern: str, index: int) -> tuple[str, int]:
    """Return a POSIX bracket expression as a Python character class and the index after it

    Args:
        pattern: The whole regular expression
        index: The index of the opening bracket

    Raises:
        re.error: If the bracket expression is never closed

    Returns:
        The Python character class and the index following its closing bracket
    """
    position = index + 1
    pieces = ["["]
    if pattern[position : position + 1] == "^":
        pieces.append("^")
        position += 1
    if pattern[position : position + 1] == "]":
        pieces.append(r"\]")
        position += 1
    while position < len(pattern):
        character = pattern[position]
        if character == "]":
            pieces.append("]")
            return "".join(pieces), position + 1
        if character == "[" and pattern[position + 1 : position + 2] == ":":
            close = pattern.find(":]", position + 2)
            class_name = pattern[position + 2 : close] if close != -1 else ""
            if class_name in POSIX_CLASSES:
                pieces.append(POSIX_CLASSES[class_name])
                position = close + 2
                continue
        if character == "\\" and pattern[position + 1 : position + 2] in ("n", "t"):
            pieces.append("\\" + pattern[position + 1])
            position += 2
            continue
        pieces.append("\\" + character if character in "\\[" else character)
        position += 1
    raise re.error("unterminated bracket expression")


def translate_regex(pattern: str, extended: bool) -> str:
    """Return a POSIX basic or extended regular expression rewritten for Python's re module

    Args:
        pattern: The expression as written in the script
        extended: Whether the expression uses the extended syntax

    Raises:
        re.error: If the expression ends in a backslash or leaves a bracket open

    Returns:
        The equivalent Python pattern
    """
    pieces: list[str] = []
    position = 0
    at_start = True
    length = len(pattern)
    while position < length:
        character = pattern[position]
        if character == "\\":
            if position + 1 >= length:
                raise re.error("trailing backslash")
            escaped = pattern[position + 1]
            position += 2
            if not extended and escaped in BASIC_ESCAPED_OPERATORS:
                pieces.append(escaped)
                at_start = escaped in GROUP_OPENERS
                continue
            if escaped in "<>":
                pieces.append(r"\b")
            elif escaped == "`":
                pieces.append(r"\A")
            elif escaped == "'":
                pieces.append(r"\Z")
            elif escaped in "ntwWsSbB" or escaped.isdigit():
                pieces.append("\\" + escaped)
            else:
                pieces.append(re.escape(escaped))
            at_start = False
            continue
        if character == "[":
            bracket, position = translate_bracket(pattern, position)
            pieces.append(bracket)
            at_start = False
            continue
        position += 1
        if character == "*" and at_start:
            pieces.append(r"\*")
            at_start = False
        elif character == "^":
            pieces.append("^" if extended or at_start else r"\^")
        elif character == "$":
            is_anchor = extended or position == length or pattern.startswith(("\\)", "\\|"), position)
            pieces.append("$" if is_anchor else r"\$")
            at_start = False
        elif not extended and character in BASIC_ESCAPED_OPERATORS:
            pieces.append("\\" + character)
            at_start = False
        elif extended and character in GROUP_OPENERS:
            pieces.append(character)
            at_start = True
        else:
            pieces.append(character)
            at_start = False
    return "".join(pieces)


def literal_regex(character: str, extended: bool) -> str:
    """Return a character written so the regex dialect treats it literally

    Args:
        character: The character to match
        extended: Whether the expression uses the extended syntax

    Returns:
        The character, escaped or left bare as the dialect needs
    """
    if not extended and character in BASIC_ESCAPED_OPERATORS:
        return character
    if character in PYTHON_SPECIAL_CHARACTERS:
        return "\\" + character
    return character


def compile_replacement(text: str, group_count: int) -> Callable[[re.Match[str]], str]:
    """Return a function building the replacement text for one match

    Args:
        text: The replacement as written, with ``&``, backslash group numbers, and backslash n and t escapes
        group_count: How many groups the regular expression has

    Raises:
        SedScriptError: If a group reference names a group the expression lacks

    Returns:
        A function from a match to the text that replaces it
    """
    pieces: list[str | int] = []
    literal: list[str] = []
    position = 0
    while position < len(text):
        character = text[position]
        position += 1
        if character == "\\" and position < len(text):
            escaped = text[position]
            position += 1
            if escaped.isdigit():
                group_number = int(escaped)
                if group_number > group_count:
                    raise SedScriptError(f"invalid reference \\{group_number} on `s' command's RHS")
                pieces.append("".join(literal))
                literal.clear()
                pieces.append(group_number)
            elif escaped == "n":
                literal.append("\n")
            elif escaped == "t":
                literal.append("\t")
            else:
                literal.append(escaped)
        elif character == "&":
            pieces.append("".join(literal))
            literal.clear()
            pieces.append(WHOLE_MATCH_GROUP)
        else:
            literal.append(character)
    pieces.append("".join(literal))

    def build(match: re.Match[str]) -> str:
        """Return the replacement for one match

        Args:
            match: The match being replaced

        Returns:
            The literal pieces with every group reference filled in
        """
        return "".join(piece if isinstance(piece, str) else (match.group(piece) or "") for piece in pieces)

    return build


class ScriptParser:
    """Turn one script expression into instructions, reporting errors as GNU sed words them"""

    def __init__(self, text: str, expression_number: int, extended: bool):
        """Prepare to parse one expression

        Args:
            text: The script text
            expression_number: Which ``-e`` expression this is, for error messages
            extended: Whether regular expressions use the extended syntax
        """
        self.text = text
        self.expression_number = expression_number
        self.extended = extended
        self.position = 0

    def error(self, message: str) -> SedScriptError:
        """Return an error located at the current position

        Args:
            message: What is wrong

        Returns:
            The error to raise
        """
        return SedScriptError(f"-e expression #{self.expression_number}, char {self.position}: {message}")

    def at_end(self) -> bool:
        """Return whether every character has been consumed"""
        return self.position >= len(self.text)

    def peek(self) -> str:
        """Return the next character, or an empty string at the end"""
        return self.text[self.position : self.position + 1]

    def take(self) -> str:
        """Return the next character and move past it, or an empty string at the end"""
        character = self.peek()
        self.position += len(character)
        return character

    def skip_blanks(self) -> None:
        """Move past spaces and tabs"""
        while self.peek() and self.peek() in BLANKS:
            self.position += 1

    def skip_separators(self) -> None:
        """Move past whitespace, semicolons and comments between commands"""
        while not self.at_end():
            character = self.peek()
            if character == "#":
                newline = self.text.find("\n", self.position)
                self.position = len(self.text) if newline == -1 else newline
            elif character in BLANKS or character in ";\n":
                self.position += 1
            else:
                return

    def read_number(self) -> int:
        """Return the decimal number at the current position, moving past it

        Raises:
            SedScriptError: If no digit is there

        Returns:
            The number
        """
        start = self.position
        while self.peek().isdigit():
            self.position += 1
        if start == self.position:
            raise self.error("expected a number")
        return int(self.text[start : self.position])

    def parse(self) -> list[Instruction]:
        """Return the instructions of the whole expression

        Raises:
            SedScriptError: If the script is malformed

        Returns:
            The instructions in order
        """
        return self.parse_sequence(inside_group=False)

    def parse_sequence(self, inside_group: bool) -> list[Instruction]:
        """Return the instructions up to the end of the text or the closing brace of a group

        Args:
            inside_group: Whether a closing brace ends the sequence

        Raises:
            SedScriptError: If a brace is unmatched

        Returns:
            The instructions in order
        """
        instructions: list[Instruction] = []
        while True:
            self.skip_separators()
            if self.at_end():
                if inside_group:
                    raise self.error("unmatched `{'")
                return instructions
            if self.peek() == "}":
                self.position += 1
                if not inside_group:
                    raise self.error("unexpected `}'")
                return instructions
            instructions.append(self.parse_instruction())

    def parse_instruction(self) -> Instruction:
        """Return the next command with its addresses

        Raises:
            SedScriptError: If the command is unknown or malformed

        Returns:
            The instruction
        """
        start = self.parse_address()
        end = None
        if start is not None:
            self.skip_blanks()
            if self.peek() == ",":
                self.position += 1
                self.skip_blanks()
                end = self.parse_second_address()
        self.skip_blanks()
        negated = False
        while self.peek() == "!":
            negated = True
            self.position += 1
            self.skip_blanks()
        if self.at_end():
            raise self.error("missing command")
        command_character = self.take()
        try:
            kind = InstructionKind(command_character)
        except ValueError:
            raise self.error(f"unknown command: `{command_character}'") from None
        instruction = Instruction(kind=kind, start=start, end=end, negated=negated)
        if kind == InstructionKind.GROUP:
            instruction.children = self.parse_sequence(inside_group=True)
            return instruction
        if kind == InstructionKind.SUBSTITUTE:
            self.parse_substitute(instruction)
            return instruction
        if kind == InstructionKind.TRANSLITERATE:
            self.parse_transliterate(instruction)
        elif kind in (InstructionKind.APPEND, InstructionKind.INSERT, InstructionKind.CHANGE):
            instruction.text = self.parse_text()
            return instruction
        elif kind in (InstructionKind.QUIT, InstructionKind.QUIT_SILENT):
            if end is not None:
                raise self.error("command only uses one address")
            self.skip_blanks()
            if self.peek().isdigit():
                instruction.exit_code = self.read_number()
        self.expect_end_of_command("extra characters after command")
        return instruction

    def expect_end_of_command(self, message: str) -> None:
        """Move past trailing blanks and check that the command is followed by a separator

        Args:
            message: The error to report when something else follows

        Raises:
            SedScriptError: If the command is followed by anything but a separator
        """
        self.skip_blanks()
        if not self.at_end() and self.peek() not in COMMAND_TERMINATORS:
            self.position += 1
            raise self.error(message)

    def parse_address(self) -> Address | None:
        """Return the address at the current position, or None when there is none

        Raises:
            SedScriptError: If the address is malformed

        Returns:
            The address, or None
        """
        character = self.peek()
        if character.isdigit():
            number = self.read_number()
            if self.peek() == "~":
                self.position += 1
                return Address(kind=AddressKind.STEP, number=number, step=self.read_number())
            if number == 0:
                raise self.error("invalid usage of line address 0")
            return Address(kind=AddressKind.LINE, number=number)
        if character == "$":
            self.position += 1
            return Address(kind=AddressKind.LAST)
        if character == "/":
            self.position += 1
            return self.parse_regex_address("/")
        if character == "\\":
            self.position += 1
            delimiter = self.take()
            if not delimiter or delimiter == "\n":
                raise self.error("unterminated address regex")
            return self.parse_regex_address(delimiter)
        return None

    def parse_second_address(self) -> Address:
        """Return the address after the comma, which may also be ``+N`` or ``~N``

        Raises:
            SedScriptError: If nothing usable follows the comma

        Returns:
            The address
        """
        character = self.peek()
        if character in ("+", "~"):
            self.position += 1
            kind = AddressKind.RELATIVE if character == "+" else AddressKind.MULTIPLE
            return Address(kind=kind, number=self.read_number())
        address = self.parse_address()
        if address is None or address.kind == AddressKind.STEP:
            raise self.error("unexpected `,'")
        return address

    def parse_regex_address(self, delimiter: str) -> Address:
        """Return a regex address whose expression runs to the delimiter

        Args:
            delimiter: The character closing the expression

        Raises:
            SedScriptError: If the expression is unterminated, empty or invalid

        Returns:
            The address
        """
        pattern = self.read_delimited(delimiter, "unterminated address regex", for_regex=True)
        flags = 0
        while self.peek() in ("I", "M"):
            flags |= re.IGNORECASE if self.take() == "I" else re.MULTILINE
        return Address(kind=AddressKind.REGEX, regex=self.compile_regex(pattern, flags))

    def compile_regex(self, pattern: str, flags: int) -> re.Pattern[str]:
        """Return the compiled form of a script regular expression

        Args:
            pattern: The expression as written in the script
            flags: The re flags to compile with

        Raises:
            SedScriptError: If the expression is empty or invalid

        Returns:
            The compiled pattern
        """
        if not pattern:
            raise self.error("no previous regular expression")
        try:
            return re.compile(translate_regex(pattern, self.extended), flags)
        except re.error as error:
            raise self.error(f"invalid regular expression: {error.msg}") from error

    def read_delimited(self, delimiter: str, message: str, for_regex: bool) -> str:
        """Return the text up to an unescaped delimiter, moving past the delimiter

        Args:
            delimiter: The character that ends the text
            message: The error to report when the text never ends
            for_regex: Whether an escaped delimiter becomes a literal in the regex dialect

        Raises:
            SedScriptError: If the delimiter never appears

        Returns:
            The text with escaped delimiters resolved and other escapes kept
        """
        pieces: list[str] = []
        while not self.at_end():
            character = self.take()
            if character == delimiter:
                return "".join(pieces)
            if character == "\\" and not self.at_end():
                escaped = self.take()
                if escaped == delimiter:
                    pieces.append(literal_regex(escaped, self.extended) if for_regex else escaped)
                elif escaped == "\n":
                    pieces.append("\n")
                else:
                    pieces.append("\\" + escaped)
            else:
                pieces.append(character)
        raise self.error(message)

    def parse_substitute(self, instruction: Instruction) -> None:
        """Fill in the regex, replacement and flags of an ``s`` command

        Args:
            instruction: The instruction to complete

        Raises:
            SedScriptError: If the command is unterminated or has an unknown flag
        """
        delimiter = self.take()
        if not delimiter or delimiter in ("\n", "\\"):
            raise self.error("unterminated `s' command")
        pattern = self.read_delimited(delimiter, "unterminated `s' command", for_regex=True)
        replacement = self.read_delimited(delimiter, "unterminated `s' command", for_regex=False)
        flags = 0
        while self.peek() and self.peek() not in COMMAND_TERMINATORS and self.peek() not in BLANKS:
            flag = self.take()
            if flag.isdigit():
                self.position -= 1
                instruction.occurrence = self.read_number()
                if instruction.occurrence == 0:
                    raise self.error("number option to `s' command may not be zero")
            elif flag == "g":
                instruction.replace_all = True
            elif flag == "p":
                instruction.print_after = True
            elif flag in ("i", "I"):
                flags |= re.IGNORECASE
            elif flag in ("m", "M"):
                flags |= re.MULTILINE
            else:
                raise self.error("unknown option to `s'")
        self.expect_end_of_command("unknown option to `s'")
        instruction.regex = self.compile_regex(pattern, flags)
        try:
            instruction.replacement = compile_replacement(replacement, instruction.regex.groups)
        except SedScriptError as error:
            raise self.error(str(error)) from error

    def parse_transliterate(self, instruction: Instruction) -> None:
        """Fill in the translation table of a ``y`` command

        Args:
            instruction: The instruction to complete

        Raises:
            SedScriptError: If the command is unterminated or its two strings differ in length
        """
        delimiter = self.take()
        if not delimiter or delimiter in ("\n", "\\"):
            raise self.error("unterminated `y' command")
        source = self.read_transliteration_part(delimiter)
        target = self.read_transliteration_part(delimiter)
        if len(source) != len(target):
            raise self.error("strings for `y' command are different lengths")
        instruction.translation = str.maketrans(source, target)

    def read_transliteration_part(self, delimiter: str) -> str:
        """Return one of the two strings of a ``y`` command with its escapes resolved

        Args:
            delimiter: The character that ends the string

        Raises:
            SedScriptError: If the string never ends

        Returns:
            The characters
        """
        raw = self.read_delimited(delimiter, "unterminated `y' command", for_regex=False)
        resolved: list[str] = []
        position = 0
        while position < len(raw):
            character = raw[position]
            position += 1
            if character == "\\" and position < len(raw):
                escaped = raw[position]
                position += 1
                resolved.append({"n": "\n", "t": "\t"}.get(escaped, escaped))
            else:
                resolved.append(character)
        return "".join(resolved)

    def parse_text(self) -> str:
        """Return the text of an ``a``, ``i`` or ``c`` command, which runs to the end of the line

        Raises:
            SedScriptError: If no text follows the command

        Returns:
            The text without its trailing newline
        """
        self.skip_blanks()
        backslash_form = self.peek() == "\\"
        if backslash_form:
            self.position += 1
            if self.peek() == "\n":
                self.position += 1
        characters: list[str] = []
        while not self.at_end():
            character = self.take()
            if character == "\\":
                if self.at_end():
                    break
                characters.append(self.take())
            elif character == "\n":
                break
            else:
                characters.append(character)
        text = "".join(characters)
        if not text and not backslash_form:
            raise self.error("expected \\ after `a', `c' or `i'")
        return text


def substitute(pattern_space: str, instruction: Instruction) -> tuple[str, bool]:
    """Return the pattern space with the substitution applied and whether anything was replaced

    Args:
        pattern_space: The current line
        instruction: The ``s`` command

    Returns:
        The new text and whether a match was replaced
    """
    if instruction.regex is None or instruction.replacement is None:
        return pattern_space, False
    pieces: list[str] = []
    last_end = 0
    previous_match_end: int | None = None
    seen = 0
    replaced = False
    for match in instruction.regex.finditer(pattern_space):
        if match.start() == match.end() == previous_match_end:
            continue
        previous_match_end = match.end()
        seen += 1
        if seen < instruction.occurrence:
            continue
        pieces.append(pattern_space[last_end : match.start()])
        pieces.append(instruction.replacement(match))
        last_end = match.end()
        replaced = True
        if not instruction.replace_all:
            break
    pieces.append(pattern_space[last_end:])
    return "".join(pieces), replaced


class SedProgram:
    """Run compiled instructions over lines, keeping the line number and range state between them"""

    def __init__(self, instructions: list[Instruction], quiet: bool):
        """Hold the script

        Args:
            instructions: The compiled script
            quiet: Whether the pattern space is not printed at the end of each cycle
        """
        self.instructions = instructions
        self.quiet = quiet
        self.line_number = 0
        self.exit_code = EXIT_CODE_SUCCESS

    def start_file(self) -> None:
        """Restart line numbering and every range for a file treated separately"""
        self.line_number = 0
        self.reset_ranges(self.instructions)

    def reset_ranges(self, instructions: list[Instruction]) -> None:
        """Close every open range in a list of instructions and their groups

        Args:
            instructions: The instructions to reset
        """
        for instruction in instructions:
            instruction.range_active = False
            self.reset_ranges(instruction.children)

    def process_line(self, line: str, is_last: bool) -> tuple[str, bool]:
        """Run the script over one line and return what it printed and whether it quit

        Args:
            line: The line with its newline, if it had one
            is_last: Whether no line follows

        Returns:
            The output text and whether a quit command ran
        """
        has_newline = line.endswith("\n")
        self.line_number += 1
        cycle = Cycle(pattern_space=line[:-1] if has_newline else line, line_number=self.line_number, is_last=is_last)
        outcome = self.execute(self.instructions, cycle)
        if outcome in (CycleOutcome.CONTINUE, CycleOutcome.QUIT) and not self.quiet:
            cycle.output.append(cycle.pattern_space + "\n")
        cycle.output.extend(cycle.appended)
        text = "".join(cycle.output)
        if not has_newline and text.endswith("\n") and not cycle.appended:
            text = text[:-1]
        return text, outcome in (CycleOutcome.QUIT, CycleOutcome.QUIT_SILENT)

    def execute(self, instructions: list[Instruction], cycle: Cycle) -> CycleOutcome:
        """Run a list of instructions over the cycle's pattern space

        Args:
            instructions: The instructions to run in order
            cycle: The line being processed

        Returns:
            How the run ended
        """
        for instruction in instructions:
            if not self.selects(instruction, cycle):
                continue
            kind = instruction.kind
            if kind == InstructionKind.GROUP:
                outcome = self.execute(instruction.children, cycle)
                if outcome != CycleOutcome.CONTINUE:
                    return outcome
            elif kind == InstructionKind.SUBSTITUTE:
                cycle.pattern_space, replaced = substitute(cycle.pattern_space, instruction)
                if replaced and instruction.print_after:
                    cycle.output.append(cycle.pattern_space + "\n")
            elif kind == InstructionKind.TRANSLITERATE:
                cycle.pattern_space = cycle.pattern_space.translate(instruction.translation)
            elif kind == InstructionKind.PRINT:
                cycle.output.append(cycle.pattern_space + "\n")
            elif kind == InstructionKind.DELETE:
                return CycleOutcome.DELETE
            elif kind == InstructionKind.QUIT:
                self.exit_code = instruction.exit_code
                return CycleOutcome.QUIT
            elif kind == InstructionKind.QUIT_SILENT:
                self.exit_code = instruction.exit_code
                return CycleOutcome.QUIT_SILENT
            elif kind == InstructionKind.LINE_NUMBER:
                cycle.output.append(f"{cycle.line_number}\n")
            elif kind == InstructionKind.APPEND:
                cycle.appended.append(instruction.text + "\n" if instruction.text else "")
            elif kind == InstructionKind.INSERT:
                cycle.output.append(instruction.text + "\n")
            elif kind == InstructionKind.CHANGE:
                if instruction.end is None or instruction.negated or not instruction.range_active:
                    cycle.output.append(instruction.text + "\n")
                return CycleOutcome.DELETE
        return CycleOutcome.CONTINUE

    def selects(self, instruction: Instruction, cycle: Cycle) -> bool:
        """Return whether an instruction applies to the current line, advancing its range state

        Args:
            instruction: The instruction with its addresses
            cycle: The line being processed

        Returns:
            Whether the instruction runs, after negation
        """
        if instruction.start is None:
            return not instruction.negated
        if instruction.end is None:
            selected = self.matches(instruction.start, cycle)
        elif instruction.range_active:
            selected = True
            self.close_range_if_ended(instruction, cycle)
        else:
            selected = self.matches(instruction.start, cycle)
            if selected:
                self.open_range(instruction, cycle)
        return selected != instruction.negated

    def open_range(self, instruction: Instruction, cycle: Cycle) -> None:
        """Mark a range as started on the current line unless it also ends here

        Args:
            instruction: The instruction whose first address matched
            cycle: The line being processed
        """
        end = instruction.end
        if end is None:
            return
        line_number = cycle.line_number
        if end.kind == AddressKind.LINE:
            instruction.range_active = end.number > line_number
        elif end.kind == AddressKind.RELATIVE:
            instruction.range_end_line = line_number + end.number
            instruction.range_active = end.number > 0
        elif end.kind == AddressKind.MULTIPLE:
            instruction.range_active = end.number > 0 and line_number % end.number != 0
        elif end.kind == AddressKind.LAST:
            instruction.range_active = not cycle.is_last
        else:
            instruction.range_active = True

    def close_range_if_ended(self, instruction: Instruction, cycle: Cycle) -> None:
        """Mark an open range as finished when the current line is its last

        Args:
            instruction: The instruction whose range is open
            cycle: The line being processed
        """
        end = instruction.end
        if end is None:
            return
        line_number = cycle.line_number
        if end.kind == AddressKind.LINE:
            ended = line_number >= end.number
        elif end.kind == AddressKind.RELATIVE:
            ended = line_number >= instruction.range_end_line
        elif end.kind == AddressKind.MULTIPLE:
            ended = line_number % end.number == 0
        elif end.kind == AddressKind.LAST:
            ended = cycle.is_last
        else:
            ended = end.regex is not None and end.regex.search(cycle.pattern_space) is not None
        if ended:
            instruction.range_active = False

    def matches(self, address: Address, cycle: Cycle) -> bool:
        """Return whether a single address matches the current line

        Args:
            address: The address
            cycle: The line being processed

        Returns:
            Whether it matches
        """
        if address.kind == AddressKind.LINE:
            return cycle.line_number == address.number
        if address.kind == AddressKind.LAST:
            return cycle.is_last
        if address.kind == AddressKind.REGEX:
            return address.regex is not None and address.regex.search(cycle.pattern_space) is not None
        if address.kind == AddressKind.STEP:
            if address.step <= 0:
                return cycle.line_number == address.number
            return cycle.line_number >= address.number and (cycle.line_number - address.number) % address.step == 0
        return False


def join_continued_expressions(expressions: list[str]) -> list[str]:
    """Return the expressions with each one ending in a backslash joined to the next by a newline

    Args:
        expressions: The ``-e`` expressions in order

    Returns:
        The expressions, with the text of an ``a``, ``i`` or ``c`` command carried over from the next
    """
    joined: list[str] = []
    for expression in expressions:
        if joined and joined[-1].endswith("\\"):
            joined[-1] = joined[-1] + "\n" + expression
        else:
            joined.append(expression)
    return joined


def compile_script(expressions: list[str], extended: bool) -> list[Instruction]:
    """Return the instructions of every expression in order

    Args:
        expressions: The ``-e`` expressions, or the single positional script
        extended: Whether regular expressions use the extended syntax

    Raises:
        SedScriptError: If any expression is malformed

    Returns:
        The instructions
    """
    instructions: list[Instruction] = []
    for offset, expression in enumerate(join_continued_expressions(expressions)):
        instructions.extend(ScriptParser(expression, FIRST_EXPRESSION_NUMBER + offset, extended).parse())
    return instructions


def extract_in_place(arguments: list[str]) -> tuple[list[str], str | None]:
    """Return the arguments without the in-place option and the backup suffix it carried

    Args:
        arguments: The arguments after the command name

    Returns:
        The remaining arguments and the suffix, which is empty for a bare ``-i`` and None when absent
    """
    remaining: list[str] = []
    suffix: str | None = None
    skip_next = False
    for index, argument in enumerate(arguments):
        if skip_next:
            skip_next = False
            remaining.append(argument)
            continue
        if argument == OPTIONS_END:
            remaining.extend(arguments[index:])
            break
        if argument == IN_PLACE_OPTION:
            suffix = ""
            continue
        if argument.startswith(IN_PLACE_OPTION_WITH_SUFFIX):
            suffix = argument[len(IN_PLACE_OPTION_WITH_SUFFIX) :]
            continue
        if not argument.startswith("-") or argument.startswith("--"):
            remaining.append(argument)
            continue
        letters = argument[1:]
        kept = "-"
        for position, letter in enumerate(letters):
            if letter == "i":
                suffix = letters[position + 1 :]
                break
            kept += letter
            if letter in SHORT_OPTIONS_WITH_VALUE:
                kept += letters[position + 1 :]
                skip_next = position + 1 == len(letters)
                break
        if kept != "-":
            remaining.append(kept)
    return remaining, suffix


async def text_line_pairs(text: str) -> AsyncIterator[tuple[str, bool]]:
    """Yield each line of a text, paired with whether it is the last line

    Args:
        text: The whole text, with its line endings as they are on disk

    Yields:
        Each line with its newline kept, and the last-line flag
    """
    pending: str | None = None
    async for line in iterate_lines([text]):
        if pending is not None:
            yield pending, False
        pending = line
    if pending is not None:
        yield pending, True


async def source_line_pairs(invocation: CommandInvocation, paths: list[str]) -> AsyncIterator[tuple[str, bool]]:
    """Yield each line of the sources in order, paired with whether it is the last line of all of them

    A source that cannot be read is reported and the exit status set to two

    Args:
        invocation: The call, providing standard input and the shell state
        paths: The sources, ``-`` meaning standard input

    Yields:
        Each line with its newline kept, and the last-line flag
    """
    pending: str | None = None
    for path_text in paths:
        lines = open_input(path_text, invocation)
        if lines is None:
            continue
        try:
            async for line in lines:
                if pending is not None:
                    yield pending, False
                pending = line
        finally:
            await close_iterator(lines)
    if pending is not None:
        yield pending, True


def open_input(path_text: str, invocation: CommandInvocation) -> AsyncIterator[str] | None:
    """Return the lines of one source, or None after reporting why it cannot be read

    Args:
        path_text: A file path, ``-`` for standard input, or the null device
        invocation: The call, providing standard input and the shell state

    Returns:
        An async iterator over the lines, or None
    """
    if path_text == STDIN_PATH:
        if invocation.stdin_kind == InputKind.ARGUMENTS:
            return as_async_iterator(())
        return stdin_lines(invocation.stdin, invocation.stdin_kind)
    if path_text == NULL_DEVICE_PATH:
        return as_async_iterator(())
    path = invocation.state.resolve_path(path_text)
    if path.is_dir():
        invocation.state.write_error(f"sed: couldn't edit {path_text}: not a regular file\n")
        invocation.exit_status.code = EXIT_CODE_UNREADABLE_INPUT
        return None
    if not path.exists():
        invocation.state.write_error(f"sed: can't read {path_text}: No such file or directory\n")
        invocation.exit_status.code = EXIT_CODE_UNREADABLE_INPUT
        return None
    return file_lines(path)


async def edit_stream(
    invocation: CommandInvocation, program: SedProgram, paths: list[str], separate: bool
) -> AsyncIterator[str]:
    """Yield the script's output over every source, stopping at a quit command

    Args:
        invocation: The call, providing standard input and the shell state
        program: The compiled script
        paths: The sources in order
        separate: Whether each file restarts line numbers and ranges

    Yields:
        Output text as each line is processed, with the newline a source's last line lacked restored once more
        output follows it
    """
    groups = [[path_text] for path_text in paths] if separate else [paths]
    missing_newline = False
    try:
        for group in groups:
            program.start_file()
            pairs = source_line_pairs(invocation, group)
            try:
                async for line, is_last in pairs:
                    text, quit_requested = program.process_line(line, is_last)
                    if text:
                        if missing_newline:
                            yield "\n"
                        yield text
                        missing_newline = not text.endswith("\n")
                    if quit_requested:
                        if program.exit_code != EXIT_CODE_SUCCESS:
                            invocation.exit_status.code = program.exit_code
                        return
            finally:
                await close_iterator(pairs)
    finally:
        await close_stdin(invocation.stdin)


async def edit_in_place(invocation: CommandInvocation, program: SedProgram, paths: list[str], suffix: str) -> int:
    """Rewrite every file with the script's output, keeping a backup when a suffix is given

    Args:
        invocation: The call, whose state resolves paths and reports errors
        program: The compiled script
        paths: The files to edit
        suffix: The backup suffix, empty for no backup

    Returns:
        The exit code
    """
    exit_code = EXIT_CODE_SUCCESS
    for path_text in paths:
        path = invocation.state.resolve_path(path_text)
        if path_text == STDIN_PATH or (path.exists() and not path.is_file()):
            invocation.state.write_error(f"sed: couldn't edit {path_text}: not a regular file\n")
            exit_code = EXIT_CODE_CANNOT_EDIT
            continue
        if not path.exists():
            invocation.state.write_error(f"sed: can't read {path_text}: No such file or directory\n")
            exit_code = EXIT_CODE_UNREADABLE_INPUT
            continue
        with path.open(encoding=TEXT_ENCODING, errors="replace", newline="") as handle:
            original = handle.read()
        program.start_file()
        pieces: list[str] = []
        quit_requested = False
        async for line, is_last in text_line_pairs(original):
            text, quit_requested = program.process_line(line, is_last)
            pieces.append(text)
            if quit_requested:
                break
        if suffix:
            path.with_name(path.name + suffix).write_text(original, encoding=TEXT_ENCODING, newline="")
        path.write_text("".join(pieces), encoding=TEXT_ENCODING, newline="")
        if quit_requested:
            return program.exit_code if program.exit_code != EXIT_CODE_SUCCESS else exit_code
    return exit_code


class SedCommand(Command):
    """Filter and transform text with a stream editor script"""

    name = "sed"
    summary = "filter and transform text"
    input_kinds = frozenset({InputKind.STREAM_TEXT, InputKind.TEXT, InputKind.ARGUMENTS})
    output_kinds = frozenset({OutputKind.STREAM_TEXT})

    async def run(self, invocation: CommandInvocation) -> CommandResult:
        """Return a stream of the edited lines, or rewrite the files in place

        Args:
            invocation: The call to perform

        Returns:
            The lazy stream, empty when editing in place
        """
        parser = CommandArgumentParser("sed", "Filter and transform text with a stream editor script")
        parser.add_argument("-n", "--quiet", "--silent", action="store_true", help="suppress automatic printing")
        parser.add_argument("-e", "--expression", dest="expressions", action="append", default=[], help="a script")
        parser.add_argument("-f", "--file", dest="script_files", action="append", default=[], help="a script file")
        parser.add_argument("-E", "-r", "--regexp-extended", action="store_true", help="use extended regexps")
        parser.add_argument("-s", "--separate", action="store_true", help="treat files as separate streams")
        parser.add_argument("-u", "--unbuffered", action="store_true", help="accepted and ignored")
        parser.add_argument("-l", "--line-length", type=int, default=None, help="accepted and ignored")
        parser.add_argument("script_and_paths", nargs="*", help="the script unless -e is given, then files")
        arguments, in_place_suffix = extract_in_place(invocation.arguments)
        parsed = parse_command_arguments(parser, arguments, invocation.state)
        if isinstance(parsed, int):
            await close_stdin(invocation.stdin)
            return CommandResult(stdout=as_async_iterator(()), exit_code=parsed)
        expressions = list(parsed.expressions)
        paths = list(parsed.script_and_paths)
        for script_file in parsed.script_files:
            script_path = invocation.state.resolve_path(script_file)
            if not script_path.is_file():
                message = f"sed: couldn't open file {script_file}: No such file or directory\n"
                return await self.fail(invocation, message)
            expressions.append(script_path.read_text(encoding=TEXT_ENCODING, errors="replace"))
        if not expressions:
            if not paths:
                return await self.fail(invocation, USAGE_TEXT)
            expressions.append(paths.pop(0))
        try:
            instructions = compile_script(expressions, parsed.regexp_extended)
        except SedScriptError as error:
            return await self.fail(invocation, f"sed: {error}\n")
        program = SedProgram(instructions, parsed.quiet)
        if in_place_suffix is not None:
            await close_stdin(invocation.stdin)
            exit_code = await edit_in_place(invocation, program, paths, in_place_suffix)
            return CommandResult(stdout=as_async_iterator(()), exit_code=exit_code)
        stream = edit_stream(invocation, program, paths or [STDIN_PATH], parsed.separate)
        return CommandResult(stdout=stream, exit_code=EXIT_CODE_SUCCESS)

    async def fail(self, invocation: CommandInvocation, message: str) -> CommandResult:
        """Report a script problem and return an empty result with the invalid-script exit code

        Args:
            invocation: The call, whose state receives the message
            message: The full message including the trailing newline

        Returns:
            An empty stream with exit code one
        """
        invocation.state.write_error(message)
        await close_stdin(invocation.stdin)
        return CommandResult(stdout=as_async_iterator(()), exit_code=EXIT_CODE_INVALID_SCRIPT)
