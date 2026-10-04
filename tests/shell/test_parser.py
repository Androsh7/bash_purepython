"""Tests for grouping tokens into pipelines and lists"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import ChainOperator, CommandList, RawCommand, ShellSyntaxError
from bash_purepython.shell.parser import parse
from bash_purepython.shell.tokenizer import expand_word, tokenize

HOME = "/home/user"


def parse_line(line: str) -> CommandList:
    """Return the parsed form of a line"""
    return parse(tokenize(line))


def argv_of(command: RawCommand) -> list[str | None]:
    """Return a raw command's words expanded with no variables"""
    return [expand_word(word, {}, HOME, 0) for word in command.words]


def test_parse_returns_one_pipeline_for_a_simple_command() -> None:
    """Check that a single command is one pipeline of one command"""
    command_list = parse_line("echo a b")

    assert len(command_list.pipelines) == 1
    assert command_list.operators == ()
    assert argv_of(command_list.pipelines[0].commands[0]) == ["echo", "a", "b"]


def test_parse_groups_piped_commands_into_one_pipeline() -> None:
    """Check that | joins commands inside a single pipeline"""
    command_list = parse_line("cat f | grep x | wc -l")

    argvs = [argv_of(command) for command in command_list.pipelines[0].commands]
    assert argvs == [["cat", "f"], ["grep", "x"], ["wc", "-l"]]


def test_parse_records_the_operator_between_pipelines() -> None:
    """Check that &&, || and ; split pipelines and are kept in order"""
    command_list = parse_line("a && b || c ; d")

    assert [argv_of(pipeline.commands[0])[0] for pipeline in command_list.pipelines] == ["a", "b", "c", "d"]
    assert command_list.operators == (ChainOperator.AND, ChainOperator.OR, ChainOperator.SEMICOLON)


def test_parse_accepts_a_trailing_semicolon() -> None:
    """Check that a line may end with ; without starting another command"""
    command_list = parse_line("echo a;")

    assert len(command_list.pipelines) == 1


def test_parse_keeps_a_word_that_may_expand_to_nothing() -> None:
    """Check that a bare variable is a command whose fate is decided at expansion time"""
    command_list = parse_line("a ; $UNSET ; b")

    assert len(command_list.pipelines) == 3
    assert argv_of(command_list.pipelines[1].commands[0]) == [None]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("echo a > out", ("out", False)),
        ("echo a >> out", ("out", True)),
        ("echo > out a", ("out", False)),
        ("echo a > one > two", ("two", False)),
    ],
    ids=["write", "append", "before-argument", "last-wins"],
)
def test_parse_attaches_redirects_to_their_command(line: str, expected: tuple[str, bool]) -> None:
    """Check that a redirect belongs to the command it appears in, the last one winning"""
    command_list = parse_line(line)

    command = command_list.pipelines[0].commands[0]
    assert command.redirects.stdout_target is not None
    assert (expand_word(command.redirects.stdout_target, {}, HOME, 0), command.redirects.stdout_append) == expected
    assert argv_of(command) == ["echo", "a"]


def test_parse_keeps_every_kind_of_redirect_on_the_command() -> None:
    """Check that stdout, stderr and stdin redirects are all recorded"""
    command_list = parse_line("cmd <in >out 2>>err")

    redirects = command_list.pipelines[0].commands[0].redirects
    assert expand_word(redirects.stdin_source, {}, HOME, 0) == "in"
    assert expand_word(redirects.stdout_target, {}, HOME, 0) == "out"
    assert expand_word(redirects.stderr_target, {}, HOME, 0) == "err"
    assert redirects.stderr_append
    assert not redirects.stderr_to_stdout


def test_parse_joins_stderr_to_stdout_for_both_forms() -> None:
    """Check that 2>&1 and &> both mark stderr as joined to stdout"""
    merged = parse_line("cmd >out 2>&1").pipelines[0].commands[0].redirects
    both = parse_line("cmd &>all").pipelines[0].commands[0].redirects

    assert merged.stderr_to_stdout
    assert both.stderr_to_stdout
    assert expand_word(both.stdout_target, {}, HOME, 0) == "all"


@pytest.mark.parametrize(
    "line",
    ["| a", "a |", "a &&", "a > ", "a > | b", "a ; ; b", "false ;; echo", "a || || b", "> out", "a 2>", "a <"],
    ids=[
        "leading-pipe",
        "trailing-pipe",
        "trailing-and",
        "missing-target",
        "operator-as-target",
        "empty-command",
        "double-semicolon",
        "double-or",
        "redirect-only",
        "stderr-without-target",
        "input-without-source",
    ],
)
def test_parse_raises_on_misplaced_operators(line: str) -> None:
    """Check that an operator without a command on each side is a syntax error"""
    with pytest.raises(ShellSyntaxError):
        parse_line(line)
