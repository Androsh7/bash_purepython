"""Tests for the interactive Python session"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import REPL_INDENT_WIDTH_SPACES, ReplStatus
from bash_purepython.shell.repl import ReplSession


@pytest.fixture
def repl() -> ReplSession:
    """Return a fresh REPL"""
    return ReplSession()


def test_feed_runs_a_statement_and_prints_an_expression(repl: ReplSession, capsys: pytest.CaptureFixture[str]) -> None:
    """Check that assignments persist and bare expressions are echoed"""
    repl.feed("answer = 41 + 1")

    result = repl.feed("answer")

    assert result.status == ReplStatus.DONE
    assert capsys.readouterr().out.strip() == "42"


def test_feed_asks_for_more_until_a_block_is_complete(repl: ReplSession, capsys: pytest.CaptureFixture[str]) -> None:
    """Check that a compound statement is held open until a blank line"""
    first = repl.feed("def double(value):")
    second = repl.feed("    return value * 2")
    third = repl.feed("")
    repl.feed("print(double(4))")

    assert (first.status, second.status, third.status) == (ReplStatus.MORE, ReplStatus.MORE, ReplStatus.DONE)
    assert capsys.readouterr().out.strip() == "8"


def test_feed_reports_a_syntax_error_and_resets(repl: ReplSession, capsys: pytest.CaptureFixture[str]) -> None:
    """Check that unparsable input prints a traceback and clears the pending lines"""
    result = repl.feed("def broken(:")
    follow_up = repl.feed("1 + 1")

    assert result.status == ReplStatus.ERROR
    assert "SyntaxError" in capsys.readouterr().err
    assert follow_up.status == ReplStatus.DONE


def test_feed_prints_a_traceback_for_a_runtime_error(repl: ReplSession, capsys: pytest.CaptureFixture[str]) -> None:
    """Check that an exception is reported and the session keeps going"""
    result = repl.feed("1 / 0")

    assert result.status == ReplStatus.DONE
    assert "ZeroDivisionError" in capsys.readouterr().err


@pytest.mark.parametrize(
    "line", ["exit()", "quit()", "exit", "raise SystemExit"], ids=["exit", "quit", "bare", "raise"]
)
def test_feed_reports_an_exit_request(repl: ReplSession, line: str) -> None:
    """Check that every way of leaving is reported as an exit"""
    result = repl.feed(line)

    assert result.status == ReplStatus.EXIT


@pytest.mark.parametrize("text", ["", "    "], ids=["empty", "indented"])
def test_complete_indents_a_blank_prefix(repl: ReplSession, text: str) -> None:
    """Check that Tab on whitespace inserts one indent level at the cursor"""
    result = repl.complete(text)

    assert result.replacement == " " * REPL_INDENT_WIDTH_SPACES
    assert result.word_start == len(text)


def test_complete_finishes_a_unique_global_name(repl: ReplSession) -> None:
    """Check that a name defined in the session is completed"""
    repl.feed("alpha_value = 1")

    result = repl.complete("print(alpha_v")

    assert result.replacement == "alpha_value"
    assert result.word_start == len("print(")


def test_complete_finishes_a_unique_attribute(repl: ReplSession) -> None:
    """Check that attributes of an imported module are completed"""
    repl.feed("import os")

    result = repl.complete("os.getcwdb")

    assert result.replacement is not None
    assert result.replacement.startswith("os.getcwdb")


def test_complete_lists_ambiguous_attributes(repl: ReplSession) -> None:
    """Check that several attribute matches are listed"""
    repl.feed("import os")

    result = repl.complete("os.pa")

    assert result.replacement is None
    assert "os.path" in result.listing


def test_complete_returns_nothing_after_punctuation(repl: ReplSession) -> None:
    """Check that there is no name to complete right after an opening bracket"""
    result = repl.complete("print(")

    assert result.replacement is None
    assert result.listing == ()


def test_banner_names_the_python_version(repl: ReplSession) -> None:
    """Check that the banner starts like the interpreter's"""
    assert repl.banner().startswith("Python 3.")


def test_feed_keeps_an_exit_word_inside_a_block_as_code(repl: ReplSession) -> None:
    """Check that an indented exit inside a pending block does not leave the REPL"""
    repl.feed("def leave():")

    result = repl.feed("    exit")

    assert result.status == ReplStatus.MORE


def test_feed_reports_a_keyboard_interrupt_as_a_traceback(
    repl: ReplSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check that a BaseException raised by a statement is shown, not propagated"""
    result = repl.feed("raise KeyboardInterrupt")

    assert result.status == ReplStatus.DONE
    assert "KeyboardInterrupt" in capsys.readouterr().err


def test_feed_shows_only_the_user_frames_in_a_traceback(repl: ReplSession, capsys: pytest.CaptureFixture[str]) -> None:
    """Check that the shell's own frames are not part of a runtime error's traceback"""
    repl.feed("1 / 0")

    assert "repl.py" not in capsys.readouterr().err
