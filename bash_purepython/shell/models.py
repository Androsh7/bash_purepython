"""Define the data types, enums, constants and exceptions shared by the shell modules"""

# Standard libraries
from dataclasses import dataclass
from enum import StrEnum

OUTPUT_LIMIT_BYTES = 256 << 20
HISTORY_LIMIT_ENTRIES = 500
DEFAULT_TERMINAL_COLUMNS = 80
REPL_INDENT_WIDTH_SPACES = 4
EXIT_CODE_SUCCESS = 0
EXIT_CODE_FAILURE = 1
EXIT_CODE_SYNTAX_ERROR = 2
EXIT_CODE_COMMAND_NOT_FOUND = 127
EXIT_CODE_INTERRUPTED = 130


class TokenKind(StrEnum):
    """Name the kinds of token the tokenizer produces"""

    WORD = "word"
    PIPE = "|"
    AND = "&&"
    OR = "||"
    SEMICOLON = ";"
    REDIRECT_WRITE = ">"
    REDIRECT_APPEND = ">>"
    REDIRECT_STDERR_WRITE = "2>"
    REDIRECT_STDERR_APPEND = "2>>"
    REDIRECT_STDERR_TO_STDOUT = "2>&1"
    REDIRECT_BOTH = "&>"
    REDIRECT_INPUT = "<"


class ChainOperator(StrEnum):
    """Name the operators that join pipelines"""

    AND = "&&"
    OR = "||"
    SEMICOLON = ";"


class CommandKind(StrEnum):
    """Name where a command comes from"""

    BUILTIN = "shell builtin"
    PACKAGE = "bash_purepython command"
    HOST = "host command (browser)"


class WordPosition(StrEnum):
    """Name the role of the word under the cursor"""

    COMMAND = "command"
    ARGUMENT = "argument"
    REDIRECT_TARGET = "redirect_target"


class QuoteStyle(StrEnum):
    """Name the quote a word was opened with"""

    NONE = ""
    SINGLE = "'"
    DOUBLE = '"'


class ReplStatus(StrEnum):
    """Name what the REPL did with a line"""

    DONE = "done"
    MORE = "more"
    ERROR = "error"
    EXIT = "exit"


class ShellError(Exception):
    """Signal a failure raised by the shell itself rather than by a command"""


class ShellSyntaxError(ShellError):
    """Signal a line that cannot be tokenized or parsed"""


class CommandNotFoundError(ShellError):
    """Signal a command name the shell does not know"""

    def __init__(self, name: str):
        """Record the unknown command name

        Args:
            name: The command name that was not found
        """
        super().__init__(f"{name}: command not found")
        self.name = name


class HostCommandPlacementError(ShellError):
    """Signal a host command used anywhere but as the whole line"""

    def __init__(self, name: str):
        """Record the misplaced host command name

        Args:
            name: The host command that appeared inside a pipeline or list
        """
        super().__init__(f"{name}: host commands cannot be used in a pipeline or command list")
        self.name = name


class OutputLimitExceededError(BrokenPipeError):
    """Signal that a command wrote more than the capture allows"""


@dataclass(frozen=True, slots=True)
class WordPart:
    """Hold a run of a word's text and whether quoting protects it from expansion"""

    text: str
    quoted: bool


@dataclass(frozen=True, slots=True)
class RawWord:
    """Hold a word before expansion, as the runs the tokenizer split it into"""

    parts: tuple[WordPart, ...]
    bare_tilde: bool


@dataclass(frozen=True, slots=True)
class Token:
    """Hold one word or operator from a command line"""

    kind: TokenKind
    value: str
    word: RawWord | None = None


@dataclass(frozen=True, slots=True)
class RawRedirects:
    """Hold where a command's streams go, before the targets are expanded"""

    stdout_target: RawWord | None = None
    stdout_append: bool = False
    stderr_target: RawWord | None = None
    stderr_append: bool = False
    stderr_to_stdout: bool = False
    stdin_source: RawWord | None = None


@dataclass(frozen=True, slots=True)
class RawCommand:
    """Hold one command before expansion, its words and its redirects"""

    words: tuple[RawWord, ...]
    redirects: RawRedirects

    def __post_init__(self):
        """Reject a command without words

        Raises:
            ValueError: If there are no words
        """
        if not self.words:
            raise ValueError("a command needs at least one word")


@dataclass(frozen=True, slots=True)
class RawPipeline:
    """Hold the unexpanded commands joined by pipes"""

    commands: tuple[RawCommand, ...]

    def __post_init__(self):
        """Reject an empty pipeline

        Raises:
            ValueError: If there are no commands
        """
        if not self.commands:
            raise ValueError("a pipeline needs at least one command")


@dataclass(frozen=True, slots=True)
class Redirect:
    """Hold the target of a > or >> redirect"""

    target: str
    append: bool


@dataclass(frozen=True, slots=True)
class SimpleCommand:
    """Hold one command, its arguments and its redirects

    redirect is where stdout goes; stderr_redirect is where stderr goes unless
    stderr_to_stdout joins it to stdout; stdin_path is a file read as input
    """

    argv: tuple[str, ...]
    redirect: Redirect | None = None
    stderr_redirect: Redirect | None = None
    stderr_to_stdout: bool = False
    stdin_path: str | None = None

    def __post_init__(self):
        """Reject a command without a name

        Raises:
            ValueError: If argv is empty
        """
        if not self.argv:
            raise ValueError("a command needs at least a name")

    @property
    def name(self) -> str:
        """Return the command name"""
        return self.argv[0]


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Hold the commands joined by pipes, or nothing for a command that expanded to no words"""

    commands: tuple[SimpleCommand, ...]


@dataclass(frozen=True, slots=True)
class CommandList:
    """Hold the unexpanded pipelines of a line and the operators between them"""

    pipelines: tuple[RawPipeline, ...]
    operators: tuple[ChainOperator, ...]

    def __post_init__(self):
        """Reject a list whose operators do not join its pipelines

        Raises:
            ValueError: If there is not exactly one operator between each pair of pipelines
        """
        if not self.pipelines:
            raise ValueError("a command list needs at least one pipeline")
        if len(self.operators) != len(self.pipelines) - 1:
            raise ValueError("a command list needs one operator between each pair of pipelines")


@dataclass(frozen=True, slots=True)
class HostCommand:
    """Describe a command the embedding host runs itself"""

    name: str
    summary: str


@dataclass(frozen=True, slots=True)
class HostCall:
    """Ask the host to run one of its commands"""

    name: str
    argv: tuple[str, ...]
    redirect: Redirect | None


@dataclass(frozen=True, slots=True)
class CommandOutput:
    """Hold the raw output and exit code of one command"""

    stdout: bytes
    stderr: bytes
    exit_code: int


@dataclass(frozen=True, slots=True)
class RunResult:
    """Hold everything a command line produced and the state it left behind"""

    stdout: str
    stderr: str
    exit_code: int
    cwd: str
    environment: dict[str, str]
    host_call: HostCall | None


@dataclass(frozen=True, slots=True)
class Candidate:
    """Hold one possible completion of a word"""

    value: str
    display: str
    is_directory: bool


@dataclass(frozen=True, slots=True)
class PartialWord:
    """Describe the word under the cursor"""

    start: int
    value: str
    quote: QuoteStyle
    position: WordPosition
    command_name: str | None


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """Tell the line editor how to complete a word"""

    word_start: int
    replacement: str | None
    listing: tuple[str, ...]

    def __post_init__(self):
        """Reject a result that both replaces the word and lists candidates

        Raises:
            ValueError: If replacement and listing are both set
        """
        if self.replacement is not None and self.listing:
            raise ValueError("a completion either replaces the word or lists candidates, not both")


@dataclass(frozen=True, slots=True)
class ReplFeedResult:
    """Report what the REPL did with a line"""

    status: ReplStatus
