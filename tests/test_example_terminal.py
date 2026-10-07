"""Test the example terminal by feeding it lines as a user would type them"""

# Standard libraries
import os
import subprocess
import sys
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from examples.terminal import needs_more_lines

REPOSITORY_ROOT = Path(__file__).parent.parent
TERMINAL_TIMEOUT_S = 30


def run_terminal_session(typed: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the example terminal with the given text on its standard input

    Args:
        typed: Everything the user types, newlines included
        cwd: The directory the terminal starts in

    Returns:
        The finished process with its captured output
    """
    return subprocess.run(
        [sys.executable, "-m", "examples.terminal"],
        input=typed,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TERMINAL_TIMEOUT_S,
        check=False,
    )


def test_terminal_runs_each_line_and_keeps_state_between_them(tmp_path: Path) -> None:
    """Check that a variable set on one line is seen on the next and output is printed"""
    session = run_terminal_session("greeting=hello\necho $greeting world\n", tmp_path)

    assert "hello world" in session.stdout


def test_terminal_leaves_on_exit_with_the_given_code(tmp_path: Path) -> None:
    """Check that exit ends the session and later lines are not run"""
    session = run_terminal_session("echo before\nexit 3\necho after\n", tmp_path)

    assert session.returncode == 3
    assert "before" in session.stdout
    assert "after" not in session.stdout


def test_terminal_ends_at_the_end_of_input_with_the_last_exit_code(tmp_path: Path) -> None:
    """Check that running out of input ends the session with the last command's code"""
    session = run_terminal_session("false\n", tmp_path)

    assert session.returncode == 1


def test_terminal_reads_a_here_document_across_lines(tmp_path: Path) -> None:
    """Check that lines are collected until the delimiter and then run as one command"""
    session = run_terminal_session("cat << EOF > note.txt\nfirst\nsecond\nEOF\n", tmp_path)

    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "first\nsecond\n"
    assert session.returncode == 0


def test_terminal_keeps_a_background_job_alive_between_lines(tmp_path: Path) -> None:
    """Check that a job started on one line can be waited for on the next"""
    session = run_terminal_session("{ sleep 0.05; echo finished; } &\nwait\necho after\n", tmp_path)

    assert session.stdout.index("finished") < session.stdout.index("after")


def test_terminal_shows_the_directory_in_its_prompt(tmp_path: Path) -> None:
    """Check that the prompt follows cd"""
    (tmp_path / "inner").mkdir()

    session = run_terminal_session("cd inner\n", tmp_path)

    assert "inner$ " in session.stdout


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("echo done", False),
        ("echo 'closed'", False),
        ("echo 'open", True),
        ('echo "open', True),
        ("cat << EOF", True),
        ("cat << EOF\nline", True),
        ("cat << EOF\nline\nEOF", False),
        ("echo one \\", True),
    ],
    ids=[
        "plain",
        "closed_quote",
        "open_single_quote",
        "open_double_quote",
        "heredoc_opened",
        "heredoc_body",
        "heredoc_closed",
        "trailing_backslash",
    ],
)
def test_needs_more_lines_detects_unfinished_input(text: str, expected: bool) -> None:
    """Check which inputs make the terminal ask for another line"""
    assert needs_more_lines(text) is expected
