"""Run plan nodes: parse a script, build each block's plan, execute it, and recurse into the scripts it contains"""

# Standard libraries
import asyncio
import dataclasses
import fnmatch
import inspect
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from bash_purepython.arithmetic import evaluate_arithmetic

# Project libraries
from bash_purepython.block_parser import build_plan
from bash_purepython.command.command import Command, CommandInvocation, ExitStatus, InputKind, OutputKind
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.conditional import conditional_body, evaluate_conditional
from bash_purepython.parse_script import split_script_into_connected_commands
from bash_purepython.shell_builtins import BUILTIN_SUMMARIES, ReadOptions, ShellBuiltins
from bash_purepython.shell_state import (
    EXIT_CODE_BROKEN_PIPE,
    EXIT_CODE_COMMAND_NOT_FOUND,
    EXIT_CODE_FAILURE,
    EXIT_CODE_KILLED,
    EXIT_CODE_MODULUS,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_USAGE_ERROR,
    NULL_DEVICE_PATH,
    PIPE_END,
    PIPE_QUEUE_SIZE_CHUNKS,
    BreakLoop,
    CollectingSink,
    ContinueLoop,
    ControlFlowSignal,
    ExitShell,
    ExpansionError,
    Job,
    JobStatus,
    OutputLimitExceededError,
    OutputSink,
    PipeSink,
    ProcessSubstitutionDirection,
    ReturnFromFunction,
    ShellError,
    ShellOption,
    ShellState,
    ShellSyntaxError,
    UnboundVariableError,
)
from bash_purepython.streams import (
    KIND_PREFERENCE,
    TEXT_ENCODING,
    TextStream,
    as_async_iterator,
    choose_kinds,
    close_iterator,
    convert,
    materialise_text,
)
from bash_purepython.words import (
    Assignment,
    QuoteStyle,
    RunSubstitution,
    Word,
    array_elements,
    expand_raw_word,
    expand_text,
    expand_word_as_pattern,
    expand_word_unsplit,
    expand_words,
    process_substitution_script,
    resolve_array_index,
    tokenize_simple_command,
)
from bash_purepython.workflow import (
    AndOrListNode,
    BackgroundNode,
    BraceGroupNode,
    CaseNode,
    CaseTerminator,
    ForNode,
    FunctionDefinitionNode,
    IfNode,
    ListOperator,
    PipelineNode,
    PlanNode,
    Redirection,
    RedirectionKind,
    SelectNode,
    SimpleCommandNode,
    SubshellNode,
    UntilNode,
    WhileNode,
)

PREVIOUS_DIRECTORY_VARIABLE_NAME = "OLDPWD"
CURRENT_DIRECTORY_VARIABLE_NAME = "PWD"
HOME_VARIABLE_NAME = "HOME"
NO_OP_BUILTIN_NAME = ":"
SHELL_COMMAND_NAMES = frozenset({"bash", "sh"})
SOURCE_COMMAND_NAMES = frozenset({"source", "."})
SCRIPT_COMMAND_NAMES = SHELL_COMMAND_NAMES | SOURCE_COMMAND_NAMES
INLINE_SCRIPT_OPTION = "-c"
ARRAY_ELEMENT_PATTERN = re.compile(r"^([A-Za-z_]\w*)\[(.+)\]$")
PATH_SEPARATOR = "/"
EXIT_CODE_NOT_EXECUTABLE = 126
EXIT_CODE_UNBOUND_VARIABLE = 127
DEFAULT_OUTPUT_LIMIT_CHARACTERS = 16 << 20
SELECT_PROMPT_VARIABLE_NAME = "PS3"
DEFAULT_SELECT_PROMPT = "#? "
REPLY_VARIABLE_NAME = "REPLY"
COLUMNS_VARIABLE_NAME = "COLUMNS"
DEFAULT_TERMINAL_WIDTH = 80
SELECT_INDEX_SUFFIX_LENGTH = 2
SELECT_CELL_GAP = 2
TAB_WIDTH = 8
INTEGER_REPLY_PATTERN = re.compile(r"^\s*[+-]?\d+\s*$")
OUTPUT_REDIRECTION_KINDS = frozenset(
    {
        RedirectionKind.WRITE_STDOUT,
        RedirectionKind.APPEND_STDOUT,
        RedirectionKind.WRITE_BOTH,
        RedirectionKind.STDOUT_TO_STDERR,
    }
)
JOB_STATUS_WORDS = {JobStatus.RUNNING: "Running", JobStatus.DONE: "Done", JobStatus.KILLED: "Terminated"}
CORE_BUILTIN_SUMMARIES = {
    "cd": "change the working directory",
    "export": "mark variables for export to commands",
    "unset": "remove variables and functions",
    "exit": "leave the shell with an exit code",
    "return": "leave a function with an exit code",
    "break": "leave the innermost loop",
    "continue": "start the next iteration of the innermost loop",
    "wait": "wait for background jobs to finish",
    "jobs": "list the background jobs",
    ":": "do nothing, successfully",
    "bash": "run a script file, -c text, or standard input",
    "sh": "run a script file, -c text, or standard input",
    "source": "run a file in the current shell",
    ".": "run a file in the current shell",
}
JOB_STATUS_COLUMN_WIDTH = 24
XTRACE_PREFIX = "+ "


class ErrorDestination(StrEnum):
    """Name where a command's error output goes when it is not a file"""

    STDERR = "stderr"
    STDOUT = "stdout"
    SINK_STDOUT = "sink_stdout"
    DISCARD = "discard"


@dataclass(frozen=True)
class StdinValue:
    """Hold a command's standard input in a known kind"""

    value: Any
    kind: OutputKind


Builtin = Callable[[list[str], StdinValue | None, ShellState], Awaitable[int]]
CompoundBody = Callable[[ShellState], Awaitable[int]]


class ExecutionResult:
    """Hold what a node produced on standard output and how it finished"""

    def __init__(self, stdout: Any, kind: OutputKind, exit_code: int):
        """Record one node's output

        Args:
            stdout: The output in its kind
            kind: The kind the output is in
            exit_code: The exit code, provisional while a stream is still being pulled
        """
        self.stdout = stdout
        self.kind = kind
        self._exit_code = exit_code
        self.exempt_from_errexit = False

    @property
    def exit_code(self) -> int:
        """Return the exit code, reading it from the stream once that has finished"""
        if isinstance(self.stdout, TextStream):
            return self.stdout.exit_code
        return self._exit_code

    @classmethod
    def empty(cls, exit_code: int):
        """Return a result with no output

        Args:
            exit_code: The exit code to report
        """
        return cls(stdout="", kind=OutputKind.TEXT, exit_code=exit_code)

    def as_stdin(self) -> StdinValue:
        """Return the output shaped as the next command's standard input"""
        return StdinValue(value=self.stdout, kind=self.kind)


class PipelineResult(ExecutionResult):
    """Hold a pipeline's output with the exit code of its last failing stage, as ``pipefail`` reports it"""

    def __init__(self, last: ExecutionResult, stage_results: list[ExecutionResult]):
        """Wrap the last stage's result

        Args:
            last: The last stage's result, whose output is the pipeline's
            stage_results: Every stage's result in order
        """
        super().__init__(stdout=last.stdout, kind=last.kind, exit_code=last.exit_code)
        self.stage_results = stage_results

    @property
    def exit_code(self) -> int:
        """Return the exit code of the last stage that failed, or zero when every stage succeeded"""
        failures = [result.exit_code for result in self.stage_results if result.exit_code != EXIT_CODE_SUCCESS]
        return failures[-1] if failures else EXIT_CODE_SUCCESS


class SubstitutionRunner:
    """Run ``$( )`` and backtick scripts for word expansion, remembering how the last one finished"""

    def __init__(self, executor: "Executor", state: ShellState):
        """Bind to one executor and state

        Args:
            executor: The executor that runs the scripts
            state: The shell state the substitutions run against
        """
        self.executor = executor
        self.state = state
        self.last_exit_code: int | None = None

    async def __call__(self, script: str) -> str:
        """Run a script and return its output with trailing newlines removed

        Args:
            script: The substituted script text

        Returns:
            The captured standard output
        """
        output, self.last_exit_code = await self.executor.capture_script(script, self.state)
        return output.rstrip("\n")


@contextmanager
def redirected_sinks(
    state: ShellState,
    output_sink: OutputSink | None = None,
    write_error: Callable[[str], None] | None = None,
) -> Generator[None, None, None]:
    """Swap the state's sinks for the duration of a block

    Args:
        state: The live shell state
        output_sink: A replacement standard output sink, or None to keep the current one
        write_error: A replacement standard error sink, or None to keep the current one
    """
    saved_output, saved_error = state.output_sink, state.write_error
    if output_sink is not None:
        state.output_sink = output_sink
    if write_error is not None:
        state.write_error = write_error
    try:
        yield
    finally:
        state.output_sink, state.write_error = saved_output, saved_error


def discard_text(text: str) -> None:
    """Drop text sent to the null device

    Args:
        text: Ignored
    """


async def interleave_errors(stream: Any, error_buffer: list[str], encode: bool = False) -> AsyncIterator[Any]:
    """Yield a command's output with the errors it wrote so far placed before each chunk

    Args:
        stream: The command's standard output, synchronous or asynchronous
        error_buffer: Where the command's error sink collects text
        encode: Whether the stream carries bytes, so buffered errors are encoded to match

    Yields:
        Error text and output chunks in the order they were produced
    """
    source = as_async_iterator(stream)

    def flush() -> Any:
        text = "".join(error_buffer)
        error_buffer.clear()
        return text.encode(TEXT_ENCODING) if encode else text

    try:
        async for chunk in source:
            if error_buffer:
                yield flush()
            yield chunk
        if error_buffer:
            yield flush()
    finally:
        await close_iterator(source)


async def read_queue(queue: asyncio.Queue) -> AsyncIterator[str]:
    """Yield chunks from a pipe queue until the end marker arrives

    Args:
        queue: The queue a pipe sink writes into

    Yields:
        Each chunk
    """
    while True:
        chunk = await queue.get()
        if chunk is PIPE_END:
            return
        yield chunk


class Executor:
    """Run scripts against a shell state using one registry of commands"""

    def __init__(
        self, registry: CommandRegistry | None = None, output_limit_characters: int = DEFAULT_OUTPUT_LIMIT_CHARACTERS
    ):
        """Create an executor

        Args:
            registry: The commands available to scripts, defaulting to everything the package ships
            output_limit_characters: The most output a captured substitution or redirected group may produce
        """
        self.registry = registry if registry is not None else CommandRegistry()
        self.output_limit_characters = output_limit_characters
        self.builtins: dict[str, Builtin] = {
            "cd": self.builtin_cd,
            "export": self.builtin_export,
            "unset": self.builtin_unset,
            "exit": self.builtin_exit,
            "return": self.builtin_return,
            "break": self.builtin_break,
            "continue": self.builtin_continue,
            "wait": self.builtin_wait,
            "jobs": self.builtin_jobs,
            NO_OP_BUILTIN_NAME: self.builtin_no_op,
        }
        self.shell_builtins = ShellBuiltins(self)
        self.builtins.update(self.shell_builtins.table())
        self.script_command_names = SCRIPT_COMMAND_NAMES

    def builtin_summaries(self) -> dict[str, str]:
        """Return a one-line summary for every builtin and script command, for help listings"""
        return {**CORE_BUILTIN_SUMMARIES, **BUILTIN_SUMMARIES}

    async def execute_script(self, script: str, state: ShellState) -> int:
        """Run a whole script as the outermost entry point, so exit stops it and stray signals are swallowed

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            The exit code of the script
        """
        try:
            return await self.run_script(script, state)
        except ExitShell as exit_shell:
            state.last_exit_code = exit_shell.exit_code
        except ControlFlowSignal:
            pass
        return state.last_exit_code

    async def run_script_async(self, script: str, state: ShellState) -> int:
        """Run a whole script, for hosts such as pyodide that await on an already running event loop

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            The exit code of the script
        """
        return await self.execute_script(script, state)

    async def run_script(self, script: str, state: ShellState) -> int:
        """Parse a script into blocks and run each one, writing its output to the state's sink

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            The exit code of the last block
        """
        for block in split_script_into_connected_commands(script):
            await asyncio.sleep(0)
            try:
                node = build_plan(block)
                result = await self.execute_node(node, state, stdin=None, direct_output=True)
                await self.drain_to_sink(result, state)
                await self.finish_process_substitutions(state)
            except ShellSyntaxError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = EXIT_CODE_USAGE_ERROR
                return state.last_exit_code
            except ExpansionError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = (
                    EXIT_CODE_UNBOUND_VARIABLE if isinstance(error, UnboundVariableError) else EXIT_CODE_FAILURE
                )
                return state.last_exit_code
            except ShellError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = EXIT_CODE_FAILURE
                continue
            state.last_exit_code = result.exit_code
            if (
                ShellOption.ERREXIT in state.options
                and result.exit_code != EXIT_CODE_SUCCESS
                and state.condition_depth == 0
                and not result.exempt_from_errexit
            ):
                raise ExitShell(result.exit_code)
        return state.last_exit_code

    async def run_subshell_script(self, script: str, state: ShellState) -> int:
        """Run a script as a subshell body, where exit, break and continue only leave the subshell

        Args:
            script: The script text
            state: The subshell's own state

        Returns:
            The exit code of the script, or the code passed to exit
        """
        try:
            return await self.run_script(script, state)
        except ExitShell as exit_shell:
            return exit_shell.exit_code
        except (BreakLoop, ContinueLoop):
            return state.last_exit_code

    async def capture_script(self, script: str, state: ShellState) -> tuple[str, int]:
        """Run a script with its standard output collected, for command substitution

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            Everything the script wrote to standard output, and its exit code
        """
        collector = CollectingSink(self.output_limit_characters)
        outer_substitutions = state.process_substitutions
        state.process_substitutions = []
        try:
            with redirected_sinks(state, output_sink=collector):
                exit_code = await self.run_subshell_script(script, state)
        except OutputLimitExceededError as error:
            if error.collector is not collector:
                raise
            raise ExpansionError(f"command substitution: {error}") from error
        finally:
            state.process_substitutions = outer_substitutions
        return collector.text(), exit_code

    async def finish_process_substitutions(self, state: ShellState) -> None:
        """Run the scripts of the block's ``>( )`` substitutions over what was written, then remove every file

        Args:
            state: The shell state holding the substitutions the block created
        """
        pending = state.process_substitutions
        if not pending:
            return
        state.process_substitutions = []
        try:
            for substitution in pending:
                if substitution.direction == ProcessSubstitutionDirection.OUTPUT:
                    script = process_substitution_script(substitution.script, substitution.direction, substitution.path)
                    await self.run_subshell_script(script, state.copy())
        finally:
            for substitution in pending:
                substitution.path.unlink(missing_ok=True)

    def substitution_runner(self, state: ShellState) -> SubstitutionRunner:
        """Return the callback word expansion uses for ``$( )`` and backticks

        Args:
            state: The shell state the substitutions run against

        Returns:
            An awaitable callable from script text to its output
        """
        return SubstitutionRunner(self, state)

    async def drain_to_sink(self, result: ExecutionResult, state: ShellState) -> None:
        """Write a result's output to the state's standard output sink as it is produced

        Args:
            result: The result to drain
            state: The shell state whose sink receives the text
        """
        if result.kind in (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES):
            chunks = as_async_iterator(await convert(result.stdout, result.kind, OutputKind.STREAM_TEXT))
            try:
                async for chunk in chunks:
                    await state.output_sink.write(chunk)
            finally:
                await close_iterator(chunks)
            return
        text = await materialise_text(result.stdout, result.kind)
        if text:
            await state.output_sink.write(text)

    async def execute_node(
        self, node: PlanNode, state: ShellState, stdin: StdinValue | None, direct_output: bool
    ) -> ExecutionResult:
        """Run one plan node

        Args:
            node: The node to run
            state: The shell state to run against
            stdin: Standard input from an upstream pipeline stage, or None
            direct_output: Whether compound commands may write straight to the sink instead of being captured

        Returns:
            The node's output and exit code
        """
        if isinstance(node, SimpleCommandNode):
            return await self.execute_simple_command(node, state, stdin)
        if isinstance(node, PipelineNode):
            return await self.execute_pipeline(node, state, stdin)
        if isinstance(node, AndOrListNode):
            return await self.execute_and_or_list(node, state, stdin, direct_output)
        if isinstance(node, BackgroundNode):
            return self.start_background_job(node, state)
        if isinstance(node, FunctionDefinitionNode):
            state.functions[node.name] = node.body
            return ExecutionResult.empty(EXIT_CODE_SUCCESS)
        body, body_state, redirections = self.compound_body(node, state)
        return await self.execute_compound(body, body_state, stdin, redirections, direct_output)

    def compound_body(self, node: PlanNode, state: ShellState) -> tuple[CompoundBody, ShellState, list[Redirection]]:
        """Return how to run a compound node, the state it runs against, and its redirections

        Args:
            node: A subshell, group, conditional or loop node
            state: The live shell state

        Raises:
            ShellSyntaxError: If the node is not a compound command

        Returns:
            The body coroutine factory, the state to run it against, and the node's trailing redirections
        """
        if isinstance(node, SubshellNode):
            expression = node.arithmetic_expression
            if expression is not None:
                return (
                    (lambda inner: self.run_arithmetic_command(expression, inner)),
                    state,
                    node.redirections,
                )
            body_text = node.body
            return (lambda inner: self.run_subshell_script(body_text, inner)), state.copy(), node.redirections
        if isinstance(node, BraceGroupNode):
            body_text = node.body
            return (lambda inner: self.run_script(body_text, inner)), state, node.redirections
        if isinstance(node, IfNode):
            return (lambda inner: self.run_if(node, inner)), state, node.redirections
        if isinstance(node, ForNode):
            return (lambda inner: self.run_for(node, inner)), state, node.redirections
        if isinstance(node, SelectNode):
            return (lambda inner: self.run_select(node, inner)), state, node.redirections
        if isinstance(node, CaseNode):
            return (lambda inner: self.run_case(node, inner)), state, node.redirections
        if isinstance(node, WhileNode | UntilNode):
            return (lambda inner: self.run_while(node, inner)), state, node.redirections
        raise ShellSyntaxError(f"unknown plan node: {node}")

    async def run_arithmetic_command(self, expression: str, state: ShellState) -> int:
        """Evaluate the expression of a ``(( ))`` command against the live state

        Args:
            expression: The text between the double parentheses
            state: The shell state whose variables are read and assigned

        Returns:
            Zero when the value is nonzero, one when it is zero
        """
        expanded = await expand_text(expression, state, self.substitution_runner(state), in_double_quotes=False)
        return EXIT_CODE_SUCCESS if evaluate_arithmetic(expanded, state) else EXIT_CODE_FAILURE

    async def execute_compound(
        self,
        run: CompoundBody,
        state: ShellState,
        stdin: StdinValue | None,
        redirections: list[Redirection],
        direct_output: bool,
        error_destination: "ErrorDestination | Path | None" = None,
    ) -> ExecutionResult:
        """Run a compound command inline, capturing its output when a redirection or caller needs it

        Args:
            run: Runs the compound body against a state and returns its exit code
            state: The state the body runs against, a copy for a subshell
            stdin: Standard input the body's commands may consume, or None
            redirections: Redirections written after the compound command
            direct_output: Whether the body may write straight to the sink when nothing needs capturing
            error_destination: Where errors go when the caller has already worked it out

        Returns:
            An empty result when the output went to the sink, otherwise the captured text
        """
        stdin = await self.apply_input_redirections(stdin, redirections, state)
        if error_destination is None:
            error_destination = await self.error_destination(redirections, state, merge_stderr=False)
        has_output_redirection = any(redirection.kind in OUTPUT_REDIRECTION_KINDS for redirection in redirections)
        previous_stdin = state.pending_stdin
        if stdin is not None:
            state.pending_stdin = stdin
        try:
            if direct_output and not has_output_redirection:
                write_error = self.error_sink(error_destination, state, state.output_sink.write_sync)
                with redirected_sinks(state, write_error=write_error):
                    return ExecutionResult.empty(await run(state))
            collector = CollectingSink(self.output_limit_characters)
            write_error = self.error_sink(error_destination, state, collector.write_sync)
            try:
                with redirected_sinks(state, output_sink=collector, write_error=write_error):
                    exit_code = await run(state)
            except OutputLimitExceededError as error:
                if error.collector is not collector:
                    raise
                state.write_error(f"bash: {error}\n")
                exit_code = EXIT_CODE_BROKEN_PIPE
            result = ExecutionResult(stdout=collector.text(), kind=OutputKind.TEXT, exit_code=exit_code)
        finally:
            state.pending_stdin = previous_stdin
        return await self.apply_output_redirections(result, redirections, state, error_destination)

    async def stream_compound(
        self,
        run: CompoundBody,
        state: ShellState,
        stdin: StdinValue | None,
        redirections: list[Redirection],
        merge_stderr: bool,
        error_destination: "ErrorDestination | Path | None" = None,
    ) -> ExecutionResult:
        """Run a compound command as a task whose output streams through a bounded pipe to the next stage

        Args:
            run: Runs the compound body against a state and returns its exit code
            state: A private copy of the state for the stage
            stdin: Standard input the body's commands may consume, or None
            redirections: Redirections written after the compound command
            merge_stderr: Whether the stage's error output joins its standard output
            error_destination: Where errors go when the caller has already worked it out

        Returns:
            A streaming result whose closing cancels the task
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=PIPE_QUEUE_SIZE_CHUNKS)
        sink = PipeSink(queue)
        exit_status = ExitStatus()
        state.output_sink = sink
        if error_destination is None:
            error_destination = await self.error_destination(redirections, state, merge_stderr)

        async def body() -> None:
            try:
                result = await self.execute_compound(
                    run, state, stdin, redirections, direct_output=True, error_destination=error_destination
                )
                exit_status.code = result.exit_code
            except ShellError as error:
                state.write_error(f"bash: {error}\n")
                exit_status.code = EXIT_CODE_FAILURE
            finally:
                sink.close_nowait()

        task = asyncio.create_task(body())

        async def stop() -> None:
            task.cancel()
            await asyncio.wait({task})

        stream = TextStream(read_queue(queue), exit_status=exit_status, on_close=stop)
        return ExecutionResult(stdout=stream, kind=OutputKind.STREAM_TEXT, exit_code=EXIT_CODE_SUCCESS)

    def start_background_job(self, node: BackgroundNode, state: ShellState) -> ExecutionResult:
        """Start a command as a background job and return at once

        Args:
            node: The background node
            state: The live shell state, whose job table and sinks the job shares

        Returns:
            An empty result with exit code zero
        """
        job_state = state.copy()

        async def body() -> int:
            try:
                result = await self.execute_node(node.inner, job_state, stdin=None, direct_output=True)
                await self.drain_to_sink(result, job_state)
                return result.exit_code
            except ExitShell as exit_shell:
                return exit_shell.exit_code
            except ControlFlowSignal:
                return job_state.last_exit_code
            except ShellError as error:
                job_state.write_error(f"bash: {error}\n")
                return EXIT_CODE_FAILURE

        task = asyncio.create_task(body())
        job = state.job_table.register(node.command_text, task)
        task.add_done_callback(lambda finished: record_job_outcome(job, finished))
        state.last_background_pid = job.pid
        return ExecutionResult.empty(EXIT_CODE_SUCCESS)

    async def execute_pipeline(
        self, node: PipelineNode, state: ShellState, stdin: StdinValue | None
    ) -> ExecutionResult:
        """Run the stages of a pipeline, each pulling lazily from the one before it

        Args:
            node: The pipeline
            state: The shell state to run against
            stdin: Standard input for the first stage, or None

        Returns:
            The last stage's result, or a drained result with the exit code flipped when negated
        """
        result: ExecutionResult | None = None
        upstream: TextStream | None = None
        stage_results: list[ExecutionResult] = []
        for index, stage in enumerate(node.stages):
            stage_stdin = stdin if result is None else result.as_stdin()
            merge_stderr = index < len(node.merge_stderr) and node.merge_stderr[index]
            result = await self.execute_stage(stage, state, stage_stdin, merge_stderr)
            stage_results.append(result)
            if isinstance(result.stdout, TextStream):
                result.stdout.upstream = upstream
                upstream = result.stdout
            elif upstream is not None:
                await upstream.aclose()
                upstream = None
        if result is None:
            raise ShellSyntaxError("empty pipeline")
        if ShellOption.PIPEFAIL in state.options and len(stage_results) > 1:
            result = PipelineResult(result, stage_results)
        if not node.negated:
            return result
        text = await materialise_text(result.stdout, result.kind)
        exit_code = EXIT_CODE_FAILURE if result.exit_code == EXIT_CODE_SUCCESS else EXIT_CODE_SUCCESS
        negated_result = ExecutionResult(stdout=text, kind=OutputKind.TEXT, exit_code=exit_code)
        negated_result.exempt_from_errexit = True
        return negated_result

    async def execute_stage(
        self, stage: PlanNode, state: ShellState, stdin: StdinValue | None, merge_stderr: bool
    ) -> ExecutionResult:
        """Run one pipeline stage with its output flowing to the next stage

        A simple command is pulled lazily by its consumer. Anything else runs as its own task against a copy of
        the state, as bash runs every stage in a subshell, and streams through a bounded pipe

        Args:
            stage: The stage node
            state: The shell state to run against
            stdin: Standard input from the previous stage, or None
            merge_stderr: Whether the stage's error output joins its standard output

        Returns:
            The stage's result
        """
        if isinstance(stage, SimpleCommandNode):
            return await self.execute_simple_command(stage, state, stdin, merge_stderr, in_pipeline=True)
        if isinstance(stage, BackgroundNode | FunctionDefinitionNode | AndOrListNode | PipelineNode):
            stage_state = state.copy()

            async def run_inner(inner: ShellState) -> int:
                inner_result = await self.execute_node(stage, inner, stdin=None, direct_output=True)
                await self.drain_to_sink(inner_result, inner)
                return inner_result.exit_code

            return await self.stream_compound(run_inner, stage_state, stdin, [], merge_stderr)
        body, body_state, redirections = self.compound_body(stage, state)
        if body_state is state:
            body_state = state.copy()
        return await self.stream_compound(body, body_state, stdin, redirections, merge_stderr)

    async def execute_and_or_list(
        self, node: AndOrListNode, state: ShellState, stdin: StdinValue | None, direct_output: bool
    ) -> ExecutionResult:
        """Run pipelines joined by && and ||, stopping as the operators dictate

        Args:
            node: The list
            state: The shell state to run against
            stdin: Standard input for the first pipeline, or None
            direct_output: Whether output may go straight to the sink

        Returns:
            An empty result carrying the exit code of the last pipeline that ran, or the captured text
        """
        collector = CollectingSink(self.output_limit_characters)
        ran_last_item = True
        with redirected_sinks(state, output_sink=None if direct_output else collector):
            state.condition_depth += 1
            try:
                exit_code = await self.run_and_drain(node.first, state, stdin)
                for position, (operator, item) in enumerate(node.rest):
                    should_run = (exit_code == EXIT_CODE_SUCCESS) == (operator == ListOperator.AND)
                    ran_last_item = should_run
                    if not should_run:
                        continue
                    if position == len(node.rest) - 1:
                        state.condition_depth -= 1
                    try:
                        exit_code = await self.run_and_drain(item, state, None)
                    finally:
                        if position == len(node.rest) - 1:
                            state.condition_depth += 1
            finally:
                state.condition_depth -= 1
        if direct_output:
            result = ExecutionResult.empty(exit_code)
        else:
            result = ExecutionResult(stdout=collector.text(), kind=OutputKind.TEXT, exit_code=exit_code)
        result.exempt_from_errexit = not ran_last_item
        return result

    async def run_and_drain(self, node: PlanNode, state: ShellState, stdin: StdinValue | None) -> int:
        """Run a node, write its output to the sink, and record its exit code

        Args:
            node: The node to run
            state: The shell state to run against
            stdin: Standard input for the node, or None

        Returns:
            The node's exit code
        """
        result = await self.execute_node(node, state, stdin, direct_output=True)
        await self.drain_to_sink(result, state)
        state.last_exit_code = result.exit_code
        return result.exit_code

    async def run_if(self, node: IfNode, state: ShellState) -> int:
        """Run the first branch whose condition succeeds

        Args:
            node: The if statement
            state: The shell state to run against

        Returns:
            The exit code of the body that ran, or zero when none did
        """
        for condition, body in node.branches:
            if await self.run_condition(condition, state) == EXIT_CODE_SUCCESS:
                return await self.run_script(body, state)
        if node.else_body is not None:
            return await self.run_script(node.else_body, state)
        return EXIT_CODE_SUCCESS

    async def run_case(self, node: CaseNode, state: ShellState) -> int:
        """Run the bodies of the case clauses whose patterns match the word

        Args:
            node: The case statement
            state: The shell state to run against

        Raises:
            ShellSyntaxError: If the tested word or a pattern is not a single word

        Returns:
            The exit code of the last body run, or zero when no pattern matched
        """
        run_substitution = self.substitution_runner(state)
        word = await expand_raw_word(node.word_text, state, run_substitution)
        exit_code = EXIT_CODE_SUCCESS
        fall_through = False
        for clause in node.clauses:
            if not fall_through:
                matched = False
                for pattern_text in split_case_patterns(clause.patterns_text):
                    words, redirections, assignments = tokenize_simple_command(pattern_text)
                    if len(words) != 1 or redirections or assignments:
                        raise ShellSyntaxError(f"bad case pattern: {pattern_text}")
                    pattern = await expand_word_as_pattern(words[0], state, run_substitution)
                    if fnmatch.fnmatchcase(word, pattern):
                        matched = True
                        break
                if not matched:
                    continue
            exit_code = await self.run_script(clause.body, state) if clause.body else EXIT_CODE_SUCCESS
            fall_through = clause.terminator == CaseTerminator.FALL_THROUGH
            if clause.terminator == CaseTerminator.STOP:
                return exit_code
        return exit_code

    async def run_arithmetic_for(self, node: ForNode, state: ShellState) -> int:
        """Run a ``for (( initial; condition; step ))`` loop

        Args:
            node: The for loop, whose ``arithmetic`` holds the three expressions
            state: The shell state to run against

        Returns:
            The exit code of the last body run, or zero when the loop never ran
        """
        initial, condition, step = node.arithmetic or ("", "", "")
        run_substitution = self.substitution_runner(state)

        async def evaluate(expression: str) -> int:
            if not expression.strip():
                return 1
            expanded = await expand_text(expression, state, run_substitution, in_double_quotes=False)
            return evaluate_arithmetic(expanded, state)

        exit_code = EXIT_CODE_SUCCESS
        await evaluate(initial)
        state.loop_depth += 1
        try:
            while await evaluate(condition) != 0:
                try:
                    exit_code = await self.run_script(node.body, state)
                except BreakLoop:
                    break
                except ContinueLoop:
                    pass
                await evaluate(step)
        finally:
            state.loop_depth -= 1
        return exit_code

    async def run_for(self, node: ForNode, state: ShellState) -> int:
        """Run a for loop over its expanded words, over the positional arguments, or arithmetically

        Args:
            node: The for loop
            state: The shell state to run against

        Returns:
            The exit code of the last body run, or zero when the loop never ran
        """
        if node.arithmetic is not None:
            return await self.run_arithmetic_for(node, state)
        if node.words_text is None:
            values = list(state.positional_arguments)
        else:
            words, redirections, assignments = tokenize_simple_command(node.words_text)
            if redirections or assignments:
                raise ShellSyntaxError(f"bad for words: {node.words_text}")
            values = await expand_words(words, state, self.substitution_runner(state))
        exit_code = EXIT_CODE_SUCCESS
        state.loop_depth += 1
        try:
            for value in values:
                state.variables[node.variable] = value
                try:
                    exit_code = await self.run_script(node.body, state)
                except BreakLoop:
                    break
                except ContinueLoop:
                    continue
        finally:
            state.loop_depth -= 1
        return exit_code

    async def run_select(self, node: SelectNode, state: ShellState) -> int:
        """Run a select loop: show the menu, read a choice, bind it and run the body until the input ends

        The menu is printed to standard error, then the ``PS3`` prompt. An empty line shows the menu again,
        a number picks that word, and anything else binds the variable to nothing. ``REPLY`` holds the line

        Args:
            node: The select loop
            state: The shell state to run against

        Returns:
            The exit code of the last body run, or zero when the loop never ran
        """
        if node.words_text is None:
            values = list(state.positional_arguments)
        else:
            words, redirections, assignments = tokenize_simple_command(node.words_text)
            if redirections or assignments:
                raise ShellSyntaxError(f"bad select words: {node.words_text}")
            values = await expand_words(words, state, self.substitution_runner(state))
        exit_code = EXIT_CODE_SUCCESS
        show_menu = True
        state.loop_depth += 1
        try:
            while True:
                if show_menu:
                    state.write_error(format_select_menu(values, select_menu_width(state)))
                state.write_error(state.variables.get(SELECT_PROMPT_VARIABLE_NAME, DEFAULT_SELECT_PROMPT))
                record = await self.shell_builtins.read_record(ReadOptions(raw=True), None, state)
                if record is None:
                    state.write_error("\n")
                    exit_code = EXIT_CODE_FAILURE
                    break
                reply = record[0]
                state.variables[REPLY_VARIABLE_NAME] = reply
                if not reply.strip():
                    show_menu = True
                    continue
                show_menu = False
                state.variables[node.variable] = select_choice(reply, values)
                try:
                    exit_code = await self.run_script(node.body, state)
                except BreakLoop:
                    exit_code = EXIT_CODE_SUCCESS
                    break
                except ContinueLoop:
                    continue
        finally:
            state.loop_depth -= 1
        return exit_code

    async def run_condition(self, script: str, state: ShellState) -> int:
        """Run the condition of an if or loop, where a failure must not stop the shell under errexit

        Args:
            script: The condition text
            state: The shell state to run against

        Returns:
            The condition's exit code
        """
        state.condition_depth += 1
        try:
            return await self.run_script(script, state)
        finally:
            state.condition_depth -= 1

    async def run_while(self, node: WhileNode | UntilNode, state: ShellState) -> int:
        """Run a while or until loop

        Args:
            node: The loop
            state: The shell state to run against

        Returns:
            The exit code of the last body run, or zero when the loop never ran
        """
        run_while_condition_succeeds = isinstance(node, WhileNode)
        exit_code = EXIT_CODE_SUCCESS
        state.loop_depth += 1
        try:
            while True:
                condition_succeeded = await self.run_condition(node.condition, state) == EXIT_CODE_SUCCESS
                if condition_succeeded != run_while_condition_succeeds:
                    return exit_code
                try:
                    exit_code = await self.run_script(node.body, state)
                except BreakLoop:
                    return exit_code
                except ContinueLoop:
                    continue
        finally:
            state.loop_depth -= 1

    async def execute_simple_command(
        self,
        node: SimpleCommandNode,
        state: ShellState,
        stdin: StdinValue | None,
        merge_stderr: bool = False,
        in_pipeline: bool = False,
    ) -> ExecutionResult:
        """Expand one simple command and run it as an assignment, a function, a builtin, or a registered command

        Args:
            node: The simple command
            state: The shell state to run against
            stdin: Standard input from a pipeline, or None
            merge_stderr: Whether the command's error output joins its standard output, as after ``|&``
            in_pipeline: Whether the command is a pipeline stage, so a function call streams in its own task

        Returns:
            The command's output and exit code
        """
        run_substitution = self.substitution_runner(state)
        condition = conditional_body(node.text)
        if condition is not None:
            if stdin is not None:
                await self.discard_stdin(stdin)
            truth = await evaluate_conditional(condition, state, run_substitution)
            return ExecutionResult.empty(EXIT_CODE_SUCCESS if truth else EXIT_CODE_FAILURE)
        words, redirections, assignments = self.expand_aliases(*tokenize_simple_command(node.text), state)
        arguments = await expand_words(words, state, run_substitution)
        if ShellOption.XTRACE in state.options:
            traced = [trace_assignment(assignment) for assignment in assignments]
            state.write_error(XTRACE_PREFIX + " ".join(traced + arguments) + "\n")
        if not arguments:
            for assignment in assignments:
                await self.apply_assignment(assignment, state, run_substitution)
            exit_code = run_substitution.last_exit_code
            return ExecutionResult.empty(EXIT_CODE_SUCCESS if exit_code is None else exit_code)
        saved_variables = {assignment.name: state.variables.get(assignment.name) for assignment in assignments}
        saved_arrays = {assignment.name: state.arrays.get(assignment.name) for assignment in assignments}
        temporarily_exported = {
            assignment.name for assignment in assignments if assignment.name not in state.exported_names
        }
        for assignment in assignments:
            await self.apply_assignment(assignment, state, run_substitution)
            state.exported_names.add(assignment.name)
        error_destination = await self.error_destination(redirections, state, merge_stderr)
        try:
            stdin = await self.apply_input_redirections(stdin, redirections, state)
            builtin = self.builtins.get(arguments[0]) if arguments[0] not in state.functions else None
            has_output_redirection = any(redirection.kind in OUTPUT_REDIRECTION_KINDS for redirection in redirections)
            if builtin is not None and (in_pipeline or has_output_redirection):
                return await self.run_builtin_as_compound(
                    builtin, arguments[1:], stdin, redirections, state, in_pipeline, merge_stderr, error_destination
                )
            attached_to_terminal = (
                not in_pipeline
                and error_destination == ErrorDestination.STDERR
                and not any(redirection.kind in OUTPUT_REDIRECTION_KINDS for redirection in redirections)
                and state.is_attached_to_terminal()
            )
            result = await self.dispatch(
                arguments[0], arguments[1:], stdin, error_destination, state, in_pipeline, attached_to_terminal
            )
        finally:
            restore_temporary_assignments(saved_variables, saved_arrays, temporarily_exported, state)
        return await self.apply_output_redirections(result, redirections, state, error_destination, merge_stderr)

    async def run_builtin_as_compound(
        self,
        builtin: Builtin,
        arguments: list[str],
        stdin: StdinValue | None,
        redirections: list[Redirection],
        state: ShellState,
        in_pipeline: bool,
        merge_stderr: bool,
        error_destination: "ErrorDestination | Path",
    ) -> ExecutionResult:
        """Run a builtin whose output is piped or redirected, the way a compound command is

        A pipeline stage runs against a copy of the state, as bash runs it in a subshell

        Args:
            builtin: The builtin to run
            arguments: Its arguments
            stdin: Standard input after input redirections, or None
            redirections: The command's redirections
            state: The shell state to run against
            in_pipeline: Whether the builtin is a pipeline stage
            merge_stderr: Whether its error output joins its standard output
            error_destination: Where its error output goes

        Returns:
            The builtin's output and exit code
        """
        output_redirections = [
            redirection for redirection in redirections if redirection.kind in OUTPUT_REDIRECTION_KINDS
        ]

        async def body(inner: ShellState) -> int:
            return await builtin(arguments, None, inner)

        if in_pipeline:
            return await self.stream_compound(
                body, state.copy(), stdin, output_redirections, merge_stderr, error_destination=error_destination
            )
        return await self.execute_compound(
            body, state, stdin, output_redirections, direct_output=True, error_destination=error_destination
        )

    def expand_aliases(
        self,
        words: list[Word],
        redirections: list[Redirection],
        assignments: list[Assignment],
        state: ShellState,
    ) -> tuple[list[Word], list[Redirection], list[Assignment]]:
        """Replace an alias in the command position with the words it stands for, repeating for a new alias

        Args:
            words: The command's words
            redirections: The command's redirections
            assignments: The assignments before the command name
            state: The shell state holding the aliases

        Returns:
            The words, redirections and assignments after alias expansion
        """
        seen: set[str] = set()
        while words and len(words[0].parts) == 1 and words[0].parts[0].quote == QuoteStyle.NONE:
            name = words[0].parts[0].text
            if name not in state.aliases or name in seen:
                break
            seen.add(name)
            alias_words, alias_redirections, alias_assignments = tokenize_simple_command(state.aliases[name])
            words = [*alias_words, *words[1:]]
            redirections = [*alias_redirections, *redirections]
            assignments = [*assignments, *alias_assignments]
        return words, redirections, assignments

    def stdin_value(self, value: Any, kind: OutputKind) -> StdinValue:
        """Return standard input of a known kind, for builtins that rewrap what they read

        Args:
            value: The input
            kind: The kind it is in

        Returns:
            The wrapped input
        """
        return StdinValue(value=value, kind=kind)

    async def run_named_command(self, name: str, arguments: list[str], state: ShellState) -> int:
        """Run a command by name with ready-made arguments, writing its output to the current sink

        Args:
            name: The command name, resolved as a function, builtin or registered command
            arguments: Its arguments, already expanded
            state: The shell state to run against

        Returns:
            The command's exit code
        """
        result = await self.dispatch(name, arguments, None, ErrorDestination.STDERR, state)
        await self.drain_to_sink(result, state)
        return result.exit_code

    async def run_bypassing_functions(
        self, name: str, arguments: list[str], stdin: StdinValue | None, state: ShellState
    ) -> int:
        """Run a command the way ``command`` does, ignoring functions and aliases of the same name

        Args:
            name: The command name
            arguments: Its arguments
            stdin: Standard input, or None
            state: The shell state to run against

        Returns:
            The command's exit code
        """
        result = await self.dispatch(name, arguments, stdin, ErrorDestination.STDERR, state, skip_functions=True)
        await self.drain_to_sink(result, state)
        return result.exit_code

    async def apply_assignment(
        self, assignment: Assignment, state: ShellState, run_substitution: RunSubstitution
    ) -> None:
        """Store the value of one assignment word, as a scalar, an array, or one element of an array

        ``name=value`` replaces a scalar, ``name+=value`` appends to it, ``name=(words)`` replaces an array,
        ``name+=(words)`` extends it, and ``name[index]=value`` sets one element, making an array of a scalar

        Args:
            assignment: The assignment as tokenised
            state: The shell state whose variables or arrays change
            run_substitution: Runs a script and returns its output
        Raises:
            ShellError: If the variable is read-only
        """
        name = assignment.name
        if name in state.readonly_names:
            raise ShellError(f"{name}: readonly variable")
        if assignment.array_words is not None:
            values = await expand_words(assignment.array_words, state, run_substitution)
            elements = array_elements(name, state) if assignment.append else {}
            next_index = max(elements, default=-1) + 1
            elements.update({next_index + offset: value for offset, value in enumerate(values)})
            state.variables.pop(name, None)
            state.arrays[name] = elements
            return
        value = await expand_word_unsplit(assignment.value, state, run_substitution)
        if assignment.index_text is not None:
            elements = array_elements(name, state)
            index = await resolve_array_index(
                assignment.index_text, max(elements, default=-1) + 1, state, run_substitution
            )
            if assignment.append:
                value = elements.get(index, "") + value
            elements[index] = value
            state.variables.pop(name, None)
            state.arrays[name] = elements
            return
        if assignment.append and name in state.arrays:
            state.arrays[name][0] = state.arrays[name].get(0, "") + value
            return
        if assignment.append:
            value = state.variables.get(name, "") + value
        state.arrays.pop(name, None)
        state.variables[name] = value

    def take_pending_stdin(self, stdin: StdinValue | None, state: ShellState) -> StdinValue | None:
        """Return the input a command that reads standard input should use

        A command inside a group or function reads whatever was piped or redirected into the group, once

        Args:
            stdin: Input given directly to the command, or None
            state: The shell state holding any input the enclosing command received

        Returns:
            The direct input, else the pending input, else None
        """
        if stdin is not None or state.pending_stdin is None:
            return stdin
        pending = state.pending_stdin
        state.pending_stdin = None
        return pending

    async def dispatch(
        self,
        name: str,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: "ErrorDestination | Path",
        state: ShellState,
        in_pipeline: bool = False,
        attached_to_terminal: bool = False,
        skip_functions: bool = False,
    ) -> ExecutionResult:
        """Run a named command as a function, a builtin, or a registered command

        Args:
            name: The command name
            arguments: The expanded arguments after it
            stdin: Standard input, or None
            error_destination: Where the command's error output goes
            state: The shell state to run against
            in_pipeline: Whether a function call should stream in its own task against a copy of the state
            attached_to_terminal: Whether a registered command's output reaches the terminal unredirected
            skip_functions: Whether a function of the same name is ignored, as ``command`` does

        Returns:
            The command's output and exit code
        """
        if name in state.functions and not skip_functions:
            return await self.call_function(name, arguments, stdin, error_destination, state, in_pipeline)
        builtin = self.builtins.get(name)
        names_a_path = PATH_SEPARATOR in name and builtin is None and self.registry.get(name) is None
        if name in SCRIPT_COMMAND_NAMES or names_a_path:
            return await self.run_script_command(name, arguments, stdin, error_destination, state, in_pipeline)
        if builtin is not None:
            write_error = self.error_sink(error_destination, state, state.output_sink.write_sync)
            with redirected_sinks(state, write_error=write_error):
                return ExecutionResult.empty(await builtin(arguments, stdin, state))
        command = self.registry.get(name)
        if command is None:
            self.error_sink(error_destination, state, state.output_sink.write_sync)(
                f"bash: {name}: command not found\n"
            )
            if stdin is not None:
                await self.discard_stdin(stdin)
            return ExecutionResult.empty(EXIT_CODE_COMMAND_NOT_FOUND)
        if command.input_kinds != frozenset({InputKind.ARGUMENTS}):
            stdin = self.take_pending_stdin(stdin, state)
        return await self.run_registered_command(
            command, arguments, stdin, error_destination, state, attached_to_terminal
        )

    async def run_script_command(
        self,
        name: str,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: "ErrorDestination | Path",
        state: ShellState,
        in_pipeline: bool = False,
    ) -> ExecutionResult:
        """Run a script named by ``bash``, ``sh``, ``source``, ``.`` or by its own path

        ``bash`` and ``sh`` run the script against a copy of the state, taking it from a file, from the text
        after ``-c``, or from standard input when no file is named. ``source`` and ``.`` run a file against the
        live state. A command name holding a slash runs that file as ``bash`` would

        Args:
            name: The command name, or the path of a script
            arguments: The words after it
            stdin: Standard input, which is the script when ``bash`` names none, otherwise the script's own input
            error_destination: Where error output goes
            state: The shell state to run against
            in_pipeline: Whether the command is a pipeline stage, so its output streams from its own task

        Returns:
            The script's output and exit code; a missing file gives 127, or 1 when sourced, and a directory 126
        """
        write_error = self.error_sink(error_destination, state, state.output_sink.write_sync)
        stdin = self.take_pending_stdin(stdin, state)
        is_shell = name in SHELL_COMMAND_NAMES
        is_sourced = name in SOURCE_COMMAND_NAMES
        script_text: str | None = None
        path_text = name
        positional = arguments
        if is_shell and arguments[:1] == [INLINE_SCRIPT_OPTION]:
            if len(arguments) == 1:
                write_error(f"bash: {INLINE_SCRIPT_OPTION}: option requires an argument\n")
                return await self.fail_script_command(stdin, EXIT_CODE_USAGE_ERROR)
            script_text, positional = arguments[1], arguments[3:]
        elif is_shell and not arguments:
            script_text = "" if stdin is None else await materialise_text(stdin.value, stdin.kind)
            stdin, positional = None, []
        elif is_shell and arguments[0].startswith("-"):
            write_error(f"bash: {arguments[0]}: invalid option\n")
            return await self.fail_script_command(stdin, EXIT_CODE_USAGE_ERROR)
        elif is_sourced and not arguments:
            write_error(f"bash: {name}: filename argument required\n")
            return await self.fail_script_command(stdin, EXIT_CODE_USAGE_ERROR)
        elif is_shell or is_sourced:
            path_text, positional = arguments[0], arguments[1:]
        if script_text is None:
            path = state.resolve_path(path_text)
            if not path.is_file():
                reason = "Is a directory" if path.is_dir() else "No such file or directory"
                write_error(f"bash: {path_text}: {reason}\n")
                exit_code = EXIT_CODE_COMMAND_NOT_FOUND
                if is_sourced:
                    exit_code = EXIT_CODE_FAILURE
                elif path.is_dir():
                    exit_code = EXIT_CODE_NOT_EXECUTABLE
                return await self.fail_script_command(stdin, exit_code)
            try:
                script_text = path.read_text(encoding=TEXT_ENCODING)
            except (OSError, UnicodeDecodeError) as error:
                write_error(f"bash: {path_text}: {error}\n")
                return await self.fail_script_command(stdin, EXIT_CODE_NOT_EXECUTABLE)
        body_text = script_text

        async def run_sourced(inner_state: ShellState) -> int:
            try:
                return await self.run_script(body_text, inner_state)
            except ReturnFromFunction as returned:
                return returned.exit_code

        async def run_separately(inner_state: ShellState) -> int:
            return await self.run_subshell_script(body_text, inner_state)

        if is_sourced and not in_pipeline:
            saved_positional = state.positional_arguments
            if positional:
                state.positional_arguments = positional
            state.function_depth += 1
            try:
                return await self.execute_compound(
                    run_sourced, state, stdin, [], False, error_destination=error_destination
                )
            finally:
                state.positional_arguments = saved_positional
                state.function_depth -= 1
        script_state = state.copy()
        if is_sourced:
            script_state.function_depth += 1
            if positional:
                script_state.positional_arguments = positional
        else:
            script_state.positional_arguments = positional
            script_state.loop_depth = 0
            script_state.function_depth = 0
        run_body = run_sourced if is_sourced else run_separately
        if in_pipeline:
            return await self.stream_compound(
                run_body, script_state, stdin, [], merge_stderr=False, error_destination=error_destination
            )
        return await self.execute_compound(
            run_body, script_state, stdin, [], False, error_destination=error_destination
        )

    async def fail_script_command(self, stdin: StdinValue | None, exit_code: int) -> ExecutionResult:
        """Return a failed result for a script that could not start, stopping whatever was piped into it

        Args:
            stdin: Standard input nobody will read, or None
            exit_code: The exit code to report

        Returns:
            An empty result with the exit code
        """
        if stdin is not None:
            await self.discard_stdin(stdin)
        return ExecutionResult.empty(exit_code)

    async def call_function(
        self,
        name: str,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: "ErrorDestination | Path",
        state: ShellState,
        in_pipeline: bool = False,
    ) -> ExecutionResult:
        """Run a shell function with its own positional arguments and a fresh loop scope

        As a pipeline stage the function runs in its own task against a copy of the state, as bash runs it in a
        subshell, and its output streams to the next stage

        Args:
            name: The function name
            arguments: The positional arguments for the call
            stdin: Standard input the function's commands may consume, or None
            error_destination: Where the function's error output goes
            state: The shell state to run against
            in_pipeline: Whether the call is a pipeline stage

        Returns:
            The captured or streamed output and the function's exit code
        """
        body_text = state.functions[name]

        async def run_body(inner_state: ShellState) -> int:
            try:
                return await self.run_script(body_text, inner_state)
            except ReturnFromFunction as returned:
                return returned.exit_code

        if in_pipeline:
            stage_state = state.copy()
            stage_state.positional_arguments = arguments
            stage_state.loop_depth = 0
            stage_state.function_depth += 1
            stage_state.local_scopes.append({})
            return await self.stream_compound(
                run_body, stage_state, stdin, [], merge_stderr=False, error_destination=error_destination
            )
        saved_positional = state.positional_arguments
        saved_loop_depth = state.loop_depth
        state.positional_arguments = arguments
        state.loop_depth = 0
        state.function_depth += 1
        state.local_scopes.append({})
        try:
            return await self.execute_compound(run_body, state, stdin, [], False, error_destination=error_destination)
        finally:
            restore_local_scope(state.local_scopes.pop(), state)
            state.positional_arguments = saved_positional
            state.loop_depth = saved_loop_depth
            state.function_depth -= 1

    async def run_registered_command(
        self,
        command: Command,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: "ErrorDestination | Path",
        state: ShellState,
        attached_to_terminal: bool = False,
    ) -> ExecutionResult:
        """Run a registered command with its input converted to a kind it accepts

        Args:
            command: The command object
            arguments: The expanded arguments
            stdin: Standard input, or None
            error_destination: Where the command's error output goes
            state: The shell state to run against
            attached_to_terminal: Whether the command's output reaches the terminal unredirected

        Returns:
            The command's output in its preferred kind, with errors interleaved when they join standard output
        """
        if stdin is None or command.input_kinds == frozenset({InputKind.ARGUMENTS}):
            if stdin is not None:
                await self.discard_stdin(stdin)
            stdin_value, stdin_kind = None, InputKind.ARGUMENTS
        else:
            _, stdin_kind = choose_kinds(frozenset({stdin.kind}), command.input_kinds)
            stdin_value = await convert(stdin.value, stdin.kind, OutputKind(stdin_kind))
        stdout_kind = next(kind for kind in KIND_PREFERENCE if kind in command.output_kinds)
        error_buffer: list[str] = []
        merge_into_stdout = error_destination == ErrorDestination.STDOUT
        write_error = error_buffer.append if merge_into_stdout else self.error_sink(error_destination, state, None)
        invocation_state = state
        if write_error is not state.write_error:
            invocation_state = dataclasses.replace(state, write_error=write_error)
            invocation_state.output_sink = state.output_sink
        invocation = CommandInvocation(
            arguments=arguments,
            stdin=stdin_value,
            stdin_kind=stdin_kind,
            stdout_kind=stdout_kind,
            state=invocation_state,
            attached_to_terminal=attached_to_terminal,
        )
        command_result = command.run(invocation)
        if inspect.isawaitable(command_result):
            command_result = await command_result
        stdout: Any = command_result.stdout
        if stdout_kind in (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES):
            stream: Any = stdout
            if merge_into_stdout:
                stream = interleave_errors(stream, error_buffer, encode=stdout_kind == OutputKind.STREAM_BYTES)
            if stdout_kind == OutputKind.STREAM_TEXT:
                invocation.exit_status.code = command_result.exit_code
                stdout = TextStream(stream, exit_status=invocation.exit_status)
            else:
                stdout = as_async_iterator(stream)
        elif merge_into_stdout and error_buffer:
            errors = "".join(error_buffer)
            stdout = errors.encode(TEXT_ENCODING) + stdout if stdout_kind == OutputKind.BYTES else errors + stdout
        return ExecutionResult(stdout=stdout, kind=stdout_kind, exit_code=command_result.exit_code)

    async def discard_stdin(self, stdin: StdinValue) -> None:
        """Stop a producer whose output nobody will read

        Args:
            stdin: The unread input
        """
        if stdin.kind in (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES):
            await close_iterator(stdin.value)

    async def error_destination(
        self, redirections: list[Redirection], state: ShellState, merge_stderr: bool
    ) -> "ErrorDestination | Path":
        """Return where a command's error output goes after its redirections are applied in order

        Args:
            redirections: The command's redirections
            state: The shell state for expansion and path resolution
            merge_stderr: Whether error output joins standard output before any redirection applies

        Returns:
            Standard error, the command's standard output, the enclosing sink, the null device, or a file to
            append to, following where standard output pointed at the moment ``2>&1`` was applied
        """
        destination: ErrorDestination | Path = ErrorDestination.STDOUT if merge_stderr else ErrorDestination.STDERR
        stdout_target: ErrorDestination | Path = ErrorDestination.STDOUT
        for redirection in redirections:
            if redirection.kind in (RedirectionKind.WRITE_STDOUT, RedirectionKind.APPEND_STDOUT):
                path = await self.redirection_path(redirection, state)
                stdout_target = ErrorDestination.DISCARD if path is None else path
                if destination == ErrorDestination.STDOUT:
                    destination = ErrorDestination.SINK_STDOUT
            elif redirection.kind == RedirectionKind.STDERR_TO_STDOUT:
                destination = stdout_target
                if isinstance(destination, Path):
                    destination.write_text("", encoding="utf-8")
            elif redirection.kind == RedirectionKind.WRITE_BOTH:
                path = await self.redirection_path(redirection, state)
                if path is None:
                    destination = ErrorDestination.DISCARD
                else:
                    path.write_text("", encoding="utf-8")
                    destination = path
            elif redirection.kind in (RedirectionKind.WRITE_STDERR, RedirectionKind.APPEND_STDERR):
                path = await self.redirection_path(redirection, state)
                if path is None:
                    destination = ErrorDestination.DISCARD
                    continue
                if redirection.kind == RedirectionKind.WRITE_STDERR:
                    path.write_text("", encoding="utf-8")
                destination = path
        return destination

    def error_sink(
        self, destination: "ErrorDestination | Path", state: ShellState, stdout_sink: Callable[[str], None] | None
    ) -> Callable[[str], None]:
        """Return the function error output should be written through

        Args:
            destination: Where the errors go
            state: The shell state holding the standard sinks
            stdout_sink: The function standing in for standard output, or None when errors cannot join it

        Returns:
            A function taking text
        """
        if destination == ErrorDestination.STDERR:
            return state.write_error
        if destination == ErrorDestination.DISCARD:
            return discard_text
        if destination == ErrorDestination.STDOUT:
            return stdout_sink if stdout_sink is not None else state.output_sink.write_sync
        if destination == ErrorDestination.SINK_STDOUT:
            return state.output_sink.write_sync
        return file_appender(destination)

    async def redirection_path(self, redirection: Redirection, state: ShellState) -> Path | None:
        """Return the file a redirection names, or None for the null device

        Args:
            redirection: A redirection with a file target
            state: The shell state for expansion and path resolution

        Returns:
            The absolute path, or None when output should be discarded
        """
        target = await expand_raw_word(redirection.target, state, self.substitution_runner(state))
        if target == NULL_DEVICE_PATH:
            return None
        return state.resolve_path(target)

    async def apply_input_redirections(
        self, stdin: StdinValue | None, redirections: list[Redirection], state: ShellState
    ) -> StdinValue | None:
        """Return the standard input after ``<``, heredocs and here-strings are applied

        Args:
            stdin: Standard input from a pipeline, or None
            redirections: The command's redirections
            state: The shell state for expansion and path resolution

        Returns:
            The input the command should read, or None when it has none
        """
        for redirection in redirections:
            if redirection.kind == RedirectionKind.READ_STDIN:
                path = await self.redirection_path(redirection, state)
                if path is None:
                    stdin = StdinValue(value="", kind=OutputKind.TEXT)
                    continue
                try:
                    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
                        text = handle.read()
                except FileNotFoundError as error:
                    raise ShellError(f"{redirection.target}: No such file or directory") from error
                stdin = StdinValue(value=text, kind=OutputKind.TEXT)
            elif redirection.kind == RedirectionKind.HEREDOC:
                body = redirection.target
                if redirection.expand_target:
                    body = await expand_text(body, state, self.substitution_runner(state), in_double_quotes=True)
                stdin = StdinValue(value=body, kind=OutputKind.TEXT)
            elif redirection.kind == RedirectionKind.HERE_STRING:
                text = await expand_raw_word(redirection.target, state, self.substitution_runner(state))
                stdin = StdinValue(value=text + "\n", kind=OutputKind.TEXT)
        return stdin

    async def apply_output_redirections(
        self,
        result: ExecutionResult,
        redirections: list[Redirection],
        state: ShellState,
        error_destination: "ErrorDestination | Path | None" = None,
        merge_stderr: bool = False,
    ) -> ExecutionResult:
        """Write a result to the file its ``>``, ``>>`` or ``&>`` names, or to standard error for ``>&2``

        Every file named by an earlier ``>`` is created and emptied as well, as bash does when it opens them in turn

        Args:
            result: The result to redirect
            redirections: The command's redirections
            state: The shell state for expansion and path resolution
            error_destination: Where errors went, so a file already holding them is appended to rather than replaced
            merge_stderr: Whether error output joined standard output before the redirections, as after ``|&``

        Returns:
            The result unchanged when no output redirection applies, otherwise an empty result with its exit code
        """
        target, append, redirected = await self.trace_stdout_target(redirections, state, merge_stderr)
        if not redirected:
            return result
        text = await materialise_text(result.stdout, result.kind)
        if target is None:
            return ExecutionResult(stdout=text, kind=OutputKind.TEXT, exit_code=result.exit_code)
        if target == ErrorDestination.STDERR:
            if text:
                state.write_error(text)
        elif isinstance(target, Path):
            shares_file_with_errors = isinstance(error_destination, Path) and error_destination == target
            keep_existing = (append or shares_file_with_errors) and target.exists()
            existing = ""
            if keep_existing:
                with target.open(encoding="utf-8", newline="") as handle:
                    existing = handle.read()
            target.write_text(existing + text, encoding="utf-8", newline="")
        return ExecutionResult.empty(result.exit_code)

    async def trace_stdout_target(
        self, redirections: list[Redirection], state: ShellState, merge_stderr: bool
    ) -> tuple["ErrorDestination | Path | None", bool, bool]:
        """Return where standard output ends up once the redirections are applied in order

        ``>&2`` points standard output wherever standard error pointed at that moment, so the two are
        followed together. Every file named by an earlier ``>`` is created and emptied, as bash does

        Args:
            redirections: The command's redirections
            state: The shell state for expansion and path resolution
            merge_stderr: Whether error output joined standard output before any redirection

        Returns:
            The target (None for the enclosing sink, a file, the null device, or standard error), whether
            a file is appended to, and whether any output redirection was written at all
        """
        stdout_target: ErrorDestination | Path | None = None
        error_target: ErrorDestination | Path = ErrorDestination.STDOUT if merge_stderr else ErrorDestination.STDERR
        append = False
        redirected = False
        for redirection in redirections:
            if redirection.kind in (
                RedirectionKind.WRITE_STDOUT,
                RedirectionKind.APPEND_STDOUT,
                RedirectionKind.WRITE_BOTH,
            ):
                if isinstance(stdout_target, Path) and not append:
                    stdout_target.write_text("", encoding="utf-8")
                path = await self.redirection_path(redirection, state)
                stdout_target = ErrorDestination.DISCARD if path is None else path
                append = redirection.kind == RedirectionKind.APPEND_STDOUT
                redirected = True
                if redirection.kind == RedirectionKind.WRITE_BOTH:
                    error_target = stdout_target
                elif error_target == ErrorDestination.STDOUT:
                    error_target = ErrorDestination.SINK_STDOUT
            elif redirection.kind == RedirectionKind.STDERR_TO_STDOUT:
                error_target = ErrorDestination.STDOUT if stdout_target is None else stdout_target
            elif redirection.kind in (RedirectionKind.WRITE_STDERR, RedirectionKind.APPEND_STDERR):
                path = await self.redirection_path(redirection, state)
                error_target = ErrorDestination.DISCARD if path is None else path
            elif redirection.kind == RedirectionKind.STDOUT_TO_STDERR:
                redirected = True
                if error_target in (ErrorDestination.STDOUT, ErrorDestination.SINK_STDOUT):
                    stdout_target = None
                else:
                    stdout_target = error_target
                    append = True
        return stdout_target, append, redirected

    async def builtin_cd(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Change the current directory

        Args:
            arguments: The target directory, ``-`` for the previous one, or nothing for home
            stdin: Ignored
            state: The shell state whose directory changes

        Returns:
            Zero on success, one when the directory does not exist
        """
        if not arguments:
            target_text = state.variables.get(HOME_VARIABLE_NAME, str(Path.home()))
        elif arguments[0] == "-":
            if PREVIOUS_DIRECTORY_VARIABLE_NAME not in state.variables:
                state.write_error("bash: cd: OLDPWD not set\n")
                return EXIT_CODE_FAILURE
            target_text = state.variables[PREVIOUS_DIRECTORY_VARIABLE_NAME]
        else:
            target_text = arguments[0]
        target = state.resolve_path(target_text)
        if not target.is_dir():
            state.write_error(f"bash: cd: {target_text}: No such file or directory\n")
            return EXIT_CODE_FAILURE
        self.change_directory(target, state)
        if arguments[:1] == ["-"]:
            await state.output_sink.write(f"{state.cwd.as_posix()}\n")
        return EXIT_CODE_SUCCESS

    def change_directory(self, target: Path, state: ShellState) -> None:
        """Move the shell into a directory, keeping ``OLDPWD`` and ``PWD`` up to date

        Args:
            target: The directory, which must exist
            state: The shell state whose directory changes
        """
        state.variables[PREVIOUS_DIRECTORY_VARIABLE_NAME] = str(state.cwd)
        state.cwd = target.resolve()
        state.variables[CURRENT_DIRECTORY_VARIABLE_NAME] = str(state.cwd)

    async def builtin_export(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Mark variables for export, setting those given as ``name=value``

        Args:
            arguments: The assignments, or bare names which keep their value
            stdin: Ignored
            state: The shell state whose variables change

        Returns:
            Zero
        """
        for argument in arguments:
            name, separator, value = argument.partition("=")
            if separator:
                state.variables[name] = value
            state.exported_names.add(name)
        return EXIT_CODE_SUCCESS

    async def builtin_unset(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Remove variables and functions by name

        Args:
            arguments: The names to remove, after any ``-f`` or ``-v`` option
            stdin: Ignored
            state: The shell state to change

        Returns:
            Zero
        """
        for name in arguments:
            if name.startswith("-"):
                continue
            element_match = ARRAY_ELEMENT_PATTERN.match(name)
            if element_match is not None:
                elements = state.arrays.get(element_match.group(1), {})
                index = await resolve_array_index(
                    element_match.group(2), max(elements, default=-1) + 1, state, self.substitution_runner(state)
                )
                elements.pop(index, None)
                continue
            state.variables.pop(name, None)
            state.arrays.pop(name, None)
            state.functions.pop(name, None)
            state.exported_names.discard(name)
        return EXIT_CODE_SUCCESS

    async def builtin_exit(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Stop the script

        Args:
            arguments: An optional exit code
            stdin: Ignored
            state: The shell state holding the last exit code used by default

        Raises:
            ExitShell: Always
        """
        raise ExitShell(parse_exit_code(arguments, state))

    async def builtin_return(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Leave the current function, or complain when there is none

        Args:
            arguments: An optional exit code
            stdin: Ignored
            state: The shell state holding the last exit code used by default

        Raises:
            ReturnFromFunction: When called inside a function

        Returns:
            One when called outside any function
        """
        if state.function_depth == 0:
            state.write_error("bash: return: can only `return' from a function or sourced script\n")
            return EXIT_CODE_FAILURE
        raise ReturnFromFunction(parse_exit_code(arguments, state))

    async def builtin_break(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Leave the innermost loop, or complain when there is none

        Args:
            arguments: Ignored
            stdin: Ignored
            state: The shell state tracking loop depth

        Raises:
            BreakLoop: When called inside a loop

        Returns:
            Zero when called outside any loop
        """
        if state.loop_depth == 0:
            state.write_error("bash: break: only meaningful in a `for', `while', or `until' loop\n")
            return EXIT_CODE_SUCCESS
        raise BreakLoop()

    async def builtin_continue(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Start the next iteration of the innermost loop, or complain when there is none

        Args:
            arguments: Ignored
            stdin: Ignored
            state: The shell state tracking loop depth

        Raises:
            ContinueLoop: When called inside a loop

        Returns:
            Zero when called outside any loop
        """
        if state.loop_depth == 0:
            state.write_error("bash: continue: only meaningful in a `for', `while', or `until' loop\n")
            return EXIT_CODE_SUCCESS
        raise ContinueLoop()

    async def builtin_wait(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Wait for background jobs to finish and remove them from the table

        Args:
            arguments: The pids to wait for, or none for every job
            stdin: Ignored
            state: The shell state holding the job table

        Returns:
            The exit code of the last job waited for, zero when there was none, 127 for an unknown pid
        """
        if arguments:
            jobs: list[Job | None] = [
                state.job_table.job_for_spec(argument)
                if argument.startswith("%")
                else state.job_table.jobs.get(int(argument))
                if argument.isdigit()
                else None
                for argument in arguments
            ]
        else:
            jobs = list(state.job_table.jobs.values())
        exit_code = EXIT_CODE_SUCCESS
        for job in jobs:
            if job is None:
                exit_code = EXIT_CODE_COMMAND_NOT_FOUND
                continue
            await asyncio.wait({job.task})
            exit_code = job.exit_code
            state.job_table.jobs.pop(job.pid, None)
        return exit_code

    async def builtin_jobs(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """List background jobs the way bash does

        Args:
            arguments: Ignored
            stdin: Ignored
            state: The shell state holding the job table

        Returns:
            Zero
        """
        jobs = list(state.job_table.jobs.values())
        for job_number, job in enumerate(jobs, start=1):
            status = JOB_STATUS_WORDS[job.status]
            if job.status == JobStatus.DONE and job.exit_code != EXIT_CODE_SUCCESS:
                status = f"Exit {job.exit_code}"
            marker = "+" if job_number == len(jobs) else "-" if job_number == len(jobs) - 1 else " "
            suffix = " &" if job.status == JobStatus.RUNNING else ""
            await state.output_sink.write(
                f"[{job_number}]{marker}  {status:<{JOB_STATUS_COLUMN_WIDTH}}{job.command_text}{suffix}\n"
            )
        return EXIT_CODE_SUCCESS

    async def builtin_no_op(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Do nothing successfully

        Args:
            arguments: Ignored
            stdin: Ignored
            state: Ignored

        Returns:
            Zero
        """
        return EXIT_CODE_SUCCESS


def split_case_patterns(patterns_text: str) -> list[str]:
    """Return the alternatives of a case pattern list, split at the bars outside quotes

    Args:
        patterns_text: The text before the clause's closing parenthesis

    Returns:
        Each pattern with surrounding whitespace removed
    """
    patterns: list[str] = []
    current = ""
    index = 0
    while index < len(patterns_text):
        character = patterns_text[index]
        if character == "\\" and index + 1 < len(patterns_text):
            current += patterns_text[index : index + 2]
            index += 2
            continue
        if character in "'\"":
            closing = patterns_text.find(character, index + 1)
            closing = len(patterns_text) - 1 if closing == -1 else closing
            current += patterns_text[index : closing + 1]
            index = closing + 1
            continue
        if character == "|":
            patterns.append(current.strip())
            current = ""
        else:
            current += character
        index += 1
    patterns.append(current.strip())
    return patterns


def trace_assignment(assignment: Assignment) -> str:
    """Return an assignment the way ``set -x`` shows it

    Args:
        assignment: The assignment as tokenised

    Returns:
        ``name=value``, or ``name=(words)`` for an array
    """
    operator = "+=" if assignment.append else "="
    if assignment.array_words is not None:
        inner = " ".join(word.raw_text() for word in assignment.array_words)
        return f"{assignment.name}{operator}({inner})"
    subscript = f"[{assignment.index_text}]" if assignment.index_text is not None else ""
    return f"{assignment.name}{subscript}{operator}{assignment.value.raw_text()}"


def select_choice(reply: str, values: list[str]) -> str:
    """Return the word a select reply picks, or nothing when it is not a whole number in range

    Args:
        reply: The line typed at the prompt
        values: The words on the menu

    Returns:
        The chosen word, or an empty string
    """
    if INTEGER_REPLY_PATTERN.match(reply) is None:
        return ""
    number = int(reply)
    return values[number - 1] if 1 <= number <= len(values) else ""


def select_menu_width(state: ShellState) -> int:
    """Return the terminal width the select menu is laid out for

    Args:
        state: The shell state holding ``COLUMNS`` when the host set it

    Returns:
        The width in characters
    """
    columns_text = state.variables.get(COLUMNS_VARIABLE_NAME, "")
    return int(columns_text) if columns_text.isdigit() and int(columns_text) > 0 else DEFAULT_TERMINAL_WIDTH


def format_select_menu(values: list[str], width: int) -> str:
    """Return the numbered menu bash prints for a select loop, laid out in columns the way bash does

    Args:
        values: The words on the menu
        width: The terminal width to fit the columns into

    Returns:
        The menu text, ending in a newline
    """
    if not values:
        return "\n"
    count = len(values)
    index_width = len(str(count))
    cell_width = max(len(value) for value in values) + index_width + SELECT_INDEX_SUFFIX_LENGTH + SELECT_CELL_GAP
    column_count = max(width // cell_width, 1)
    row_count = count // column_count + (count % column_count != 0)
    column_count = count // row_count + (count % row_count != 0)
    if row_count == 1:
        row_count, column_count = column_count, 1
    first_column_index_width = len(str(row_count))
    lines: list[str] = []
    for row in range(row_count):
        index = row
        position = 0
        pieces: list[str] = []
        while True:
            current_index_width = first_column_index_width if position == 0 else index_width
            cell = f"{index + 1:>{current_index_width}}) {values[index]}"
            pieces.append(cell)
            index += row_count
            if index >= count:
                break
            pieces.append(select_menu_indent(position + len(cell), position + cell_width))
            position += cell_width
        lines.append("".join(pieces) + "\n")
    return "".join(lines)


def select_menu_indent(start: int, end: int) -> str:
    """Return the blanks that move from one column position to another, using tabs where bash does

    Args:
        start: The column position after the cell just printed
        end: The column position of the next cell

    Returns:
        Tabs and spaces
    """
    pieces: list[str] = []
    position = start
    while position < end:
        if end // TAB_WIDTH > position // TAB_WIDTH:
            pieces.append("\t")
            position += TAB_WIDTH - position % TAB_WIDTH
        else:
            pieces.append(" ")
            position += 1
    return "".join(pieces)


def restore_temporary_assignments(
    saved_variables: dict[str, str | None],
    saved_arrays: dict[str, dict[int, str] | None],
    temporarily_exported: set[str],
    state: ShellState,
) -> None:
    """Put back the variables and arrays a command's temporary assignments replaced and drop their export marks

    Args:
        saved_variables: Each assigned name with the scalar it held before, None when it held none
        saved_arrays: Each assigned name with the array it held before, None when it held none
        temporarily_exported: The assigned names that were not exported before the command
        state: The shell state to restore
    """
    for name, value in saved_variables.items():
        if value is None:
            state.variables.pop(name, None)
        else:
            state.variables[name] = value
    for name, elements in saved_arrays.items():
        if elements is None:
            state.arrays.pop(name, None)
        else:
            state.arrays[name] = elements
    state.exported_names.difference_update(temporarily_exported)


def restore_local_scope(scope: dict[str, tuple[str | None, dict[int, str] | None]], state: ShellState) -> None:
    """Put back the variables a function declared local, as they were before it ran

    Args:
        scope: Each local name with the scalar and array values it had before, None when it had none
        state: The shell state to restore
    """
    for name, (value, elements) in scope.items():
        state.variables.pop(name, None)
        state.arrays.pop(name, None)
        if value is not None:
            state.variables[name] = value
        if elements is not None:
            state.arrays[name] = elements


def record_job_outcome(job: Job, task: asyncio.Task) -> None:
    """Update a job's status and exit code once its task has finished

    Args:
        job: The job to update
        task: Its finished task
    """
    if task.cancelled():
        job.status = JobStatus.KILLED
        job.exit_code = EXIT_CODE_KILLED
        return
    job.status = JobStatus.DONE
    exception = task.exception()
    job.exit_code = EXIT_CODE_FAILURE if exception is not None else task.result()


def parse_exit_code(arguments: list[str], state: ShellState) -> int:
    """Return the exit code named by a builtin's first argument, or the last exit code

    Args:
        arguments: The builtin's arguments
        state: The shell state holding the last exit code

    Returns:
        The exit code
    """
    if not arguments:
        return state.last_exit_code
    try:
        return int(arguments[0]) % EXIT_CODE_MODULUS
    except ValueError:
        state.write_error(f"bash: {arguments[0]}: numeric argument required\n")
        return EXIT_CODE_USAGE_ERROR


def file_appender(path: Path) -> Callable[[str], None]:
    """Return a sink that appends text to one file

    Args:
        path: The file to append to

    Returns:
        A function writing text to the end of the file
    """

    def append(text: str) -> None:
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    return append


class ShellRunner:
    """Drive the async executor from synchronous code on one long-lived event loop, so jobs outlive a call"""

    def __init__(
        self, registry: CommandRegistry | None = None, output_limit_characters: int = DEFAULT_OUTPUT_LIMIT_CHARACTERS
    ):
        """Create a runner with its own event loop

        Args:
            registry: The commands available to scripts
            output_limit_characters: The most output a captured substitution or redirected group may produce
        """
        self.executor = Executor(registry, output_limit_characters)
        self.runner = asyncio.Runner()

    def run(self, script: str, state: ShellState) -> int:
        """Run a script to completion, leaving background jobs to continue on the next call

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            The exit code of the script
        """
        return self.runner.run(self.executor.execute_script(script, state))

    def close(self) -> None:
        """Cancel any remaining jobs and close the loop"""
        self.runner.close()


def run_script(script: str, state: ShellState, registry: CommandRegistry | None = None) -> int:
    """Run a script against a state from synchronous code, on CPython rather than pyodide

    Args:
        script: The script text
        state: The shell state to run against
        registry: The commands available, defaulting to everything the package ships

    Returns:
        The exit code of the script
    """
    runner = ShellRunner(registry)
    try:
        return runner.run(script, state)
    finally:
        runner.close()


async def run_script_async(script: str, state: ShellState, registry: CommandRegistry | None = None) -> int:
    """Run a script against a state from an already running event loop, as under pyodide

    Args:
        script: The script text
        state: The shell state to run against
        registry: The commands available, defaulting to everything the package ships

    Returns:
        The exit code of the script
    """
    return await Executor(registry).run_script_async(script, state)
