"""Run an interactive terminal on the engine, as an example of embedding it in a host

Start it with ``python -m examples.terminal``. It shows the pieces every host supplies: one shell state kept
for the whole session, one runner whose event loop keeps background jobs alive between lines, a prompt, and a
continuation prompt while a quote or here-document is still open
"""

# Standard libraries
import sys
from pathlib import Path

# Project libraries
from bash_purepython.continuation import script_needs_more_lines
from bash_purepython.execute_command import ShellRunner
from bash_purepython.shell_state import ControlFlowSignal, ExitShell, ShellState

PROMPT_SUFFIX = "$ "
CONTINUATION_PROMPT = "> "
HOME_SHORTHAND = "~"
EXIT_CODE_INTERRUPTED = 130


def prompt_for(state: ShellState) -> str:
    """Return the prompt showing the shell's current directory, with the home directory shortened

    Args:
        state: The shell state holding the directory

    Returns:
        The prompt text
    """
    home = Path.home()
    try:
        shown = Path(HOME_SHORTHAND) / state.cwd.relative_to(home)
    except ValueError:
        shown = state.cwd
    return f"{shown.as_posix()}{PROMPT_SUFFIX}"


def read_command(state: ShellState) -> str | None:
    """Read one complete command, asking for further lines while it is unfinished

    Args:
        state: The shell state the prompt is drawn from

    Returns:
        The command text, or None at the end of input
    """
    try:
        text = input(prompt_for(state))
        while script_needs_more_lines(text):
            text += "\n" + input(CONTINUATION_PROMPT)
    except EOFError:
        return None
    return text


def run_terminal() -> int:
    """Read commands and run them until ``exit`` or the end of input, and return the exit code

    The executor's inner entry point is used so that ``exit`` reaches this loop instead of only ending
    the line it was typed on

    Returns:
        The code given to ``exit``, or the exit code of the last command that ran
    """
    state = ShellState.for_terminal()
    runner = ShellRunner()
    try:
        while True:
            try:
                command = read_command(state)
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                continue
            if command is None:
                sys.stdout.write("\n")
                return state.last_exit_code
            if not command.strip():
                continue
            try:
                runner.runner.run(runner.executor.run_script(command, state))
            except ExitShell as exit_shell:
                return exit_shell.exit_code
            except ControlFlowSignal:
                continue
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                state.last_exit_code = EXIT_CODE_INTERRUPTED
    finally:
        runner.close()


if __name__ == "__main__":
    sys.exit(run_terminal())
