"""Split a shell script into classified top-level command blocks"""

# Standard libraries
import re
from dataclasses import dataclass
from enum import StrEnum

COMPOUND_OPENING_KEYWORDS = frozenset({"if", "for", "while", "until", "case", "select"})
COMPOUND_CLOSING_KEYWORDS = frozenset({"fi", "done", "esac"})
KEYWORDS_FOLLOWED_BY_A_COMMAND = frozenset({"if", "then", "elif", "else", "while", "until", "do", "!", "time"})
WORD_BREAK_CHARACTERS = frozenset(" \t\n;&|()<>{}'\"\\`$")
WHITESPACE_CHARACTERS = frozenset(" \t")
REDIRECTION_CHARACTERS = frozenset("<>|")
HEREDOC_OPERATOR_PATTERN = re.compile(r"<<(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|(\\?[^\s;&|()<>'\"]+))")


class Nesting(StrEnum):
    """Name each kind of bracket or block that can keep a separator from ending a command"""

    PARENTHESIS = "parenthesis"
    BRACE_GROUP = "brace_group"
    PARAMETER_EXPANSION = "parameter_expansion"
    COMPOUND = "compound"
    CASE = "case"


class CommandBlockType(StrEnum):
    """Name the shape of one top-level command block"""

    COMMAND = "command"
    PIPED_COMMANDS = "piped_commands"
    AND_OR_LIST = "and_or_list"
    BACKGROUND_COMMAND = "background_command"
    MULTILINE_CAT = "multiline_cat"
    IF = "if"
    FOR = "for"
    WHILE = "while"
    UNTIL = "until"
    CASE = "case"
    SELECT = "select"
    FUNCTION = "function"
    SUBSHELL = "subshell"
    BRACE_GROUP = "brace_group"


COMPOUND_KEYWORD_BLOCK_TYPES = {
    "if": CommandBlockType.IF,
    "for": CommandBlockType.FOR,
    "while": CommandBlockType.WHILE,
    "until": CommandBlockType.UNTIL,
    "case": CommandBlockType.CASE,
    "select": CommandBlockType.SELECT,
    "function": CommandBlockType.FUNCTION,
}
OPENING_BRACKET_BLOCK_TYPES = {"(": CommandBlockType.SUBSHELL, "{": CommandBlockType.BRACE_GROUP}


@dataclass(frozen=True)
class CommandBlock:
    """Hold one top-level command and the kind of block it is"""

    block_type: CommandBlockType
    command: str


class ScriptSplitter:
    """Scan a script once and collect its top-level commands"""

    def __init__(self, script: str):
        """Prepare to scan one script

        Args:
            script: The shell script text to split
        """
        self.script = script
        self.position = 0
        self.commands: list[CommandBlock] = []
        self.pending_heredocs: list[tuple[str, bool]] = []
        self.nesting: list[Nesting] = []
        self.pieces: list[str] = []
        self.segment_start = 0
        self.at_word_start = True
        self.at_command_start = True
        self.first_word: str | None = None
        self.opening_bracket: str | None = None
        self.top_level_word_count = 0
        self.saw_top_level_pipe = False
        self.saw_top_level_and_or = False
        self.saw_top_level_heredoc = False
        self.is_function_definition = False
        self.ends_in_background = False

    def split(self) -> list[CommandBlock]:
        """Return every top-level command in the script, in order

        Returns:
            The classified commands with surrounding whitespace removed and comments dropped
        """
        while self.position < len(self.script):
            self._scan_next()
        self._flush_segment()
        self._finish_command()
        return self.commands

    def _scan_next(self) -> None:
        """Consume the next token or character at the current position"""
        character = self.script[self.position]
        if self.script.startswith("\\\n", self.position):
            self._consume_line_continuation()
            return
        if character == "\\":
            self.position += 2
            self.at_word_start = False
            return
        if character == "'":
            self._consume_single_quoted()
            return
        if character == '"':
            self._consume_double_quoted()
            return
        if character == "`":
            self._consume_backticks()
            return
        if character == "#" and self.at_word_start:
            self._consume_comment()
            return
        if character in WHITESPACE_CHARACTERS:
            self.position += 1
            self.at_word_start = True
            return
        if character in "\n;&|":
            self._consume_separator(character)
            return
        if self.script.startswith("<<", self.position) and not self.script.startswith("<<<", self.position):
            self._consume_heredoc_operator()
            return
        if self.script.startswith("<<<", self.position):
            self.position += 3
            self.at_word_start = True
            return
        if character in "<>":
            self.position += 1
            self.at_word_start = True
            return
        if character == "$":
            self._consume_dollar()
            return
        if character in "(){}":
            self._consume_bracket(character)
            return
        self._consume_word()

    def _consume_line_continuation(self) -> None:
        """Remove a backslash-newline, collapsing any whitespace around it to a single space"""
        self._flush_segment()
        stripped_piece = self.pieces[-1].rstrip(" \t")
        had_whitespace_before = stripped_piece != self.pieces[-1]
        self.pieces[-1] = stripped_piece
        self.position += 2
        had_whitespace_after = self.position < len(self.script) and self.script[self.position] in WHITESPACE_CHARACTERS
        while self.position < len(self.script) and self.script[self.position] in WHITESPACE_CHARACTERS:
            self.position += 1
        if had_whitespace_before or had_whitespace_after:
            self.pieces.append(" ")
            self.at_word_start = True
        self.segment_start = self.position

    def _consume_single_quoted(self) -> None:
        """Skip past a single-quoted string"""
        closing_index = self.script.find("'", self.position + 1)
        self.position = len(self.script) if closing_index == -1 else closing_index + 1
        self.at_word_start = False

    def _consume_double_quoted(self) -> None:
        """Skip past a double-quoted string, including any expansions nested inside it"""
        self.position += 1
        while self.position < len(self.script):
            character = self.script[self.position]
            if self.script.startswith("\\\n", self.position):
                self._flush_segment()
                self.position += 2
                self.segment_start = self.position
            elif character == "\\":
                self.position += 2
            elif character == '"':
                self.position += 1
                break
            elif character == "`":
                self._consume_backticks()
            elif self.script.startswith("$(", self.position):
                self.position += 2
                self._skip_balanced("(", ")")
            elif self.script.startswith("${", self.position):
                self.position += 2
                self._skip_balanced("{", "}")
            else:
                self.position += 1
        self.at_word_start = False

    def _consume_backticks(self) -> None:
        """Skip past a backtick command substitution"""
        self.position += 1
        while self.position < len(self.script):
            character = self.script[self.position]
            if character == "\\":
                self.position += 2
            elif character == "`":
                self.position += 1
                break
            else:
                self.position += 1
        self.at_word_start = False

    def _skip_balanced(self, opening: str, closing: str) -> None:
        """Skip past text up to and including the bracket that balances an already consumed opening bracket

        Args:
            opening: The opening bracket character
            closing: The closing bracket character
        """
        depth = 1
        while self.position < len(self.script) and depth > 0:
            character = self.script[self.position]
            if character == "\\":
                self.position += 2
            elif character == "'":
                self._consume_single_quoted()
            elif character == '"':
                self._consume_double_quoted()
            elif character == "`":
                self._consume_backticks()
            else:
                if character == opening:
                    depth += 1
                elif character == closing:
                    depth -= 1
                self.position += 1

    def _consume_comment(self) -> None:
        """Drop a comment running to the end of the line"""
        self._flush_segment()
        newline_index = self.script.find("\n", self.position)
        self.position = len(self.script) if newline_index == -1 else newline_index
        self.segment_start = self.position

    def _consume_heredoc_operator(self) -> None:
        """Record a heredoc whose body starts after the current line"""
        match = HEREDOC_OPERATOR_PATTERN.match(self.script, self.position)
        if match is None:
            self.position += 2
            return
        strip_leading_tabs = match.group(1) == "-"
        delimiter = match.group(2) or match.group(3) or match.group(4).removeprefix("\\")
        self.pending_heredocs.append((delimiter, strip_leading_tabs))
        if not self.nesting:
            self.saw_top_level_heredoc = True
        self.position = match.end()
        self.at_word_start = False

    def _consume_heredoc_bodies(self) -> None:
        """Consume every pending heredoc body, each ending at its own delimiter line"""
        for delimiter, strip_leading_tabs in self.pending_heredocs:
            while self.position < len(self.script):
                newline_index = self.script.find("\n", self.position)
                line_end = len(self.script) if newline_index == -1 else newline_index
                line = self.script[self.position : line_end]
                self.position = min(line_end + 1, len(self.script))
                if (line.lstrip("\t") if strip_leading_tabs else line) == delimiter:
                    break
        self.pending_heredocs.clear()

    def _consume_dollar(self) -> None:
        """Consume a dollar sign, opening a nesting level for command or parameter expansion"""
        if self.script.startswith("$(", self.position):
            self.nesting.append(Nesting.PARENTHESIS)
            self.position += 2
            self.at_command_start = True
        elif self.script.startswith("${", self.position):
            self.nesting.append(Nesting.PARAMETER_EXPANSION)
            self.position += 2
        else:
            self.position += 1
        self.at_word_start = False

    def _consume_bracket(self, character: str) -> None:
        """Consume a bracket, adjusting the nesting stack

        Args:
            character: One of the four bracket characters
        """
        top = self.nesting[-1] if self.nesting else None
        if character == "(":
            if top is None:
                self._record_top_level_parenthesis()
            self.nesting.append(Nesting.PARENTHESIS)
            self.at_command_start = True
        elif character == ")":
            if top == Nesting.PARENTHESIS:
                self.nesting.pop()
                self.at_command_start = False
            elif Nesting.CASE in self.nesting:
                self.at_command_start = True
        elif character == "{":
            opens_group = self.at_word_start or self._previous_character() == ")"
            if opens_group and self._followed_by_whitespace_or_end():
                if top is None and self.top_level_word_count == 0 and self.opening_bracket is None:
                    self.opening_bracket = "{"
                self.nesting.append(Nesting.BRACE_GROUP)
                self.at_command_start = True
        elif character == "}":
            if top == Nesting.PARAMETER_EXPANSION or (top == Nesting.BRACE_GROUP and self.at_word_start):
                self.nesting.pop()
                self.at_command_start = False
        self.position += 1
        self.at_word_start = False

    def _record_top_level_parenthesis(self) -> None:
        """Note whether a top-level opening parenthesis starts a subshell or follows a function name"""
        if self.top_level_word_count == 0 and self.opening_bracket is None:
            self.opening_bracket = "("
        elif self.top_level_word_count == 1 and not (self.saw_top_level_pipe or self.saw_top_level_and_or):
            self.is_function_definition = True

    def _followed_by_whitespace_or_end(self) -> bool:
        """Return whether the character after the current one is whitespace, a newline, or the end of the script

        Returns:
            True when the current character stands alone as its own word
        """
        next_index = self.position + 1
        return next_index >= len(self.script) or self.script[next_index] in " \t\n"

    def _consume_word(self) -> None:
        """Consume a plain word, tracking compound-command keywords when the word begins a command"""
        word_start = self.position
        self.position += 1
        while self.position < len(self.script) and self.script[self.position] not in WORD_BREAK_CHARACTERS:
            self.position += 1
        word = self.script[word_start : self.position]
        if not self.nesting:
            if self.top_level_word_count == 0:
                self.first_word = word
            self.top_level_word_count += 1
        if self.at_command_start and self.at_word_start:
            if word in COMPOUND_OPENING_KEYWORDS:
                self.nesting.append(Nesting.CASE if word == "case" else Nesting.COMPOUND)
            elif (
                word in COMPOUND_CLOSING_KEYWORDS
                and self.nesting
                and self.nesting[-1]
                in (
                    Nesting.COMPOUND,
                    Nesting.CASE,
                )
            ):
                self.nesting.pop()
            self.at_command_start = word in KEYWORDS_FOLLOWED_BY_A_COMMAND
        else:
            self.at_command_start = False
        self.at_word_start = False

    def _consume_separator(self, character: str) -> None:
        """Consume a newline, semicolon, ampersand, or pipe and end the command when appropriate

        Args:
            character: The separator character at the current position
        """
        at_top_level = not self.nesting
        if character == "\n":
            self.position += 1
            if self.pending_heredocs:
                self._flush_segment()
                self._consume_heredoc_bodies()
                self.pieces.append(self.script[self.segment_start : self.position])
                self.segment_start = self.position
            if at_top_level:
                self._flush_segment()
                self._finish_command()
        elif character == ";":
            if self.script.startswith(";;", self.position):
                self.position += 2
            elif at_top_level and not self.pending_heredocs:
                self._flush_segment()
                self.position += 1
                self.segment_start = self.position
                self._finish_command()
            else:
                self.position += 1
        elif character == "&":
            if self.script.startswith("&&", self.position):
                self.position += 2
                self.saw_top_level_and_or = self.saw_top_level_and_or or at_top_level
            elif self.script.startswith("&>", self.position):
                self.position += 2
            elif self._previous_character() in REDIRECTION_CHARACTERS:
                self.position += 1
            else:
                self.position += 1
                if at_top_level and not self.pending_heredocs:
                    self.ends_in_background = True
                    self._flush_segment()
                    self._finish_command()
        elif character == "|":
            if self.script.startswith("||", self.position):
                self.position += 2
                self.saw_top_level_and_or = self.saw_top_level_and_or or at_top_level
            else:
                self.position += 2 if self.script.startswith("|&", self.position) else 1
                self.saw_top_level_pipe = self.saw_top_level_pipe or at_top_level
        self.at_word_start = True
        self.at_command_start = True

    def _previous_character(self) -> str:
        """Return the character before the current position, or an empty string at the start

        Returns:
            One character, or an empty string
        """
        return self.script[self.position - 1] if self.position > 0 else ""

    def _flush_segment(self) -> None:
        """Move the text scanned since the last flush into the current command"""
        self.pieces.append(self.script[self.segment_start : self.position])
        self.segment_start = self.position

    def _finish_command(self) -> None:
        """Store the current command if it holds anything and start a new one"""
        command = "".join(self.pieces).strip()
        if command:
            self.commands.append(CommandBlock(block_type=self._classify(), command=command))
        self.pieces = []
        self.at_word_start = True
        self.at_command_start = True
        self.first_word = None
        self.opening_bracket = None
        self.top_level_word_count = 0
        self.saw_top_level_pipe = False
        self.saw_top_level_and_or = False
        self.saw_top_level_heredoc = False
        self.is_function_definition = False
        self.ends_in_background = False

    def _classify(self) -> CommandBlockType:
        """Return the block type of the command being finished, from what was seen at its top level

        Returns:
            A background ampersand first, then a list operator, then the opening keyword or bracket, then a
            heredoc, otherwise a plain command
        """
        if self.ends_in_background:
            return CommandBlockType.BACKGROUND_COMMAND
        if self.saw_top_level_and_or:
            return CommandBlockType.AND_OR_LIST
        if self.saw_top_level_pipe:
            return CommandBlockType.PIPED_COMMANDS
        if self.first_word in COMPOUND_KEYWORD_BLOCK_TYPES:
            return COMPOUND_KEYWORD_BLOCK_TYPES[self.first_word]
        if self.is_function_definition:
            return CommandBlockType.FUNCTION
        if self.opening_bracket in OPENING_BRACKET_BLOCK_TYPES:
            return OPENING_BRACKET_BLOCK_TYPES[self.opening_bracket]
        if self.saw_top_level_heredoc:
            return CommandBlockType.MULTILINE_CAT
        return CommandBlockType.COMMAND


def split_script_into_connected_commands(script: str) -> list[CommandBlock]:
    """Return the top-level commands of a script, each classified by the kind of block it is

    A command runs until an unquoted newline, semicolon, or background ampersand at the top level. Pipelines and
    lists joined by ``|``, ``&&``, or ``||`` stay together, as do ``$( )``, backtick, ``( )``, and ``{ }`` groups,
    ``if``/``for``/``while``/``until``/``case``/``select`` blocks, and heredoc bodies. Comments are dropped. A
    background ampersand stays attached to its command

    Args:
        script: The shell script text to split

    Returns:
        The command blocks in script order, each holding its type and its text with surrounding whitespace removed
    """
    return ScriptSplitter(script).split()
