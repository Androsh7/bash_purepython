"""Define the plan nodes one command block is turned into before it runs"""

# Standard libraries
from dataclasses import dataclass, field
from enum import StrEnum


class ListOperator(StrEnum):
    """Name the operators that join items of an and/or list"""

    AND = "&&"
    OR = "||"


class RedirectionKind(StrEnum):
    """Name the redirections the executor honours"""

    WRITE_STDOUT = ">"
    APPEND_STDOUT = ">>"
    READ_STDIN = "<"
    WRITE_STDERR = "2>"
    APPEND_STDERR = "2>>"
    STDERR_TO_STDOUT = "2>&1"
    STDOUT_TO_STDERR = ">&2"
    WRITE_BOTH = "&>"
    HEREDOC = "<<"
    HERE_STRING = "<<<"


@dataclass(frozen=True)
class Redirection:
    """Hold one redirection with its unexpanded target or body"""

    kind: RedirectionKind
    target: str
    expand_target: bool = True


@dataclass(frozen=True)
class SimpleCommandNode:
    """Hold one simple command whose words are expanded when it runs"""

    text: str


@dataclass(frozen=True)
class PipelineNode:
    """Hold commands joined by pipes, in order"""

    stages: list["PlanNode"]
    merge_stderr: list[bool] = field(default_factory=list)
    negated: bool = False


@dataclass(frozen=True)
class AndOrListNode:
    """Hold pipelines joined by && and ||"""

    first: "PlanNode"
    rest: list[tuple[ListOperator, "PlanNode"]]


@dataclass(frozen=True)
class BackgroundNode:
    """Hold a command that was followed by a background ampersand"""

    inner: "PlanNode"
    command_text: str


@dataclass(frozen=True)
class SubshellNode:
    """Hold a parenthesised script that runs against a copy of the state

    Written as ``(( expression ))``, with nothing between each pair of parentheses, it is an arithmetic
    command instead, and ``arithmetic_expression`` holds the text between them
    """

    body: str
    redirections: list[Redirection] = field(default_factory=list)
    arithmetic_expression: str | None = None


@dataclass(frozen=True)
class BraceGroupNode:
    """Hold a braced script that runs against the live state"""

    body: str
    redirections: list[Redirection] = field(default_factory=list)


@dataclass(frozen=True)
class IfNode:
    """Hold the condition and body of every branch of an if statement"""

    branches: list[tuple[str, str]]
    else_body: str | None = None
    redirections: list[Redirection] = field(default_factory=list)


class CaseTerminator(StrEnum):
    """Name what happens after a case clause body runs"""

    STOP = ";;"
    FALL_THROUGH = ";&"
    CONTINUE_MATCHING = ";;&"


@dataclass(frozen=True)
class CaseClause:
    """Hold one ``pattern) body ;;`` clause of a case statement"""

    patterns_text: str
    body: str
    terminator: CaseTerminator


@dataclass(frozen=True)
class CaseNode:
    """Hold a case statement: the word it tests and its clauses in order"""

    word_text: str
    clauses: list[CaseClause]
    redirections: list[Redirection] = field(default_factory=list)


@dataclass(frozen=True)
class ForNode:
    """Hold a for loop over a list of words, or an arithmetic loop when ``arithmetic`` is set"""

    variable: str
    words_text: str | None
    body: str
    redirections: list[Redirection] = field(default_factory=list)
    arithmetic: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class SelectNode:
    """Hold a select loop that offers a numbered menu of words and binds the chosen one"""

    variable: str
    words_text: str | None
    body: str
    redirections: list[Redirection] = field(default_factory=list)


@dataclass(frozen=True)
class WhileNode:
    """Hold a loop that runs while its condition succeeds"""

    condition: str
    body: str
    redirections: list[Redirection] = field(default_factory=list)


@dataclass(frozen=True)
class UntilNode:
    """Hold a loop that runs until its condition succeeds"""

    condition: str
    body: str
    redirections: list[Redirection] = field(default_factory=list)


@dataclass(frozen=True)
class FunctionDefinitionNode:
    """Hold a function name and its body text"""

    name: str
    body: str


PlanNode = (
    SimpleCommandNode
    | PipelineNode
    | AndOrListNode
    | BackgroundNode
    | SubshellNode
    | BraceGroupNode
    | IfNode
    | CaseNode
    | ForNode
    | SelectNode
    | WhileNode
    | UntilNode
    | FunctionDefinitionNode
)
