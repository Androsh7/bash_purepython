"""Share fixtures that run scripts against an in-memory shell state"""

# Standard libraries
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.execute_command import Executor
from bash_purepython.shell_state import ShellState


@dataclass
class ScriptRun:
    """Hold what one script run produced"""

    stdout: str
    stderr: str
    exit_code: int
    state: ShellState


@dataclass
class ShellHarness:
    """Run scripts against one state and collect their output"""

    state: ShellState
    executor: Executor
    output_pieces: list[str] = field(default_factory=list)
    error_pieces: list[str] = field(default_factory=list)

    def run(self, script: str) -> ScriptRun:
        """Run a script and return everything it produced

        Args:
            script: The script text

        Returns:
            The collected output, errors, exit code and the state after the run
        """
        self.output_pieces.clear()
        self.error_pieces.clear()
        exit_code = self.executor.execute_script(script, self.state)
        return ScriptRun(
            stdout="".join(self.output_pieces),
            stderr="".join(self.error_pieces),
            exit_code=exit_code,
            state=self.state,
        )


def build_harness(cwd: Path, registry: CommandRegistry | None = None) -> ShellHarness:
    """Return a harness whose state writes into in-memory lists

    Args:
        cwd: The starting directory
        registry: The commands available, defaulting to the package's

    Returns:
        A harness ready to run scripts
    """
    output_pieces: list[str] = []
    error_pieces: list[str] = []
    state = ShellState(cwd=cwd, write_output=output_pieces.append, write_error=error_pieces.append)
    return ShellHarness(
        state=state, executor=Executor(registry), output_pieces=output_pieces, error_pieces=error_pieces
    )


@pytest.fixture
def shell(tmp_path: Path) -> ShellHarness:
    """Return a harness running in a temporary directory with the default commands"""
    return build_harness(tmp_path)


@pytest.fixture
def make_shell(tmp_path: Path) -> Callable[[CommandRegistry], ShellHarness]:
    """Return a factory for harnesses with a custom registry"""
    return lambda registry: build_harness(tmp_path, registry)
