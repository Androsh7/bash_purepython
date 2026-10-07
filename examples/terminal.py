"""Run an interactive terminal on the engine, as an example of embedding it in a host

Start it with ``python -m examples.terminal``. It shows the pieces every host supplies: one shell state kept
for the whole session, one runner whose event loop keeps background jobs alive between lines, a prompt, and a
continuation prompt while a quote or here-document is still open
"""

# Standard libraries
import re
import sys
from pathlib import Path

# Project libraries
from bash_purepython.execute_command import ShellRunner
from bash_purepython.shell_state import ControlFlowSignal, ExitShell, ShellState, ShellSyntaxError
from bash_purepython.words import tokenize_simple_command

PROMPT_SUFFIX = "$ "
CONTINUATION_PROMPT = "> "
HOME_SHORTHAND = "~"
EXIT_CODE_INTERRUPTED = 130
HEREDOC_OPERATOR_PATTERN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w.]*)\1")
UNCLOSED_MARKER = "unclosed"


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


def needs_more_lines(text: str) -> bool:
    """Return whether the lines typed so far leave a quote or a here-document open

    Args:
        text: The lines entered so far, joined by newlines

    Returns:
        True when another line should be read before the text is run
    """
    lines = text.split("\n")
    for delimiter_match in HEREDOC_OPERATOR_PATTERN.finditer(lines[0]):
        if delimiter_match.group(2) not in lines[1:]:
            return True
    if text.endswith("\\"):
        return True
    try:
        tokenize_simple_command(text.replace("\n", " "))
    except ShellSyntaxError as error:
        return UNCLOSED_MARKER in str(error)
    return False


def read_command(state: ShellState) -> str | None:
    """Read one complete command, asking for further lines while it is unfinished

    Args:
        state: The shell state the prompt is drawn from

    Returns:
        The command text, or None at the end of input
    """
    try:
        text = input(prompt_for(state))
        while needs_more_lines(text):
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
