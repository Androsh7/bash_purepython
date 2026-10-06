"""Tests for grouping tokens into pipelines and lists"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell.models import ChainOperator, CommandList, IncompleteInputError, RawCommand, ShellSyntaxError
from bash_purepython.shell.parser import parse, parse_text
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


def test_parse_sends_stderr_to_the_file_stdout_already_names() -> None:
    """Check that >out 2>&1 points stderr at out, and &> names the file for both"""
    merged = parse_line("cmd >out 2>&1").pipelines[0].commands[0].redirects
    both = parse_line("cmd &>all").pipelines[0].commands[0].redirects

    assert expand_word(merged.stderr_target, {}, HOME, 0) == "out"
    assert not merged.stderr_to_stdout
    assert expand_word(both.stderr_target, {}, HOME, 0) == "all"
    assert expand_word(both.stdout_target, {}, HOME, 0) == "all"


def test_parse_applies_redirects_left_to_right() -> None:
    """Check that 2>&1 before > keeps stderr on the pipe while stdout moves to the file"""
    redirects = parse_line("cmd 2>&1 >out").pipelines[0].commands[0].redirects

    assert redirects.stderr_to_stdout
    assert redirects.stderr_target is None
    assert expand_word(redirects.stdout_target, {}, HOME, 0) == "out"


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


def test_parse_text_attaches_a_here_document_body() -> None:
    """Check that the lines up to the delimiter become the command's input"""
    command_list = parse_text("cat << EOF\nline one\nline two\nEOF")

    redirects = command_list.pipelines[0].commands[0].redirects
    assert redirects.heredoc_body == "line one\nline two\n"


def test_parse_text_feeds_two_here_documents_in_order() -> None:
    """Check that each << on the line takes the next body"""
    command_list = parse_text("cat << A | cat << B\nfirst\nA\nsecond\nB")

    bodies = [command.redirects.heredoc_body for command in command_list.pipelines[0].commands]
    assert bodies == ["first\n", "second\n"]


def test_parse_text_strips_leading_tabs_for_dash_form() -> None:
    """Check that <<- removes leading tabs from body and delimiter lines"""
    command_list = parse_text("cat <<- EOF\n\tindented\n\tEOF")

    assert command_list.pipelines[0].commands[0].redirects.heredoc_body == "indented\n"


def test_parse_text_reports_an_unterminated_here_document_as_incomplete() -> None:
    """Check that a missing delimiter asks for more input rather than failing"""
    with pytest.raises(IncompleteInputError):
        parse_text("cat << EOF\nstill going")


def test_parse_text_reports_an_open_quote_as_incomplete() -> None:
    """Check that a quote spanning lines asks for more input"""
    with pytest.raises(IncompleteInputError):
        parse_text('echo "first line')


def test_parse_text_rejects_text_after_the_last_here_document() -> None:
    """Check that stray lines after the delimiter are an error, not silently dropped"""
    with pytest.raises(ShellSyntaxError, match="unexpected text"):
        parse_text("cat << EOF\nbody\nEOF\nstray")
