"""Define the state one shell session carries between commands, its output sinks, jobs, errors and signals"""

# Standard libraries
import asyncio
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

EXIT_CODE_SUCCESS = 0
EXIT_CODE_FAILURE = 1
EXIT_CODE_USAGE_ERROR = 2
EXIT_CODE_COMMAND_NOT_FOUND = 127
EXIT_CODE_BROKEN_PIPE = 141
EXIT_CODE_KILLED = 143
EXIT_CODE_MODULUS = 256
NULL_DEVICE_PATH = "/dev/null"
FIRST_BACKGROUND_PID = 1000
PIPE_QUEUE_SIZE_CHUNKS = 64
PIPE_END = None


class ShellError(Exception):
    """Signal a failure raised by the shell itself rather than by a command"""


class ShellSyntaxError(ShellError):
    """Signal command text the shell cannot parse"""


class ExpansionError(ShellError):
    """Signal a word expansion the shell cannot perform, which stops the script"""


class UnsupportedBlockError(ShellError):
    """Signal a block type the executor does not handle yet"""

    def __init__(self, block_text: str):
        """Record the text of the unsupported block

        Args:
            block_text: The command text that could not be planned
        """
        super().__init__(f"unsupported command: {block_text}")
        self.block_text = block_text


class CommandNotFoundError(ShellError):
    """Signal a command name the shell does not know"""

    def __init__(self, name: str):
        """Record the unknown command name

        Args:
            name: The command name that was not found
        """
        super().__init__(f"{name}: command not found")
        self.name = name


class OutputLimitExceededError(Exception):
    """Signal that a captured command wrote more than the executor allows"""

    def __init__(self, collector: object, limit_characters: int):
        """Record which collector overflowed

        Args:
            collector: The object that was collecting the output
            limit_characters: The limit that was exceeded
        """
        super().__init__(f"output exceeded {limit_characters} characters")
        self.collector = collector
        self.limit_characters = limit_characters


class ControlFlowSignal(Exception):  # noqa: N818
    """Carry a shell control-flow builtin up to the construct that handles it"""


class BreakLoop(ControlFlowSignal):
    """Leave the innermost loop"""


class ContinueLoop(ControlFlowSignal):
    """Start the next iteration of the innermost loop"""


class ReturnFromFunction(ControlFlowSignal):
    """Leave the current function with an exit code"""

    def __init__(self, exit_code: int):
        """Record the exit code to return

        Args:
            exit_code: The value the function call evaluates to
        """
        super().__init__(exit_code)
        self.exit_code = exit_code


class ExitShell(ControlFlowSignal):
    """Stop the whole script with an exit code"""

    def __init__(self, exit_code: int):
        """Record the exit code to stop with

        Args:
            exit_code: The value the script evaluates to
        """
        super().__init__(exit_code)
        self.exit_code = exit_code


class OutputSink(Protocol):
    """Receive standard output, awaiting when the receiver needs the writer to slow down"""

    async def write(self, text: str) -> None:
        """Deliver one chunk, returning once the receiver has room for more

        Args:
            text: The chunk to deliver
        """

    def write_sync(self, text: str) -> None:
        """Deliver one chunk without waiting

        Args:
            text: The chunk to deliver
        """


class CallableSink:
    """Deliver output to a callable, which may return an awaitable"""

    def __init__(self, receiver: Callable[[str], Any]):
        """Wrap one receiver

        Args:
            receiver: Takes a chunk of text and may return an awaitable
        """
        self.receiver = receiver
        self.scheduled: set[asyncio.Future] = set()

    async def write(self, text: str) -> None:
        """Call the receiver and await its result when it returns one

        Args:
            text: The chunk to deliver
        """
        result = self.receiver(text)
        if inspect.isawaitable(result):
            await result

    def write_sync(self, text: str) -> None:
        """Call the receiver, scheduling any awaitable it returns on the running loop

        Args:
            text: The chunk to deliver
        """
        result = self.receiver(text)
        if inspect.isawaitable(result):
            future = asyncio.ensure_future(result)
            self.scheduled.add(future)
            future.add_done_callback(self.scheduled.discard)


class RecordingSink:
    """Remember every chunk and pass it on"""

    def __init__(self, inner: OutputSink, chunks: list[str]):
        """Wrap one sink

        Args:
            inner: The sink that receives the chunks after they are recorded
            chunks: The list the chunks are appended to
        """
        self.inner = inner
        self.chunks = chunks

    async def write(self, text: str) -> None:
        """Record and forward one chunk

        Args:
            text: The chunk to deliver
        """
        self.chunks.append(text)
        await self.inner.write(text)

    def write_sync(self, text: str) -> None:
        """Record and forward one chunk without waiting

        Args:
            text: The chunk to deliver
        """
        self.chunks.append(text)
        self.inner.write_sync(text)


class CollectingSink:
    """Collect output in memory, refusing to grow past a limit"""

    def __init__(self, limit_characters: int):
        """Start empty

        Args:
            limit_characters: The most text to hold before raising
        """
        self.pieces: list[str] = []
        self.size = 0
        self.limit_characters = limit_characters

    async def write(self, text: str) -> None:
        """Add one chunk

        Args:
            text: The chunk to add
        """
        self.write_sync(text)

    def write_sync(self, text: str) -> None:
        """Add one chunk

        Args:
            text: The chunk to add

        Raises:
            OutputLimitExceededError: If the collected text would pass the limit
        """
        self.size += len(text)
        if self.size > self.limit_characters:
            raise OutputLimitExceededError(self, self.limit_characters)
        self.pieces.append(text)

    def text(self) -> str:
        """Return everything collected"""
        return "".join(self.pieces)


class PipeSink:
    """Hand output to a consumer through a bounded queue, so a fast producer waits for a slow reader"""

    def __init__(self, queue: asyncio.Queue):
        """Wrap one queue

        Args:
            queue: The bounded queue the consumer reads from
        """
        self.queue = queue

    async def write(self, text: str) -> None:
        """Put one chunk, waiting while the queue is full

        Args:
            text: The chunk to deliver
        """
        await self.queue.put(text)

    def write_sync(self, text: str) -> None:
        """Put one chunk without waiting, growing the queue past its bound if it must

        Args:
            text: The chunk to deliver
        """
        self._put_without_waiting(text)

    def close_nowait(self) -> None:
        """Tell the consumer that no more chunks will come"""
        self._put_without_waiting(PIPE_END)

    def _put_without_waiting(self, item: Any) -> None:
        """Append an item even when the queue is full

        Args:
            item: The chunk or the end marker
        """
        if self.queue.full():
            self.queue._queue.append(item)
            self.queue._wakeup_next(self.queue._getters)
        else:
            self.queue.put_nowait(item)


class JobStatus(StrEnum):
    """Name what a background job is doing, as the fake ps prints it"""

    RUNNING = "R"
    DONE = "D"
    KILLED = "K"


@dataclass
class Job:
    """Hold one background job"""

    pid: int
    command_text: str
    task: asyncio.Task
    status: JobStatus = JobStatus.RUNNING
    exit_code: int = EXIT_CODE_SUCCESS


@dataclass
class JobTable:
    """Hold every background job of one session, shared by every copy of its state"""

    jobs: dict[int, Job] = field(default_factory=dict)
    next_pid: int = FIRST_BACKGROUND_PID

    def register(self, command_text: str, task: asyncio.Task) -> Job:
        """Add a running job under the next free pid

        Args:
            command_text: The command the job runs, as ps shows it
            task: The task running it

        Returns:
            The new job
        """
        job = Job(pid=self.next_pid, command_text=command_text, task=task)
        self.jobs[job.pid] = job
        self.next_pid += 1
        return job

    def running(self) -> list[Job]:
        """Return the jobs still running, in pid order"""
        return [job for job in self.jobs.values() if job.status == JobStatus.RUNNING]


def write_to_stdout(text: str) -> None:
    """Write text to the process standard output

    Args:
        text: The text to write
    """
    sys.stdout.write(text)


def write_to_stderr(text: str) -> None:
    """Write text to the process standard error

    Args:
        text: The text to write
    """
    sys.stderr.write(text)


@dataclass
class ShellState:
    """Hold everything a running script can read or change"""

    cwd: Path
    write_output: Callable[[str], Any]
    write_error: Callable[[str], None]
    variables: dict[str, str] = field(default_factory=dict)
    functions: dict[str, str] = field(default_factory=dict)
    positional_arguments: list[str] = field(default_factory=list)
    last_exit_code: int = EXIT_CODE_SUCCESS
    pending_stdin: Any = None
    loop_depth: int = 0
    function_depth: int = 0
    job_table: JobTable = field(default_factory=JobTable)
    last_background_pid: int | None = None

    def __post_init__(self):
        """Build the output sink and wrap the error sink so terminal output is recorded as well as streamed"""
        self.stdout_chunks: list[str] = []
        self.stderr_chunks: list[str] = []
        self.output_sink: OutputSink = RecordingSink(CallableSink(self.write_output), self.stdout_chunks)
        terminal_error = self.write_error

        def record_and_write_error(text: str) -> None:
            self.stderr_chunks.append(text)
            terminal_error(text)

        self.write_error = record_and_write_error
        self.terminal_output_sink: OutputSink = self.output_sink
        self.terminal_write_error: Callable[[str], None] = self.write_error

    @property
    def stdout(self) -> str:
        """Return everything written to standard output so far"""
        return "".join(self.stdout_chunks)

    @property
    def stderr(self) -> str:
        """Return everything written to standard error so far"""
        return "".join(self.stderr_chunks)

    @classmethod
    def for_terminal(cls, cwd: Path | None = None):
        """Return a state that writes straight to the process streams

        Args:
            cwd: The starting directory, defaulting to the process working directory
        """
        return cls(cwd=cwd or Path.cwd(), write_output=write_to_stdout, write_error=write_to_stderr)

    def copy(self):
        """Return an independent copy for a subshell, sharing the current sinks and the job table"""
        copied = ShellState(
            cwd=self.cwd,
            write_output=self.write_output,
            write_error=self.write_error,
            variables=dict(self.variables),
            functions=dict(self.functions),
            positional_arguments=list(self.positional_arguments),
            last_exit_code=self.last_exit_code,
            loop_depth=self.loop_depth,
            function_depth=self.function_depth,
            job_table=self.job_table,
            last_background_pid=self.last_background_pid,
        )
        copied.output_sink = self.output_sink
        copied.write_error = self.write_error
        copied.terminal_output_sink = self.terminal_output_sink
        copied.terminal_write_error = self.terminal_write_error
        return copied

    def is_attached_to_terminal(self) -> bool:
        """Return whether both sinks still point at the terminal rather than a pipe, capture or file"""
        return self.output_sink is self.terminal_output_sink and self.write_error is self.terminal_write_error

    def resolve_path(self, path_text: str) -> Path:
        """Return a path made absolute against the current directory

        Args:
            path_text: A path as written on the command line

        Returns:
            The absolute path
        """
        path = Path(path_text).expanduser()
        return path if path.is_absolute() else self.cwd / path
