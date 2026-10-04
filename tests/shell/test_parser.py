"""Tests for grouping tokens into pipelines and lists"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import ChainOperator, Redirect, ShellSyntaxError
from bash_purepython.shell.parser import parse
from bash_purepython.shell.tokenizer import tokenize


def parse_line(line: str):
    """Return the parsed form of a line with no variables or home"""
    return parse(tokenize(line, {}, "/home/user"))


def test_parse_returns_one_pipeline_for_a_simple_command() -> None:
    """Check that a single command is one pipeline of one command"""
    command_list = parse_line("echo a b")

    assert len(command_list.pipelines) == 1
    assert command_list.operators == ()
    assert command_list.pipelines[0].commands[0].argv == ("echo", "a", "b")


def test_parse_groups_piped_commands_into_one_pipeline() -> None:
    """Check that | joins commands inside a single pipeline"""
    command_list = parse_line("cat f | grep x | wc -l")

    argvs = [command.argv for command in command_list.pipelines[0].commands]
    assert argvs == [("cat", "f"), ("grep", "x"), ("wc", "-l")]


def test_parse_records_the_operator_between_pipelines() -> None:
    """Check that &&, || and ; split pipelines and are kept in order"""
    command_list = parse_line("a && b || c ; d")

    assert [pipeline.commands[0].name for pipeline in command_list.pipelines] == ["a", "b", "c", "d"]
    assert command_list.operators == (ChainOperator.AND, ChainOperator.OR, ChainOperator.SEMICOLON)


def test_parse_accepts_a_trailing_semicolon() -> None:
    """Check that a line may end with ; without starting another command"""
    command_list = parse_line("echo a;")

    assert len(command_list.pipelines) == 1


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("echo a > out", Redirect(target="out", append=False)),
        ("echo a >> out", Redirect(target="out", append=True)),
        ("echo > out a", Redirect(target="out", append=False)),
        ("echo a > one > two", Redirect(target="two", append=False)),
    ],
    ids=["write", "append", "before-argument", "last-wins"],
)
def test_parse_attaches_redirects_to_their_command(line: str, expected: Redirect) -> None:
    """Check that a redirect belongs to the command it appears in, the last one winning"""
    command_list = parse_line(line)

    command = command_list.pipelines[0].commands[0]
    assert command.redirect == expected
    assert command.argv == ("echo", "a")


@pytest.mark.parametrize(
    "line",
    ["| a", "a |", "a &&", "a > ", "a > | b", "a ; ; b"],
    ids=["leading-pipe", "trailing-pipe", "trailing-and", "missing-target", "operator-as-target", "empty-command"],
)
def test_parse_raises_on_misplaced_operators(line: str) -> None:
    """Check that an operator without a command on each side is a syntax error"""
    with pytest.raises(ShellSyntaxError):
        parse_line(line)
