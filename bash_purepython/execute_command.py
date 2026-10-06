"""Run plan nodes: parse a script, build each block's plan, execute it, and recurse into the scripts it contains"""

# Standard libraries
import dataclasses
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

# Project libraries
from bash_purepython.block_parser import build_plan
from bash_purepython.command.command import Command, CommandInvocation, InputKind, OutputKind
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.parse_script import split_script_into_connected_commands
from bash_purepython.shell_state import (
    EXIT_CODE_BROKEN_PIPE,
    EXIT_CODE_COMMAND_NOT_FOUND,
    EXIT_CODE_FAILURE,
    EXIT_CODE_MODULUS,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_USAGE_ERROR,
    NULL_DEVICE_PATH,
    BreakLoop,
    ContinueLoop,
    ControlFlowSignal,
    ExitShell,
    ExpansionError,
    OutputLimitExceededError,
    ReturnFromFunction,
    ShellError,
    ShellState,
    ShellSyntaxError,
)
from bash_purepython.streams import KIND_PREFERENCE, TEXT_ENCODING, TextStream, choose_kinds, convert, materialise_text
from bash_purepython.words import (
    expand_raw_word,
    expand_text,
    expand_word_unsplit,
    expand_words,
    tokenize_simple_command,
)
from bash_purepython.workflow import (
    AndOrListNode,
    BackgroundNode,
    BraceGroupNode,
    ForNode,
    FunctionDefinitionNode,
    IfNode,
    ListOperator,
    PipelineNode,
    PlanNode,
    Redirection,
    RedirectionKind,
    SimpleCommandNode,
    SubshellNode,
    UntilNode,
    WhileNode,
)

PREVIOUS_DIRECTORY_VARIABLE_NAME = "OLDPWD"
CURRENT_DIRECTORY_VARIABLE_NAME = "PWD"
HOME_VARIABLE_NAME = "HOME"
NO_OP_BUILTIN_NAME = ":"
DEFAULT_OUTPUT_LIMIT_CHARACTERS = 16 << 20
OUTPUT_REDIRECTION_KINDS = frozenset(
    {RedirectionKind.WRITE_STDOUT, RedirectionKind.APPEND_STDOUT, RedirectionKind.WRITE_BOTH}
)


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

    def __call__(self, script: str) -> str:
        """Run a script and return its output with trailing newlines removed

        Args:
            script: The substituted script text

        Returns:
            The captured standard output
        """
        output, self.last_exit_code = self.executor.capture_script(script, self.state)
        return output.rstrip("\n")


@contextmanager
def redirected_sinks(
    state: ShellState,
    write_output: Callable[[str], None] | None = None,
    write_error: Callable[[str], None] | None = None,
) -> Generator[None, None, None]:
    """Swap the state's sinks for the duration of a block

    Args:
        state: The live shell state
        write_output: A replacement standard output sink, or None to keep the current one
        write_error: A replacement standard error sink, or None to keep the current one
    """
    saved_output, saved_error = state.write_output, state.write_error
    if write_output is not None:
        state.write_output = write_output
    if write_error is not None:
        state.write_error = write_error
    try:
        yield
    finally:
        state.write_output, state.write_error = saved_output, saved_error


def discard_text(text: str) -> None:
    """Drop text sent to the null device

    Args:
        text: Ignored
    """


class LimitedCollector:
    """Collect captured output, refusing to grow past a limit"""

    def __init__(self, limit_characters: int):
        """Start empty

        Args:
            limit_characters: The most text to hold before raising
        """
        self.pieces: list[str] = []
        self.size = 0
        self.limit_characters = limit_characters

    def append(self, text: str) -> None:
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


def interleave_errors(
    stream: Iterator[str], error_buffer: list[str], encode: bool = False
) -> Generator[Any, None, int]:
    """Yield a command's output with the errors it wrote so far placed before each chunk

    Args:
        stream: The command's standard output
        error_buffer: Where the command's error sink collects text
        encode: Whether the stream carries bytes, so buffered errors are encoded to match

    Returns:
        The exit code the stream returned
    """
    exit_code = EXIT_CODE_SUCCESS

    def flush() -> Any:
        text = "".join(error_buffer)
        error_buffer.clear()
        return text.encode(TEXT_ENCODING) if encode else text

    try:
        while True:
            try:
                chunk = next(stream)
            except StopIteration as stop:
                if isinstance(stop.value, int):
                    exit_code = stop.value
                break
            if error_buffer:
                yield flush()
            yield chunk
        if error_buffer:
            yield flush()
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()
    return exit_code


class Executor:
    """Run scripts against a shell state using one registry of commands"""

    def __init__(
        self, registry: CommandRegistry | None = None, output_limit_characters: int = DEFAULT_OUTPUT_LIMIT_CHARACTERS
    ):
        """Create an executor

        Args:
            registry: The commands available to scripts, defaulting to everything the package ships
            output_limit_characters: The most output a captured group or function may produce
        """
        self.registry = registry if registry is not None else CommandRegistry()
        self.output_limit_characters = output_limit_characters
        self.builtins: dict[str, Callable[[list[str], StdinValue | None, ShellState], int]] = {
            "cd": self.builtin_cd,
            "export": self.builtin_export,
            "unset": self.builtin_unset,
            "exit": self.builtin_exit,
            "return": self.builtin_return,
            "break": self.builtin_break,
            "continue": self.builtin_continue,
            NO_OP_BUILTIN_NAME: self.builtin_no_op,
        }

    def execute_script(self, script: str, state: ShellState) -> int:
        """Run a whole script as the outermost entry point, so exit stops it and stray signals are swallowed

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            The exit code of the script
        """
        try:
            return self.run_script(script, state)
        except ExitShell as exit_shell:
            state.last_exit_code = exit_shell.exit_code
        except ControlFlowSignal:
            pass
        return state.last_exit_code

    def run_script(self, script: str, state: ShellState) -> int:
        """Parse a script into blocks and run each one, writing its output to the state's sink

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            The exit code of the last block
        """
        for block in split_script_into_connected_commands(script):
            try:
                node = build_plan(block)
                result = self.execute_node(node, state, stdin=None, direct_output=True)
                self.drain_to_sink(result, state)
            except ShellSyntaxError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = EXIT_CODE_USAGE_ERROR
                return state.last_exit_code
            except ExpansionError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = EXIT_CODE_FAILURE
                return state.last_exit_code
            except ShellError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = EXIT_CODE_FAILURE
                continue
            state.last_exit_code = result.exit_code
        return state.last_exit_code

    def run_subshell_script(self, script: str, state: ShellState) -> int:
        """Run a script as a subshell body, where exit only leaves the subshell

        Args:
            script: The script text
            state: The subshell's own state

        Returns:
            The exit code of the script, or the code passed to exit
        """
        try:
            return self.run_script(script, state)
        except ExitShell as exit_shell:
            return exit_shell.exit_code
        except (BreakLoop, ContinueLoop):
            return state.last_exit_code

    def capture_script(self, script: str, state: ShellState) -> tuple[str, int]:
        """Run a script with its standard output collected, for command substitution

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            Everything the script wrote to standard output, and its exit code
        """
        pieces: list[str] = []
        with redirected_sinks(state, write_output=pieces.append):
            exit_code = self.run_subshell_script(script, state)
        return "".join(pieces), exit_code

    def substitution_runner(self, state: ShellState) -> SubstitutionRunner:
        """Return the callback word expansion uses for ``$( )`` and backticks

        Args:
            state: The shell state the substitutions run against

        Returns:
            A callable from script text to its output
        """
        return SubstitutionRunner(self, state)

    def drain_to_sink(self, result: ExecutionResult, state: ShellState) -> None:
        """Write a result's output to the state's standard output sink as it is produced

        Args:
            result: The result to drain
            state: The shell state whose sink receives the text
        """
        if isinstance(result.stdout, TextStream):
            for chunk in result.stdout:
                state.write_output(chunk)
        elif result.kind in (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES):
            for chunk in convert(result.stdout, result.kind, OutputKind.STREAM_TEXT):
                state.write_output(chunk)
        else:
            text = materialise_text(result.stdout, result.kind)
            if text:
                state.write_output(text)

    def execute_node(
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
            return self.execute_simple_command(node, state, stdin)
        if isinstance(node, PipelineNode):
            return self.execute_pipeline(node, state, stdin)
        if isinstance(node, AndOrListNode):
            return self.execute_and_or_list(node, state, stdin, direct_output)
        if isinstance(node, BackgroundNode):
            return self.execute_node(node.inner, state, stdin, direct_output)
        if isinstance(node, SubshellNode):
            body = node.body
            return self.execute_compound(
                lambda inner_state: self.run_subshell_script(body, inner_state),
                state.copy(),
                stdin,
                node.redirections,
                direct_output,
            )
        if isinstance(node, BraceGroupNode):
            body = node.body
            return self.execute_compound(
                lambda inner_state: self.run_script(body, inner_state), state, stdin, node.redirections, direct_output
            )
        if isinstance(node, IfNode):
            return self.execute_compound(
                lambda inner_state: self.run_if(node, inner_state), state, stdin, node.redirections, direct_output
            )
        if isinstance(node, ForNode):
            return self.execute_compound(
                lambda inner_state: self.run_for(node, inner_state), state, stdin, node.redirections, direct_output
            )
        if isinstance(node, WhileNode | UntilNode):
            return self.execute_compound(
                lambda inner_state: self.run_while(node, inner_state), state, stdin, node.redirections, direct_output
            )
        if isinstance(node, FunctionDefinitionNode):
            state.functions[node.name] = node.body
            return ExecutionResult.empty(EXIT_CODE_SUCCESS)
        raise ShellSyntaxError(f"unknown plan node: {node}")

    def execute_compound(
        self,
        run: Callable[[ShellState], int],
        state: ShellState,
        stdin: StdinValue | None,
        redirections: list[Redirection],
        direct_output: bool,
        merge_stderr: bool = False,
        error_destination: "ErrorDestination | Path | None" = None,
    ) -> ExecutionResult:
        """Run a compound command, capturing its output when a pipeline or redirection needs it

        Args:
            run: Runs the compound body against a state and returns its exit code
            state: The state the body runs against, a copy for a subshell
            stdin: Standard input the body's commands may consume, or None
            redirections: Redirections written after the compound command
            direct_output: Whether the body may write straight to the sink when nothing needs capturing
            merge_stderr: Whether error output joins standard output, as after ``|&``
            error_destination: Where errors go when the caller has already worked it out

        Returns:
            An empty result when the output went to the sink, otherwise the captured text
        """
        stdin = self.apply_input_redirections(stdin, redirections, state)
        if error_destination is None:
            error_destination = self.error_destination(redirections, state, merge_stderr)
        has_output_redirection = any(redirection.kind in OUTPUT_REDIRECTION_KINDS for redirection in redirections)
        previous_stdin = state.pending_stdin
        if stdin is not None:
            state.pending_stdin = stdin
        try:
            if direct_output and not has_output_redirection and stdin is None:
                write_error = self.error_sink(error_destination, state, state.write_output)
                with redirected_sinks(state, write_error=write_error):
                    return ExecutionResult.empty(run(state))
            collector = LimitedCollector(self.output_limit_characters)
            write_error = self.error_sink(error_destination, state, collector.append)
            try:
                with redirected_sinks(state, write_output=collector.append, write_error=write_error):
                    exit_code = run(state)
            except OutputLimitExceededError as error:
                if error.collector is not collector:
                    raise
                state.write_error(f"bash: {error}\n")
                exit_code = EXIT_CODE_BROKEN_PIPE
            result = ExecutionResult(stdout=collector.text(), kind=OutputKind.TEXT, exit_code=exit_code)
        finally:
            state.pending_stdin = previous_stdin
        return self.apply_output_redirections(result, redirections, state, error_destination)

    def execute_pipeline(self, node: PipelineNode, state: ShellState, stdin: StdinValue | None) -> ExecutionResult:
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
        for index, stage in enumerate(node.stages):
            stage_stdin = stdin if result is None else result.as_stdin()
            merge_stderr = index < len(node.merge_stderr) and node.merge_stderr[index]
            result = self.execute_stage(stage, state, stage_stdin, merge_stderr)
            if isinstance(result.stdout, TextStream):
                result.stdout.upstream = upstream
                upstream = result.stdout
            elif upstream is not None:
                upstream.close()
                upstream = None
        if result is None:
            raise ShellSyntaxError("empty pipeline")
        if not node.negated:
            return result
        text = materialise_text(result.stdout, result.kind)
        exit_code = EXIT_CODE_FAILURE if result.exit_code == EXIT_CODE_SUCCESS else EXIT_CODE_SUCCESS
        return ExecutionResult(stdout=text, kind=OutputKind.TEXT, exit_code=exit_code)

    def execute_stage(
        self, stage: PlanNode, state: ShellState, stdin: StdinValue | None, merge_stderr: bool
    ) -> ExecutionResult:
        """Run one pipeline stage with its output captured for the next stage

        Args:
            stage: The stage node
            state: The shell state to run against
            stdin: Standard input from the previous stage, or None
            merge_stderr: Whether the stage's error output joins its standard output

        Returns:
            The stage's result
        """
        if isinstance(stage, SimpleCommandNode):
            return self.execute_simple_command(stage, state, stdin, merge_stderr)
        if not merge_stderr:
            return self.execute_node(stage, state, stdin, direct_output=False)
        if isinstance(stage, SubshellNode):
            body = stage.body
            return self.execute_compound(
                lambda inner_state: self.run_subshell_script(body, inner_state),
                state.copy(),
                stdin,
                stage.redirections,
                False,
                merge_stderr=True,
            )
        if isinstance(stage, BraceGroupNode):
            body = stage.body
            return self.execute_compound(
                lambda inner_state: self.run_script(body, inner_state),
                state,
                stdin,
                stage.redirections,
                False,
                merge_stderr=True,
            )
        with redirected_sinks(state, write_error=state.write_output):
            return self.execute_node(stage, state, stdin, direct_output=False)

    def execute_and_or_list(
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
        pieces: list[str] = []
        sink = state.write_output if direct_output else pieces.append
        with redirected_sinks(state, write_output=sink):
            exit_code = self.run_and_drain(node.first, state, stdin)
            for operator, item in node.rest:
                should_run = (exit_code == EXIT_CODE_SUCCESS) == (operator == ListOperator.AND)
                if should_run:
                    exit_code = self.run_and_drain(item, state, None)
        if direct_output:
            return ExecutionResult.empty(exit_code)
        return ExecutionResult(stdout="".join(pieces), kind=OutputKind.TEXT, exit_code=exit_code)

    def run_and_drain(self, node: PlanNode, state: ShellState, stdin: StdinValue | None) -> int:
        """Run a node, write its output to the sink, and record its exit code

        Args:
            node: The node to run
            state: The shell state to run against
            stdin: Standard input for the node, or None

        Returns:
            The node's exit code
        """
        result = self.execute_node(node, state, stdin, direct_output=True)
        self.drain_to_sink(result, state)
        state.last_exit_code = result.exit_code
        return result.exit_code

    def run_if(self, node: IfNode, state: ShellState) -> int:
        """Run the first branch whose condition succeeds

        Args:
            node: The if statement
            state: The shell state to run against

        Returns:
            The exit code of the body that ran, or zero when none did
        """
        for condition, body in node.branches:
            if self.run_script(condition, state) == EXIT_CODE_SUCCESS:
                return self.run_script(body, state)
        if node.else_body is not None:
            return self.run_script(node.else_body, state)
        return EXIT_CODE_SUCCESS

    def run_for(self, node: ForNode, state: ShellState) -> int:
        """Run a for loop over its expanded words, or over the positional arguments

        Args:
            node: The for loop
            state: The shell state to run against

        Returns:
            The exit code of the last body run, or zero when the loop never ran
        """
        if node.words_text is None:
            values = list(state.positional_arguments)
        else:
            words, redirections, assignments = tokenize_simple_command(node.words_text)
            if redirections or assignments:
                raise ShellSyntaxError(f"bad for words: {node.words_text}")
            values = expand_words(words, state, self.substitution_runner(state))
        exit_code = EXIT_CODE_SUCCESS
        state.loop_depth += 1
        try:
            for value in values:
                state.variables[node.variable] = value
                try:
                    exit_code = self.run_script(node.body, state)
                except BreakLoop:
                    break
                except ContinueLoop:
                    continue
        finally:
            state.loop_depth -= 1
        return exit_code

    def run_while(self, node: WhileNode | UntilNode, state: ShellState) -> int:
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
                condition_succeeded = self.run_script(node.condition, state) == EXIT_CODE_SUCCESS
                if condition_succeeded != run_while_condition_succeeds:
                    return exit_code
                try:
                    exit_code = self.run_script(node.body, state)
                except BreakLoop:
                    return exit_code
                except ContinueLoop:
                    continue
        finally:
            state.loop_depth -= 1

    def execute_simple_command(
        self, node: SimpleCommandNode, state: ShellState, stdin: StdinValue | None, merge_stderr: bool = False
    ) -> ExecutionResult:
        """Expand one simple command and run it as an assignment, a function, a builtin, or a registered command

        Args:
            node: The simple command
            state: The shell state to run against
            stdin: Standard input from a pipeline, or None
            merge_stderr: Whether the command's error output joins its standard output, as after ``|&``

        Returns:
            The command's output and exit code
        """
        run_substitution = self.substitution_runner(state)
        words, redirections, assignments = tokenize_simple_command(node.text)
        arguments = expand_words(words, state, run_substitution)
        if not arguments:
            for assignment in assignments:
                state.variables[assignment.name] = expand_word_unsplit(assignment.value, state, run_substitution)
            exit_code = run_substitution.last_exit_code
            return ExecutionResult.empty(EXIT_CODE_SUCCESS if exit_code is None else exit_code)
        saved_variables = {assignment.name: state.variables.get(assignment.name) for assignment in assignments}
        for assignment in assignments:
            state.variables[assignment.name] = expand_word_unsplit(assignment.value, state, run_substitution)
        error_destination = self.error_destination(redirections, state, merge_stderr)
        try:
            stdin = self.apply_input_redirections(stdin, redirections, state)
            result = self.dispatch(arguments[0], arguments[1:], stdin, error_destination, state)
        finally:
            for name, value in saved_variables.items():
                if value is None:
                    state.variables.pop(name, None)
                else:
                    state.variables[name] = value
        return self.apply_output_redirections(result, redirections, state, error_destination)

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

    def dispatch(
        self,
        name: str,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: ErrorDestination | Path,
        state: ShellState,
    ) -> ExecutionResult:
        """Run a named command as a function, a builtin, or a registered command

        Args:
            name: The command name
            arguments: The expanded arguments after it
            stdin: Standard input, or None
            error_destination: Where the command's error output goes
            state: The shell state to run against

        Returns:
            The command's output and exit code
        """
        if name in state.functions:
            return self.call_function(name, arguments, stdin, error_destination, state)
        builtin = self.builtins.get(name)
        if builtin is not None:
            with redirected_sinks(state, write_error=self.error_sink(error_destination, state, state.write_output)):
                return ExecutionResult.empty(builtin(arguments, stdin, state))
        command = self.registry.get(name)
        if command is None:
            self.error_sink(error_destination, state, state.write_output)(f"bash: {name}: command not found\n")
            if stdin is not None:
                self.discard_stdin(stdin)
            return ExecutionResult.empty(EXIT_CODE_COMMAND_NOT_FOUND)
        if command.input_kinds != frozenset({InputKind.ARGUMENTS}):
            stdin = self.take_pending_stdin(stdin, state)
        return self.run_registered_command(command, arguments, stdin, error_destination, state)

    def call_function(
        self,
        name: str,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: ErrorDestination | Path,
        state: ShellState,
    ) -> ExecutionResult:
        """Run a shell function with its own positional arguments and a fresh loop scope

        Args:
            name: The function name
            arguments: The positional arguments for the call
            stdin: Standard input the function's commands may consume, or None
            error_destination: Where the function's error output goes
            state: The shell state to run against

        Returns:
            The captured output and the function's exit code
        """
        saved_positional = state.positional_arguments
        saved_loop_depth = state.loop_depth
        state.positional_arguments = arguments
        state.loop_depth = 0
        state.function_depth += 1

        def run_body(inner_state: ShellState) -> int:
            try:
                return self.run_script(state.functions[name], inner_state)
            except ReturnFromFunction as returned:
                return returned.exit_code

        try:
            return self.execute_compound(run_body, state, stdin, [], False, error_destination=error_destination)
        finally:
            state.positional_arguments = saved_positional
            state.loop_depth = saved_loop_depth
            state.function_depth -= 1

    def run_registered_command(
        self,
        command: Command,
        arguments: list[str],
        stdin: StdinValue | None,
        error_destination: ErrorDestination | Path,
        state: ShellState,
    ) -> ExecutionResult:
        """Run a registered command with its input converted to a kind it accepts

        Args:
            command: The command object
            arguments: The expanded arguments
            stdin: Standard input, or None
            error_destination: Where the command's error output goes
            state: The shell state to run against

        Returns:
            The command's output in its preferred kind, with errors interleaved when they join standard output
        """
        if stdin is None or command.input_kinds == frozenset({InputKind.ARGUMENTS}):
            if stdin is not None:
                self.discard_stdin(stdin)
            stdin_value, stdin_kind = None, InputKind.ARGUMENTS
        else:
            _, stdin_kind = choose_kinds(frozenset({stdin.kind}), command.input_kinds)
            stdin_value = convert(stdin.value, stdin.kind, OutputKind(stdin_kind))
        stdout_kind = next(kind for kind in KIND_PREFERENCE if kind in command.output_kinds)
        error_buffer: list[str] = []
        merge_into_stdout = error_destination == ErrorDestination.STDOUT
        write_error = error_buffer.append if merge_into_stdout else self.error_sink(error_destination, state, None)
        invocation_state = (
            state if write_error is state.write_error else dataclasses.replace(state, write_error=write_error)
        )
        invocation = CommandInvocation(
            arguments=arguments,
            stdin=stdin_value,
            stdin_kind=stdin_kind,
            stdout_kind=stdout_kind,
            state=invocation_state,
        )
        command_result = command.run(invocation)
        stdout: Any = command_result.stdout
        if stdout_kind in (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES):
            stream = iter(stdout)
            if merge_into_stdout:
                stream = interleave_errors(stream, error_buffer, encode=stdout_kind == OutputKind.STREAM_BYTES)
            if stdout_kind == OutputKind.STREAM_TEXT:
                stdout = TextStream(stream, provisional_exit_code=command_result.exit_code)
            else:
                stdout = stream
        elif merge_into_stdout and error_buffer:
            errors = "".join(error_buffer)
            stdout = errors.encode(TEXT_ENCODING) + stdout if stdout_kind == OutputKind.BYTES else errors + stdout
        return ExecutionResult(stdout=stdout, kind=stdout_kind, exit_code=command_result.exit_code)

    def discard_stdin(self, stdin: StdinValue) -> None:
        """Drain input a command will not read, so the producer runs to completion as it would under bash

        Args:
            stdin: The unread input
        """
        if stdin.kind in (OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES):
            close = getattr(stdin.value, "close", None)
            if close is not None:
                close()

    def error_destination(
        self, redirections: list[Redirection], state: ShellState, merge_stderr: bool
    ) -> ErrorDestination | Path:
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
                path = self.redirection_path(redirection, state)
                stdout_target = ErrorDestination.DISCARD if path is None else path
                if destination == ErrorDestination.STDOUT:
                    destination = ErrorDestination.SINK_STDOUT
            elif redirection.kind == RedirectionKind.STDERR_TO_STDOUT:
                destination = stdout_target
                if isinstance(destination, Path):
                    destination.write_text("", encoding="utf-8")
            elif redirection.kind == RedirectionKind.WRITE_BOTH:
                path = self.redirection_path(redirection, state)
                if path is None:
                    destination = ErrorDestination.DISCARD
                else:
                    path.write_text("", encoding="utf-8")
                    destination = path
            elif redirection.kind in (RedirectionKind.WRITE_STDERR, RedirectionKind.APPEND_STDERR):
                path = self.redirection_path(redirection, state)
                if path is None:
                    destination = ErrorDestination.DISCARD
                    continue
                if redirection.kind == RedirectionKind.WRITE_STDERR:
                    path.write_text("", encoding="utf-8")
                destination = path
        return destination

    def error_sink(
        self, destination: ErrorDestination | Path, state: ShellState, stdout_sink: Callable[[str], None] | None
    ) -> Callable[[str], None]:
        """Return the function error output should be written through

        Args:
            destination: Where the errors go
            state: The shell state holding the standard sinks
            stdout_sink: The sink standing in for standard output, or None when errors cannot join it

        Returns:
            A function taking text
        """
        if destination == ErrorDestination.STDERR:
            return state.write_error
        if destination == ErrorDestination.DISCARD:
            return discard_text
        if destination == ErrorDestination.STDOUT:
            return stdout_sink if stdout_sink is not None else state.write_output
        if destination == ErrorDestination.SINK_STDOUT:
            return state.write_output
        return file_appender(destination)

    def redirection_path(self, redirection: Redirection, state: ShellState) -> Path | None:
        """Return the file a redirection names, or None for the null device

        Args:
            redirection: A redirection with a file target
            state: The shell state for expansion and path resolution

        Returns:
            The absolute path, or None when output should be discarded
        """
        target = expand_raw_word(redirection.target, state, self.substitution_runner(state))
        if target == NULL_DEVICE_PATH:
            return None
        return state.resolve_path(target)

    def apply_input_redirections(
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
                path = self.redirection_path(redirection, state)
                if path is None:
                    stdin = StdinValue(value="", kind=OutputKind.TEXT)
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except FileNotFoundError as error:
                    raise ShellError(f"{redirection.target}: No such file or directory") from error
                stdin = StdinValue(value=text, kind=OutputKind.TEXT)
            elif redirection.kind == RedirectionKind.HEREDOC:
                body = redirection.target
                if redirection.expand_target:
                    body = expand_text(body, state, self.substitution_runner(state), in_double_quotes=True)
                stdin = StdinValue(value=body, kind=OutputKind.TEXT)
            elif redirection.kind == RedirectionKind.HERE_STRING:
                text = expand_raw_word(redirection.target, state, self.substitution_runner(state))
                stdin = StdinValue(value=text + "\n", kind=OutputKind.TEXT)
        return stdin

    def apply_output_redirections(
        self,
        result: ExecutionResult,
        redirections: list[Redirection],
        state: ShellState,
        error_destination: ErrorDestination | Path | None = None,
    ) -> ExecutionResult:
        """Write a result to the file its ``>``, ``>>`` or ``&>`` names, leaving nothing for the sink

        Every file named by an earlier ``>`` is created and emptied as well, as bash does when it opens them in turn

        Args:
            result: The result to redirect
            redirections: The command's redirections
            state: The shell state for expansion and path resolution
            error_destination: Where errors went, so a file already holding them is appended to rather than replaced

        Returns:
            The result unchanged when no output redirection applies, otherwise an empty result with its exit code
        """
        target: Path | None = None
        append = False
        redirected = False
        for redirection in redirections:
            if redirection.kind not in OUTPUT_REDIRECTION_KINDS:
                continue
            if target is not None and not append:
                target.write_text("", encoding="utf-8")
            target = self.redirection_path(redirection, state)
            append = redirection.kind != RedirectionKind.WRITE_STDOUT
            redirected = True
        if not redirected:
            return result
        text = materialise_text(result.stdout, result.kind)
        if target is not None:
            shares_file_with_errors = isinstance(error_destination, Path) and error_destination == target
            existing = (
                target.read_text(encoding="utf-8") if (append or shares_file_with_errors) and target.exists() else ""
            )
            target.write_text(existing + text, encoding="utf-8")
        return ExecutionResult.empty(result.exit_code)

    def builtin_cd(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
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
        state.variables[PREVIOUS_DIRECTORY_VARIABLE_NAME] = str(state.cwd)
        state.cwd = target.resolve()
        state.variables[CURRENT_DIRECTORY_VARIABLE_NAME] = str(state.cwd)
        return EXIT_CODE_SUCCESS

    def builtin_export(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Set variables from ``name=value`` arguments

        Args:
            arguments: The assignments, or bare names which are left as they are
            stdin: Ignored
            state: The shell state whose variables change

        Returns:
            Zero
        """
        for argument in arguments:
            name, separator, value = argument.partition("=")
            if separator:
                state.variables[name] = value
        return EXIT_CODE_SUCCESS

    def builtin_unset(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
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
            state.variables.pop(name, None)
            state.functions.pop(name, None)
        return EXIT_CODE_SUCCESS

    def builtin_exit(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Stop the script

        Args:
            arguments: An optional exit code
            stdin: Ignored
            state: The shell state holding the last exit code used by default

        Raises:
            ExitShell: Always
        """
        raise ExitShell(parse_exit_code(arguments, state))

    def builtin_return(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
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

    def builtin_break(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
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

    def builtin_continue(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
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

    def builtin_no_op(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Do nothing successfully

        Args:
            arguments: Ignored
            stdin: Ignored
            state: Ignored

        Returns:
            Zero
        """
        return EXIT_CODE_SUCCESS


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
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    return append


def run_script(script: str, state: ShellState, registry: CommandRegistry | None = None) -> int:
    """Run a script against a state with the default commands

    Args:
        script: The script text
        state: The shell state to run against
        registry: The commands available, defaulting to everything the package ships

    Returns:
        The exit code of the script
    """
    return Executor(registry).execute_script(script, state)
