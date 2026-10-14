"""Turn one classified command block into a tree of plan nodes"""

# Standard libraries
import re

# Project libraries
from bash_purepython.parse_script import (
    REDIRECTION_CHARACTERS,
    CommandBlock,
    CommandBlockType,
    ScriptSplitter,
    split_script_into_connected_commands,
)
from bash_purepython.shell_state import ShellSyntaxError, UnsupportedBlockError
from bash_purepython.words import tokenize_simple_command
from bash_purepython.workflow import (
    AndOrListNode,
    BackgroundNode,
    BraceGroupNode,
    CaseClause,
    CaseNode,
    CaseTerminator,
    ForNode,
    FunctionDefinitionNode,
    IfNode,
    ListOperator,
    PipelineNode,
    PlanNode,
    Redirection,
    SelectNode,
    SimpleCommandNode,
    SubshellNode,
    UntilNode,
    WhileNode,
)

PIPE_OPERATOR = "|"
PIPE_WITH_STDERR_OPERATOR = "|&"
LIST_OPERATORS_LONGEST_FIRST = ("&&", "||", "|&", "|")
NEGATION_PATTERN = re.compile(r"^!(?:\s+|$)")
SECTION_KEYWORD_PATTERN = re.compile(r"^(then|elif|else|fi|do|done)(?:\s+|$)", re.DOTALL)
FOR_HEADER_PATTERN = re.compile(r"^for\s+([A-Za-z_]\w*)(\s+in\b([^;\n]*))?\s*[;\n]?\s*(?=do\b)", re.DOTALL)
FOR_ARITHMETIC_PATTERN = re.compile(r"^for\s*\(\((.*?)\)\)\s*;?\s*(?=do\b)", re.DOTALL)
SELECT_HEADER_PATTERN = re.compile(r"^select\s+([A-Za-z_]\w*)(\s+in\b([^;\n]*))?\s*[;\n]?\s*(?=do\b)", re.DOTALL)
CASE_HEADER_PATTERN = re.compile(r"^case\s+(.+?)\s+in(?=\s)", re.DOTALL)
CASE_CLOSING_KEYWORD = "esac"
CASE_OPENING_KEYWORD = "case"
COMMAND_PREFIX_WORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "time"})
CASE_TERMINATORS_LONGEST_FIRST = (CaseTerminator.CONTINUE_MATCHING, CaseTerminator.FALL_THROUGH, CaseTerminator.STOP)
ARITHMETIC_FOR_PART_COUNT = 3
FUNCTION_PATTERN = re.compile(r"^(?:function\s+)?([A-Za-z_][\w-]*)\s*(?:\(\s*\))?\s*([({].*[)}])$", re.DOTALL)
SIMPLE_COMMAND_BLOCK_TYPES = frozenset(
    {
        CommandBlockType.COMMAND,
        CommandBlockType.MULTILINE_CAT,
        CommandBlockType.PIPED_COMMANDS,
        CommandBlockType.AND_OR_LIST,
    }
)


class OperatorSplitter(ScriptSplitter):
    """Split one block at its top-level pipe and list operators, keeping heredoc bodies with their command"""

    def __init__(self, text: str):
        """Prepare to scan one block

        Args:
            text: The text of a pipeline or and/or list block
        """
        super().__init__(text)
        self.operators: list[str] = []
        self.heredoc_bodies: list[tuple[int, str]] = []
        self.heredoc_owner_index: int | None = None
        self.group_close_positions: list[int] = []

    def split_at_operators(self) -> tuple[list[str], list[str]]:
        """Return the segments between operators and the operators that separated them

        Raises:
            ShellSyntaxError: If an operator has nothing on one side of it

        Returns:
            The segment texts in order, and one operator fewer
        """
        texts = [block.command for block in self.split()]
        for owner_index, body in self.heredoc_bodies:
            if owner_index >= len(texts):
                raise ShellSyntaxError(f"heredoc body without a command: {self.script}")
            texts[owner_index] = f"{texts[owner_index]}\n{body}"
        if len(texts) != len(self.operators) + 1:
            raise ShellSyntaxError(f"operator with a missing operand: {self.script}")
        return texts, self.operators

    def _consume_separator(self, character: str) -> None:
        """End the current segment at a top-level pipe or list operator, otherwise defer to the base scanner

        Args:
            character: The separator character at the current position
        """
        if character == "\n" and self.pending_heredocs and not self.nesting:
            self._consume_heredoc_line()
            return
        if character in "&|" and not self.nesting and self._previous_character() not in REDIRECTION_CHARACTERS:
            for operator in LIST_OPERATORS_LONGEST_FIRST:
                if self.script.startswith(operator, self.position):
                    self._flush_segment()
                    self.position += len(operator)
                    self.segment_start = self.position
                    self._finish_command()
                    self.operators.append(operator)
                    return
        super()._consume_separator(character)

    def _consume_heredoc_operator(self) -> None:
        """Remember which segment a top-level heredoc belongs to, then defer to the base scanner"""
        if self.heredoc_owner_index is None and not self.nesting:
            self.heredoc_owner_index = len(self.commands)
        super()._consume_heredoc_operator()

    def _consume_heredoc_line(self) -> None:
        """Consume the newline that starts pending heredoc bodies and store the bodies against their command"""
        self._flush_segment()
        self.position += 1
        owner_index = self.heredoc_owner_index if self.heredoc_owner_index is not None else len(self.commands)
        self.heredoc_owner_index = None
        body_start = self.position
        self._consume_heredoc_bodies()
        body = self.script[body_start : self.position].rstrip("\n")
        self.segment_start = self.position
        self.heredoc_bodies.append((owner_index, body))
        self.at_word_start = True
        self.at_command_start = True

    def _consume_bracket(self, character: str) -> None:
        """Track where a top-level group closes, then defer to the base scanner

        Args:
            character: One of the four bracket characters
        """
        closes_top_level_group = character in ")}" and len(self.nesting) == 1
        super()._consume_bracket(character)
        if closes_top_level_group and not self.nesting:
            self.group_close_positions.append(self.position - 1)


def split_at_operators(text: str) -> tuple[list[str], list[str]]:
    """Return the top-level segments of a block and the operators between them

    Args:
        text: The text of a pipeline or and/or list block

    Returns:
        The segment texts in order, and one operator fewer
    """
    return OperatorSplitter(text).split_at_operators()


def find_group_close(text: str) -> int:
    """Return the index of the bracket that closes the group the text opens with

    Args:
        text: Text starting with ``(`` or ``{``

    Raises:
        ShellSyntaxError: If the group never closes

    Returns:
        The index of the closing bracket
    """
    splitter = OperatorSplitter(text)
    splitter.split()
    if not splitter.group_close_positions:
        raise ShellSyntaxError(f"unclosed group: {text}")
    return splitter.group_close_positions[0]


def parse_pipeline(text: str) -> PlanNode:
    """Return the node for text holding only pipes, with any leading negation

    Args:
        text: A pipeline or a single command

    Returns:
        A pipeline node, or a simple command node when there is no pipe
    """
    negated = NEGATION_PATTERN.match(text) is not None
    if negated:
        text = NEGATION_PATTERN.sub("", text, count=1)
    segments, operators = split_at_operators(text)
    stages = [parse_pipeline_stage(segment) for segment in segments]
    if len(stages) == 1 and not negated:
        return stages[0]
    merge_stderr = [operator == PIPE_WITH_STDERR_OPERATOR for operator in operators]
    return PipelineNode(stages=stages, merge_stderr=merge_stderr, negated=negated)


def parse_pipeline_stage(text: str) -> PlanNode:
    """Return the node for one stage of a pipeline, which may itself be a group or compound command

    Args:
        text: The text of one stage

    Returns:
        The node for the stage
    """
    blocks = split_script_into_connected_commands(text)
    if len(blocks) != 1:
        raise ShellSyntaxError(f"expected one command: {text}")
    block = blocks[0]
    if block.block_type in SIMPLE_COMMAND_BLOCK_TYPES:
        return SimpleCommandNode(text=block.command)
    return build_plan(block)


def parse_and_or_list(text: str) -> PlanNode:
    """Return the node for pipelines joined by && and ||

    Args:
        text: The text of an and/or list block

    Returns:
        An and/or list node
    """
    segments, operators = split_at_operators(text)
    items: list[str] = [segments[0]]
    list_operators: list[ListOperator] = []
    for segment, operator in zip(segments[1:], operators, strict=True):
        if operator in (PIPE_OPERATOR, PIPE_WITH_STDERR_OPERATOR):
            items[-1] = f"{items[-1]} {operator} {segment}"
        else:
            items.append(segment)
            list_operators.append(ListOperator(operator))
    first = parse_pipeline(items[0])
    rest = [(operator, parse_pipeline(item)) for operator, item in zip(list_operators, items[1:], strict=True)]
    return AndOrListNode(first=first, rest=rest)


def parse_trailing_redirections(text: str) -> list[Redirection]:
    """Return the redirections written after a group or compound command

    Args:
        text: The text after the closing bracket or keyword

    Raises:
        ShellSyntaxError: If the text holds anything but redirections

    Returns:
        The redirections, possibly empty
    """
    if not text.strip():
        return []
    words, redirections, assignments = tokenize_simple_command(text)
    if words or assignments:
        raise ShellSyntaxError(f"unexpected text after command: {text}")
    return redirections


def arithmetic_command_expression(inside: str) -> str | None:
    """Return the expression of a ``(( ))`` command, given the text inside its outer parentheses

    Args:
        inside: Everything between the outer parentheses, whitespace included

    Returns:
        The text between the inner parentheses when they touch the outer ones, otherwise None
    """
    if not inside.startswith("(") or not inside.endswith(")"):
        return None
    try:
        inner_close = find_group_close(inside)
    except ShellSyntaxError:
        return None
    return inside[1:-1] if inner_close == len(inside) - 1 else None


def parse_group(text: str, block_type: CommandBlockType) -> PlanNode:
    """Return the node for a subshell or brace group with its trailing redirections

    Args:
        text: The block text, starting with the opening bracket
        block_type: Whether the group is a subshell or a brace group

    Returns:
        A subshell or brace group node
    """
    close_index = find_group_close(text)
    inside = text[1:close_index]
    body = inside.strip()
    redirections = parse_trailing_redirections(text[close_index + 1 :])
    if block_type == CommandBlockType.SUBSHELL:
        return SubshellNode(
            body=body, redirections=redirections, arithmetic_expression=arithmetic_command_expression(inside)
        )
    return BraceGroupNode(body=body, redirections=redirections)


def split_into_sections(text: str, opening_keyword: str) -> list[tuple[str, str]]:
    """Return the keyword-delimited sections of a compound command

    The opening keyword is removed, the remainder is split into commands, and every command starting with a
    section keyword starts a new section. Commands are joined back with newlines inside each section

    Args:
        text: The whole compound command
        opening_keyword: The keyword the text starts with

    Raises:
        ShellSyntaxError: If the text does not start with the keyword

    Returns:
        Pairs of section keyword and section text, the first keyword being the opening one
    """
    if not re.match(rf"^{opening_keyword}(?:\s|$)", text):
        raise ShellSyntaxError(f"expected {opening_keyword}: {text}")
    sections: list[tuple[str, list[str]]] = [(opening_keyword, [])]
    for block in split_script_into_connected_commands(text[len(opening_keyword) :]):
        match = SECTION_KEYWORD_PATTERN.match(block.command)
        command = block.command
        if match is not None:
            sections.append((match.group(1), []))
            command = command[match.end() :]
        if command.strip():
            sections[-1][1].append(command)
    return [(keyword, "\n".join(commands)) for keyword, commands in sections]


def parse_if(text: str) -> IfNode:
    """Return the node for an if statement

    Args:
        text: The whole if block

    Raises:
        ShellSyntaxError: If a section is missing or out of order

    Returns:
        An if node with every branch
    """
    sections = split_into_sections(text, "if")
    branches: list[tuple[str, str]] = []
    else_body: str | None = None
    pending_condition: str | None = None
    redirections: list[Redirection] = []
    for keyword, section_text in sections:
        if keyword in ("if", "elif"):
            pending_condition = section_text
        elif keyword == "then":
            if pending_condition is None:
                raise ShellSyntaxError(f"then without a condition: {text}")
            branches.append((pending_condition, section_text))
            pending_condition = None
        elif keyword == "else":
            else_body = section_text
        elif keyword == "fi":
            redirections = parse_trailing_redirections(section_text)
        else:
            raise ShellSyntaxError(f"unexpected {keyword} in if: {text}")
    if not branches:
        raise ShellSyntaxError(f"if without then: {text}")
    return IfNode(branches=branches, else_body=else_body, redirections=redirections)


def parse_loop_sections(text: str, opening_keyword: str) -> tuple[str, str, list[Redirection]]:
    """Return the header, body and trailing redirections of a for, while, or until loop

    Args:
        text: The whole loop block
        opening_keyword: ``for``, ``while``, or ``until``

    Raises:
        ShellSyntaxError: If do or done is missing

    Returns:
        The header text, the body text, and the redirections written after done
    """
    sections = dict(split_into_sections(text, opening_keyword))
    if "do" not in sections or "done" not in sections:
        raise ShellSyntaxError(f"loop without do and done: {text}")
    return sections[opening_keyword], sections["do"], parse_trailing_redirections(sections["done"])


def parse_for(text: str) -> ForNode:
    """Return the node for a for loop, over words or in the arithmetic ``for (( ; ; ))`` form

    Args:
        text: The whole for block

    Raises:
        ShellSyntaxError: If the header is neither ``name in words`` nor three arithmetic expressions

    Returns:
        A for node
    """
    arithmetic_match = FOR_ARITHMETIC_PATTERN.match(text)
    if arithmetic_match is not None:
        parts = arithmetic_match.group(1).split(";")
        if len(parts) != ARITHMETIC_FOR_PART_COUNT:
            raise ShellSyntaxError(f"bad for header: {text}")
        sections = dict(split_into_sections(text[arithmetic_match.end() :].lstrip(), "do"))
        if "done" not in sections:
            raise ShellSyntaxError(f"loop without done: {text}")
        initial, condition, step = (part.strip() for part in parts)
        return ForNode(
            variable="",
            words_text=None,
            body=sections["do"],
            redirections=parse_trailing_redirections(sections["done"]),
            arithmetic=(initial, condition, step),
        )
    match = FOR_HEADER_PATTERN.match(text)
    if match is None:
        raise ShellSyntaxError(f"bad for header: {text}")
    words_text = None if match.group(2) is None else (match.group(3) or "").strip()
    sections = dict(split_into_sections(text[match.end() :].lstrip(), "do"))
    if "done" not in sections:
        raise ShellSyntaxError(f"loop without done: {text}")
    redirections = parse_trailing_redirections(sections["done"])
    return ForNode(variable=match.group(1), words_text=words_text, body=sections["do"], redirections=redirections)


def parse_select(text: str) -> SelectNode:
    """Return the node for a select loop

    Args:
        text: The whole select block

    Raises:
        ShellSyntaxError: If the header is not ``name`` or ``name in words`` followed by ``do``

    Returns:
        A select node
    """
    match = SELECT_HEADER_PATTERN.match(text)
    if match is None:
        raise ShellSyntaxError(f"bad select header: {text}")
    words_text = None if match.group(2) is None else (match.group(3) or "").strip()
    sections = dict(split_into_sections(text[match.end() :].lstrip(), "do"))
    if "done" not in sections:
        raise ShellSyntaxError(f"loop without done: {text}")
    redirections = parse_trailing_redirections(sections["done"])
    return SelectNode(variable=match.group(1), words_text=words_text, body=sections["do"], redirections=redirections)


class CaseClauseScanner:
    """Walk the text after ``case WORD in`` and cut it into clauses"""

    def __init__(self, text: str):
        """Prepare to scan the clauses

        Args:
            text: Everything after the ``in`` keyword, including the closing ``esac``
        """
        self.text = text
        self.position = 0
        self.clauses: list[CaseClause] = []
        self.trailing = ""

    def scan(self) -> tuple[list[CaseClause], str]:
        """Return the clauses and the text after ``esac``

        Raises:
            ShellSyntaxError: If a clause is malformed or ``esac`` is missing

        Returns:
            The clauses in order and whatever follows the closing keyword
        """
        while True:
            self._skip_blank()
            if self.position >= len(self.text):
                raise ShellSyntaxError(f"case without esac: {self.text}")
            if self._at_keyword(CASE_CLOSING_KEYWORD):
                self.trailing = self.text[self.position + len(CASE_CLOSING_KEYWORD) :]
                return self.clauses, self.trailing
            if self.text[self.position] == "(":
                self.position += 1
            patterns_text = self._read_patterns()
            body, terminator = self._read_body()
            self.clauses.append(CaseClause(patterns_text=patterns_text, body=body, terminator=terminator))

    def _skip_blank(self) -> None:
        """Skip whitespace, newlines and comments"""
        while self.position < len(self.text):
            character = self.text[self.position]
            if character in " \t\n":
                self.position += 1
            elif character == "#":
                newline = self.text.find("\n", self.position)
                self.position = len(self.text) if newline == -1 else newline
            else:
                return

    def _at_keyword(self, keyword: str) -> bool:
        """Return whether the keyword stands as a whole word at the current position

        Args:
            keyword: The word to look for

        Returns:
            True when it is there and not part of a longer word
        """
        end = self.position + len(keyword)
        return self.text.startswith(keyword, self.position) and (end >= len(self.text) or self.text[end] in " \t\n;&|)")

    def _read_patterns(self) -> str:
        """Return the pattern list up to the parenthesis that closes it

        Raises:
            ShellSyntaxError: If no closing parenthesis follows

        Returns:
            The raw pattern text
        """
        start = self.position
        while self.position < len(self.text):
            character = self.text[self.position]
            if character == ")":
                patterns_text = self.text[start : self.position].strip()
                self.position += 1
                return patterns_text
            self._skip_quoted_or_nested()
        raise ShellSyntaxError(f"case pattern without a closing parenthesis: {self.text}")

    def _read_body(self) -> tuple[str, CaseTerminator]:
        """Return the clause body and the terminator that ended it

        Returns:
            The body text and ``;;``, ``;&`` or ``;;&``, the first when ``esac`` ended the last clause
        """
        start = self.position
        case_depth = 0
        while self.position < len(self.text):
            character = self.text[self.position]
            if case_depth == 0:
                for terminator in CASE_TERMINATORS_LONGEST_FIRST:
                    if self.text.startswith(terminator.value, self.position):
                        body = self.text[start : self.position].strip()
                        self.position += len(terminator.value)
                        return body, terminator
                if self._at_keyword(CASE_CLOSING_KEYWORD) and self._at_word_start():
                    return self.text[start : self.position].strip(), CaseTerminator.STOP
            if self._at_keyword(CASE_OPENING_KEYWORD) and self._at_command_start():
                case_depth += 1
                self.position += len(CASE_OPENING_KEYWORD)
                continue
            if case_depth > 0 and self._at_keyword(CASE_CLOSING_KEYWORD) and self._at_word_start():
                case_depth -= 1
                self.position += len(CASE_CLOSING_KEYWORD)
                continue
            if character == "#" and self._at_word_start():
                newline = self.text.find("\n", self.position)
                self.position = len(self.text) if newline == -1 else newline
                continue
            self._skip_quoted_or_nested()
        return self.text[start:].strip(), CaseTerminator.STOP

    def _at_word_start(self) -> bool:
        """Return whether the current position begins a word"""
        return self.position == 0 or self.text[self.position - 1] in " \t\n;&|(){}"

    def _at_command_start(self) -> bool:
        """Return whether the current position begins a command rather than an argument of one"""
        if not self._at_word_start():
            return False
        index = self.position
        while index > 0 and self.text[index - 1] in " \t":
            index -= 1
        if index == 0 or self.text[index - 1] in "\n;&|(){":
            return True
        word_end = index
        while index > 0 and self.text[index - 1] not in " \t\n;&|(){}":
            index -= 1
        return self.text[index:word_end] in COMMAND_PREFIX_WORDS

    def _skip_quoted_or_nested(self) -> None:
        """Advance past one character, or past a whole quoted string or bracketed expansion"""
        character = self.text[self.position]
        if character == "\\":
            self.position += 2
        elif character == "'":
            closing = self.text.find("'", self.position + 1)
            self.position = len(self.text) if closing == -1 else closing + 1
        elif character == '"':
            self.position += 1
            while self.position < len(self.text) and self.text[self.position] != '"':
                self.position += 2 if self.text[self.position] == "\\" else 1
            self.position += 1
        elif character == "`":
            closing = self.text.find("`", self.position + 1)
            self.position = len(self.text) if closing == -1 else closing + 1
        elif self.text.startswith("$(", self.position):
            self.position = find_group_close(self.text[self.position + 1 :]) + self.position + 2
        elif self.text.startswith("${", self.position):
            closing = self.text.find("}", self.position)
            self.position = len(self.text) if closing == -1 else closing + 1
        else:
            self.position += 1


def parse_case(text: str) -> CaseNode:
    """Return the node for a case statement

    Args:
        text: The whole case block

    Raises:
        ShellSyntaxError: If the header is not ``case WORD in`` or a clause is malformed

    Returns:
        A case node
    """
    match = CASE_HEADER_PATTERN.match(text)
    if match is None:
        raise ShellSyntaxError(f"bad case header: {text}")
    clauses, trailing = CaseClauseScanner(text[match.end() :]).scan()
    return CaseNode(word_text=match.group(1), clauses=clauses, redirections=parse_trailing_redirections(trailing))


def parse_function(text: str) -> FunctionDefinitionNode:
    """Return the node for a function definition

    Args:
        text: The whole function block

    Raises:
        ShellSyntaxError: If the text is not ``name() group`` or ``function name group``

    Returns:
        A function definition node whose body is the group text itself
    """
    match = FUNCTION_PATTERN.match(text.strip())
    if match is None:
        raise ShellSyntaxError(f"bad function definition: {text}")
    return FunctionDefinitionNode(name=match.group(1), body=match.group(2))


def build_plan(block: CommandBlock) -> PlanNode:
    """Return the plan node tree for one command block

    Args:
        block: A classified top-level command

    Raises:
        UnsupportedBlockError: If the block type is not handled yet

    Returns:
        The root node of the plan
    """
    block_type = block.block_type
    text = block.command
    if block_type in (CommandBlockType.COMMAND, CommandBlockType.MULTILINE_CAT, CommandBlockType.PIPED_COMMANDS):
        return parse_pipeline(text)
    if block_type == CommandBlockType.AND_OR_LIST:
        return parse_and_or_list(text)
    if block_type == CommandBlockType.BACKGROUND_COMMAND:
        inner_text = text.removesuffix("&").strip()
        inner_blocks = split_script_into_connected_commands(inner_text)
        if len(inner_blocks) != 1:
            raise ShellSyntaxError(f"expected one command before &: {text}")
        return BackgroundNode(inner=build_plan(inner_blocks[0]), command_text=inner_text)
    if block_type in (CommandBlockType.SUBSHELL, CommandBlockType.BRACE_GROUP):
        return parse_group(text, block_type)
    if block_type == CommandBlockType.IF:
        return parse_if(text)
    if block_type == CommandBlockType.FOR:
        return parse_for(text)
    if block_type == CommandBlockType.SELECT:
        return parse_select(text)
    if block_type == CommandBlockType.CASE:
        return parse_case(text)
    if block_type == CommandBlockType.WHILE:
        condition, body, redirections = parse_loop_sections(text, "while")
        return WhileNode(condition=condition, body=body, redirections=redirections)
    if block_type == CommandBlockType.UNTIL:
        condition, body, redirections = parse_loop_sections(text, "until")
        return UntilNode(condition=condition, body=body, redirections=redirections)
    if block_type == CommandBlockType.FUNCTION:
        return parse_function(text)
    raise UnsupportedBlockError(text)
