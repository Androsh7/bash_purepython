"""Share fixtures that run scripts against an in-memory shell state"""

# Standard libraries
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.execute_command import ShellRunner
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
    """Run scripts against one state on one event loop and collect their output"""

    state: ShellState
    runner: ShellRunner
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
        exit_code = self.runner.run(script, self.state)
        return ScriptRun(
            stdout="".join(self.output_pieces),
            stderr="".join(self.error_pieces),
            exit_code=exit_code,
            state=self.state,
        )

    def close(self) -> None:
        """Stop any background jobs and release the event loop"""
        self.runner.close()


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
        state=state, runner=ShellRunner(registry), output_pieces=output_pieces, error_pieces=error_pieces
    )


@pytest.fixture
def shell(tmp_path: Path) -> Iterator[ShellHarness]:
    """Return a harness running in a temporary directory with the default commands"""
    harness = build_harness(tmp_path)
    yield harness
    harness.close()


@pytest.fixture
def make_shell(tmp_path: Path) -> Iterator[Callable[[CommandRegistry], ShellHarness]]:
    """Return a factory for harnesses with a custom registry"""
    harnesses: list[ShellHarness] = []

    def make(registry: CommandRegistry) -> ShellHarness:
        harness = build_harness(tmp_path, registry)
        harnesses.append(harness)
        return harness

    yield make
    for harness in harnesses:
        harness.close()
