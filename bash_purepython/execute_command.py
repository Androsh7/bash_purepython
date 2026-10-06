"""Run plan nodes: parse a script, build each block's plan, execute it, and recurse into the scripts it contains"""

# Standard libraries
import dataclasses
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Project libraries
from bash_purepython.block_parser import build_plan
from bash_purepython.command.command import Command, CommandInvocation, InputKind, OutputKind
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.parse_script import split_script_into_connected_commands
from bash_purepython.shell_state import (
    EXIT_CODE_COMMAND_NOT_FOUND,
    EXIT_CODE_FAILURE,
    EXIT_CODE_SUCCESS,
    EXIT_CODE_USAGE_ERROR,
    BreakLoop,
    ContinueLoop,
    ControlFlowSignal,
    ExitShell,
    ReturnFromFunction,
    ShellError,
    ShellState,
    ShellSyntaxError,
)
from bash_purepython.streams import KIND_PREFERENCE, TextStream, choose_kinds, convert, materialise_text
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


class Executor:
    """Run scripts against a shell state using one registry of commands"""

    def __init__(self, registry: CommandRegistry | None = None):
        """Create an executor

        Args:
            registry: The commands available to scripts, defaulting to everything the package ships
        """
        self.registry = registry if registry is not None else CommandRegistry()
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
        """Run a whole script as the outermost entry point, so exit stops it and stray break or continue are ignored

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
            except ShellError as error:
                state.write_error(f"bash: {error}\n")
                state.last_exit_code = EXIT_CODE_FAILURE
                continue
            state.last_exit_code = result.exit_code
        return state.last_exit_code

    def capture_script(self, script: str, state: ShellState) -> str:
        """Run a script with its standard output collected, for command substitution

        Args:
            script: The script text
            state: The shell state to run against

        Returns:
            Everything the script wrote to standard output
        """
        pieces: list[str] = []
        with redirected_sinks(state, write_output=pieces.append):
            self.run_script(script, state)
        return "".join(pieces)

    def substitution_runner(self, state: ShellState) -> Callable[[str], str]:
        """Return the callback word expansion uses for ``$( )`` and backticks

        Args:
            state: The shell state the substitutions run against

        Returns:
            A function from script text to its output with trailing newlines removed
        """
        return lambda script: self.capture_script(script, state).rstrip("\n")

    def drain_to_sink(self, result: ExecutionResult, state: ShellState) -> None:
        """Write a result's output to the state's standard output sink as it is produced

        Args:
            result: The result to drain
            state: The shell state whose sink receives the text
        """
        if isinstance(result.stdout, TextStream):
            for chunk in result.stdout:
                state.write_output(chunk)
        elif result.kind == OutputKind.STREAM_TEXT or result.kind == OutputKind.STREAM_BYTES:
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
            return self.execute_compound(
                lambda inner_state: self.run_script(node.body, inner_state),
                state.copy(),
                stdin,
                node.redirections,
                direct_output,
            )
        if isinstance(node, BraceGroupNode):
            return self.execute_compound(
                lambda inner_state: self.run_script(node.body, inner_state),
                state,
                stdin,
                node.redirections,
                direct_output,
            )
        if isinstance(node, IfNode):
            return self.execute_compound(
                lambda inner_state: self.run_if(node, inner_state), state, stdin, [], direct_output
            )
        if isinstance(node, ForNode):
            return self.execute_compound(
                lambda inner_state: self.run_for(node, inner_state), state, stdin, [], direct_output
            )
        if isinstance(node, WhileNode | UntilNode):
            return self.execute_compound(
                lambda inner_state: self.run_while(node, inner_state), state, stdin, [], direct_output
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
    ) -> ExecutionResult:
        """Run a compound command, capturing its output when a pipeline or redirection needs it

        Args:
            run: Runs the compound body against a state and returns its exit code
            state: The state the body runs against, a copy for a subshell
            stdin: Standard input the body's commands may consume, or None
            redirections: Redirections written after the compound command
            direct_output: Whether the body may write straight to the sink when nothing needs capturing

        Returns:
            An empty result when the output went to the sink, otherwise the captured text
        """
        previous_stdin = state.pending_stdin
        state.pending_stdin = stdin
        try:
            if direct_output and not redirections and stdin is None:
                return ExecutionResult.empty(run(state))
            pieces: list[str] = []
            with redirected_sinks(state, write_output=pieces.append):
                exit_code = run(state)
            result = ExecutionResult(stdout="".join(pieces), kind=OutputKind.TEXT, exit_code=exit_code)
        finally:
            state.pending_stdin = previous_stdin
        return self.apply_output_redirections(result, redirections, state)

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
            if merge_stderr and isinstance(stage, SimpleCommandNode):
                result = self.execute_simple_command(stage, state, stage_stdin, merge_stderr=True)
            elif merge_stderr:
                with redirected_sinks(state, write_error=state.write_output):
                    result = self.execute_node(stage, state, stage_stdin, direct_output=False)
            else:
                result = self.execute_node(stage, state, stage_stdin, direct_output=False)
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
        for value in values:
            state.variables[node.variable] = value
            try:
                exit_code = self.run_script(node.body, state)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
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
            return ExecutionResult.empty(EXIT_CODE_SUCCESS)
        saved_variables = {assignment.name: state.variables.get(assignment.name) for assignment in assignments}
        for assignment in assignments:
            state.variables[assignment.name] = expand_word_unsplit(assignment.value, state, run_substitution)
        try:
            stdin = self.apply_input_redirections(stdin, redirections, state)
            if stdin is None and state.pending_stdin is not None:
                stdin = state.pending_stdin
                state.pending_stdin = None
            result = self.dispatch(arguments[0], arguments[1:], stdin, redirections, state, merge_stderr)
        finally:
            for name, value in saved_variables.items():
                if value is None:
                    state.variables.pop(name, None)
                else:
                    state.variables[name] = value
        return self.apply_output_redirections(result, redirections, state)

    def dispatch(
        self,
        name: str,
        arguments: list[str],
        stdin: StdinValue | None,
        redirections: list[Redirection],
        state: ShellState,
        merge_stderr: bool,
    ) -> ExecutionResult:
        """Run a named command as a function, a builtin, or a registered command

        Args:
            name: The command name
            arguments: The expanded arguments after it
            stdin: Standard input, or None
            redirections: The command's redirections, for stderr routing
            state: The shell state to run against
            merge_stderr: Whether error output joins standard output

        Returns:
            The command's output and exit code
        """
        if name in state.functions:
            return self.call_function(name, arguments, stdin, state)
        builtin = self.builtins.get(name)
        if builtin is not None:
            return ExecutionResult.empty(builtin(arguments, stdin, state))
        command = self.registry.get(name)
        if command is None:
            state.write_error(f"bash: {name}: command not found\n")
            if stdin is not None:
                self.discard_stdin(stdin)
            return ExecutionResult.empty(EXIT_CODE_COMMAND_NOT_FOUND)
        return self.run_registered_command(command, arguments, stdin, redirections, state, merge_stderr)

    def call_function(
        self, name: str, arguments: list[str], stdin: StdinValue | None, state: ShellState
    ) -> ExecutionResult:
        """Run a shell function with its own positional arguments

        Args:
            name: The function name
            arguments: The positional arguments for the call
            stdin: Standard input the function's commands may consume, or None
            state: The shell state to run against

        Returns:
            The captured output and the function's exit code
        """
        saved_positional = state.positional_arguments
        state.positional_arguments = arguments

        def run_body(inner_state: ShellState) -> int:
            try:
                return self.run_script(state.functions[name], inner_state)
            except ReturnFromFunction as returned:
                return returned.exit_code

        try:
            return self.execute_compound(run_body, state, stdin, [], direct_output=False)
        finally:
            state.positional_arguments = saved_positional

    def run_registered_command(
        self,
        command: Command,
        arguments: list[str],
        stdin: StdinValue | None,
        redirections: list[Redirection],
        state: ShellState,
        merge_stderr: bool,
    ) -> ExecutionResult:
        """Run a registered command with its input converted to a kind it accepts

        Args:
            command: The command object
            arguments: The expanded arguments
            stdin: Standard input, or None
            redirections: The command's redirections, for stderr routing
            state: The shell state to run against
            merge_stderr: Whether error output joins standard output

        Returns:
            The command's output in its preferred kind
        """
        if stdin is None or command.input_kinds == frozenset({InputKind.ARGUMENTS}):
            if stdin is not None:
                self.discard_stdin(stdin)
            stdin_value, stdin_kind = None, InputKind.ARGUMENTS
        else:
            _, stdin_kind = choose_kinds(frozenset({stdin.kind}), command.input_kinds)
            stdin_value = convert(stdin.value, stdin.kind, OutputKind(stdin_kind))
        stdout_kind = next(kind for kind in KIND_PREFERENCE if kind in command.output_kinds)
        invocation_state = self.state_with_stderr_routing(state, redirections, merge_stderr)
        invocation = CommandInvocation(
            arguments=arguments,
            stdin=stdin_value,
            stdin_kind=stdin_kind,
            stdout_kind=stdout_kind,
            state=invocation_state,
        )
        command_result = command.run(invocation)
        stdout: Any = command_result.stdout
        if stdout_kind == OutputKind.STREAM_TEXT:
            stdout = TextStream(iter(stdout), provisional_exit_code=command_result.exit_code)
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

    def state_with_stderr_routing(
        self, state: ShellState, redirections: list[Redirection], merge_stderr: bool
    ) -> ShellState:
        """Return the state a command should see, with its error sink redirected as the command asked

        Args:
            state: The live shell state
            redirections: The command's redirections
            merge_stderr: Whether error output joins standard output before any redirection applies

        Returns:
            The same state, or a shallow copy whose error sink points elsewhere
        """
        write_error = state.write_output if merge_stderr else state.write_error
        for redirection in redirections:
            if redirection.kind == RedirectionKind.STDERR_TO_STDOUT:
                write_error = state.write_output
            elif redirection.kind in (RedirectionKind.WRITE_STDERR, RedirectionKind.APPEND_STDERR):
                path = self.redirection_path(redirection, state)
                if redirection.kind == RedirectionKind.WRITE_STDERR:
                    path.write_text("", encoding="utf-8")
                write_error = file_appender(path)
            elif redirection.kind == RedirectionKind.WRITE_BOTH:
                path = self.redirection_path(redirection, state)
                path.write_text("", encoding="utf-8")
                write_error = file_appender(path)
        if write_error is state.write_error:
            return state
        return dataclasses.replace(state, write_error=write_error)

    def redirection_path(self, redirection: Redirection, state: ShellState) -> Path:
        """Return the file a redirection names

        Args:
            redirection: A redirection with a file target
            state: The shell state for expansion and path resolution

        Returns:
            The absolute path
        """
        target = expand_raw_word(redirection.target, state, self.substitution_runner(state))
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
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except FileNotFoundError as error:
                    raise ShellError(f"{redirection.target}: No such file or directory") from error
                stdin = StdinValue(value=text, kind=OutputKind.TEXT)
            elif redirection.kind == RedirectionKind.HEREDOC:
                body = redirection.target
                if redirection.expand_target:
                    body = expand_heredoc_body(body, state, self.substitution_runner(state))
                stdin = StdinValue(value=body, kind=OutputKind.TEXT)
            elif redirection.kind == RedirectionKind.HERE_STRING:
                text = expand_raw_word(redirection.target, state, self.substitution_runner(state))
                stdin = StdinValue(value=text + "\n", kind=OutputKind.TEXT)
        return stdin

    def apply_output_redirections(
        self, result: ExecutionResult, redirections: list[Redirection], state: ShellState
    ) -> ExecutionResult:
        """Write a result to the file its ``>``, ``>>`` or ``&>`` names, leaving nothing for the sink

        Args:
            result: The result to redirect
            redirections: The command's redirections
            state: The shell state for expansion and path resolution

        Returns:
            The result unchanged when no output redirection applies, otherwise an empty result with its exit code
        """
        target: Path | None = None
        append = False
        for redirection in redirections:
            if redirection.kind in (RedirectionKind.WRITE_STDOUT, RedirectionKind.WRITE_BOTH):
                target, append = self.redirection_path(redirection, state), False
            elif redirection.kind == RedirectionKind.APPEND_STDOUT:
                target, append = self.redirection_path(redirection, state), True
        if target is None:
            return result
        text = materialise_text(result.stdout, result.kind)
        existing = target.read_text(encoding="utf-8") if append and target.exists() else ""
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
            arguments: The names to remove
            stdin: Ignored
            state: The shell state to change

        Returns:
            Zero
        """
        for name in arguments:
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
        """Leave the current function

        Args:
            arguments: An optional exit code
            stdin: Ignored
            state: The shell state holding the last exit code used by default

        Raises:
            ReturnFromFunction: Always
        """
        raise ReturnFromFunction(parse_exit_code(arguments, state))

    def builtin_break(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Leave the innermost loop

        Args:
            arguments: Ignored
            stdin: Ignored
            state: Ignored

        Raises:
            BreakLoop: Always
        """
        raise BreakLoop()

    def builtin_continue(self, arguments: list[str], stdin: StdinValue | None, state: ShellState) -> int:
        """Start the next iteration of the innermost loop

        Args:
            arguments: Ignored
            stdin: Ignored
            state: Ignored

        Raises:
            ContinueLoop: Always
        """
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
        return int(arguments[0])
    except ValueError:
        state.write_error(f"bash: {arguments[0]}: numeric argument required\n")
        return EXIT_CODE_USAGE_ERROR


def expand_heredoc_body(body: str, state: ShellState, run_substitution: Callable[[str], str]) -> str:
    """Return a heredoc body with parameters and substitutions expanded as bash does for an unquoted delimiter

    Args:
        body: The raw body text
        state: The shell state to read variables from
        run_substitution: Runs a script and returns its output

    Returns:
        The expanded body
    """
    return expand_text(body, state, run_substitution, in_double_quotes=True)


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
