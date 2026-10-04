"""Tests for running one command with captured streams"""

# Standard libraries
import io

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import OUTPUT_LIMIT_BYTES, CommandNotFoundError
from bash_purepython.shell.runner import command_help_text, exit_code_from_system_exit, run_command


def test_run_command_captures_stdout_and_succeeds() -> None:
    """Check that a command's output comes back as bytes with exit code zero"""
    output = run_command("echo", ["echo", "hello"], b"")

    assert output.stdout == b"hello\n"
    assert output.stderr == b""
    assert output.exit_code == 0


@pytest.mark.parametrize(("name", "expected"), [("true", 0), ("false", 1)], ids=["true", "false"])
def test_run_command_returns_the_exit_code_of_sys_exit(name: str, expected: int) -> None:
    """Check that a command leaving through sys.exit reports that code"""
    output = run_command(name, [name], b"")

    assert output.exit_code == expected


def test_run_command_feeds_stdin_to_the_command() -> None:
    """Check that a filter reads the bytes it is given"""
    output = run_command("tr", ["tr", "a", "b"], b"aaa")

    assert output.stdout == b"bbb"


def test_run_command_preserves_bytes_written_through_the_buffer() -> None:
    """Check that binary output is not decoded and re-encoded"""
    output = run_command("head", ["head", "-c", "3"], b"\xff\x00\x01zz")

    assert output.stdout == b"\xff\x00\x01"


def test_run_command_stops_an_endless_writer_at_the_output_limit() -> None:
    """Check that yes terminates cleanly once the capture is full"""
    output = run_command("yes", ["yes"], b"")

    assert output.exit_code == 0
    assert 0 < len(output.stdout) <= OUTPUT_LIMIT_BYTES


def test_run_command_reports_argparse_errors_on_stderr() -> None:
    """Check that an invalid flag produces a usage error with argparse's exit code"""
    output = run_command("echo", ["echo", "--no-such-flag"], b"")

    assert output.exit_code == 2
    assert b"usage" in output.stderr.lower()


def test_run_command_raises_for_an_unknown_command() -> None:
    """Check that the caller learns about a missing command rather than getting output"""
    with pytest.raises(CommandNotFoundError):
        run_command("nonexistent", ["nonexistent"], b"")


@pytest.mark.parametrize(
    ("code", "expected"),
    [(None, 0), (0, 0), (3, 3), ("boom", 1)],
    ids=["none", "zero", "three", "message"],
)
def test_exit_code_from_system_exit_maps_every_payload_kind(code: object, expected: int) -> None:
    """Check that None, integers and messages all become a usable exit code"""
    stderr = io.StringIO()

    exit_code = exit_code_from_system_exit(SystemExit(code), stderr)

    assert exit_code == expected


def test_exit_code_from_system_exit_prints_a_message_payload() -> None:
    """Check that a string payload is written to stderr"""
    stderr = io.StringIO()

    exit_code_from_system_exit(SystemExit("boom"), stderr)

    assert "boom" in stderr.getvalue()


def test_command_help_text_contains_the_option_names() -> None:
    """Check that a command's help can be read for its flags"""
    help_text = command_help_text("grep")

    assert "--ignore-case" in help_text
