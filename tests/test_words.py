"""Test tokenising simple commands and expanding their words"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell_state import ShellState, ShellSyntaxError
from bash_purepython.words import Word, expand_word_unsplit, expand_words, tokenize_simple_command
from bash_purepython.workflow import Redirection, RedirectionKind


def make_state(variables: dict[str, str] | None = None, **state_fields: object) -> ShellState:
    """Return a state with in-memory sinks

    Args:
        variables: Shell variables to start with
        state_fields: Other ShellState fields to override

    Returns:
        The state
    """
    return ShellState(
        cwd=Path("/tmp"),
        write_output=lambda text: None,
        write_error=lambda text: None,
        variables=variables or {},
        **state_fields,
    )


def echo_substitution(script: str) -> str:
    """Return a marker for a substitution instead of running it

    Args:
        script: The substituted script

    Returns:
        The script wrapped so a test can see it was substituted
    """
    return f"<{script.replace(' ', '_')}>"


def words_of(text: str) -> list[Word]:
    """Return only the words of a command text

    Args:
        text: One simple command

    Returns:
        The words
    """
    return tokenize_simple_command(text)[0]


def redirections_of(text: str) -> list[Redirection]:
    """Return only the redirections of a command text

    Args:
        text: One simple command

    Returns:
        The redirections
    """
    return tokenize_simple_command(text)[1]


def expand(text: str, state: ShellState | None = None) -> list[str]:
    """Return the expanded arguments of a command text

    Args:
        text: One simple command
        state: The state to expand against, defaulting to an empty one

    Returns:
        The expanded fields
    """
    return expand_words(words_of(text), state or make_state(), echo_substitution)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("echo a b  c", ["echo", "a", "b", "c"]),
        ("echo 'a b' \"c d\"", ["echo", "a b", "c d"]),
        ("echo a'b'\"c\"d", ["echo", "abcd"]),
        ("echo a\\ b", ["echo", "a b"]),
        ("echo 'it''s'", ["echo", "its"]),
        ('echo ""', ["echo", ""]),
        ("echo ''", ["echo", ""]),
        ("echo \\$HOME", ["echo", "$HOME"]),
        ("echo '$HOME'", ["echo", "$HOME"]),
        ("echo {a,b}", ["echo", "{a,b}"]),
        ("echo a#b", ["echo", "a#b"]),
    ],
    ids=[
        "whitespace_splits",
        "quotes_keep_spaces",
        "adjacent_quotes_join",
        "escaped_space",
        "adjacent_single_quotes",
        "empty_double_quotes_is_a_field",
        "empty_single_quotes_is_a_field",
        "escaped_dollar_is_literal",
        "single_quoted_dollar_is_literal",
        "braces_are_literal",
        "hash_inside_word_is_literal",
    ],
)
def test_expand_handles_quoting(text: str, expected: list[str]) -> None:
    """Check that quoting rules decide how text becomes fields"""
    assert expand(text) == expected


@pytest.mark.parametrize(
    ("text", "variables", "expected"),
    [
        ("echo $name", {"name": "bob"}, ["echo", "bob"]),
        ("echo ${name}", {"name": "bob"}, ["echo", "bob"]),
        ('echo "$name"', {"name": "bob"}, ["echo", "bob"]),
        ("echo ${name}s", {"name": "bob"}, ["echo", "bobs"]),
        ("echo $names", {"name": "bob"}, ["echo"]),
        ("echo $missing", {}, ["echo"]),
        ('echo "$missing"', {}, ["echo", ""]),
        ("echo $words", {"words": "a b  c"}, ["echo", "a", "b", "c"]),
        ('echo "$words"', {"words": "a b  c"}, ["echo", "a b  c"]),
        ("echo x${words}y", {"words": "a b"}, ["echo", "xa", "by"]),
        ("echo ${missing:-fallback}", {}, ["echo", "fallback"]),
        ("echo ${empty:-fallback}", {"empty": ""}, ["echo", "fallback"]),
        ('echo "${empty-fallback}"', {"empty": ""}, ["echo", ""]),
        ("echo ${name:+set}", {"name": "bob"}, ["echo", "set"]),
        ("echo ${#name}", {"name": "bob"}, ["echo", "3"]),
        ("echo ${missing:-$other}", {"other": "o"}, ["echo", "o"]),
    ],
    ids=[
        "plain",
        "braced",
        "quoted",
        "braced_with_suffix",
        "suffix_changes_the_name",
        "unset_unquoted_vanishes",
        "unset_quoted_is_empty_field",
        "unquoted_splits",
        "quoted_keeps_spaces",
        "split_joins_neighbours",
        "default_for_unset",
        "colon_default_for_empty",
        "plain_default_keeps_empty",
        "alternate_when_set",
        "length",
        "default_is_expanded",
    ],
)
def test_expand_parameters(text: str, variables: dict[str, str], expected: list[str]) -> None:
    """Check parameter expansion with and without quotes and operators"""
    assert expand(text, make_state(variables)) == expected


def test_expand_assigns_with_colon_equals() -> None:
    """Check that := sets the variable as well as expanding to the default"""
    state = make_state()

    fields = expand("echo ${name:=bob}", state)

    assert (fields, state.variables["name"]) == (["echo", "bob"], {"name": "bob"}["name"])


def test_expand_special_parameters() -> None:
    """Check that the exit code, positional arguments and their count expand"""
    state = make_state(positional_arguments=["one", "two three"], last_exit_code=3)

    fields = expand('echo $? $# $1 "$2" $@ $0', state)

    assert fields == ["echo", "3", "2", "one", "two three", "one", "two", "three", "bash"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("echo $(date)", ["echo", "<date>"]),
        ("echo `date`", ["echo", "<date>"]),
        ('echo "$(date; uptime)"', ["echo", "<date;_uptime>"]),
        ("echo $(echo $(inner))", ["echo", "<echo_$(inner)>"]),
        ("echo pre$(date)post", ["echo", "pre<date>post"]),
        ("echo $((1 + 2))", ["echo", "<(1_+_2)>"]),
    ],
    ids=["dollar_paren", "backticks", "quoted_with_semicolon", "nested", "embedded", "arithmetic_passes_through"],
)
def test_expand_runs_substitutions(text: str, expected: list[str]) -> None:
    """Check that command substitutions are handed to the runner with their inner text"""
    assert expand(text) == expected


def test_expand_splits_unquoted_substitution_output() -> None:
    """Check that an unquoted substitution's output is split into fields but a quoted one is not"""
    words = words_of('echo $(x) "$(x)"')

    fields = expand_words(words, make_state(), lambda script: "a b\nc")

    assert fields == ["echo", "a", "b", "c", "a b\nc"]


def test_expand_tilde_uses_home() -> None:
    """Check that a bare or leading tilde expands to HOME and a quoted one does not"""
    state = make_state({"HOME": "/home/bob"})

    fields = expand("echo ~ ~/x '~' a~", state)

    assert fields == ["echo", "/home/bob", "/home/bob/x", "~", "a~"]


def test_tokenize_separates_assignments_from_arguments() -> None:
    """Check that name=value words before the command are assignments and later ones are not"""
    words, _, assignments = tokenize_simple_command("A=1 B='x y' cmd C=3")

    assert [assignment.name for assignment in assignments] == ["A", "B"]
    assert [expand_word_unsplit(assignment.value, make_state(), echo_substitution) for assignment in assignments] == [
        "1",
        "x y",
    ]
    assert [word.raw_text() for word in words] == ["cmd", "C=3"]


@pytest.mark.parametrize(
    ("text", "expected_words", "expected_redirections"),
    [
        ("echo a > out", ["echo", "a"], [(RedirectionKind.WRITE_STDOUT, "out")]),
        ("echo a>out", ["echo", "a"], [(RedirectionKind.WRITE_STDOUT, "out")]),
        ("echo a >> out", ["echo", "a"], [(RedirectionKind.APPEND_STDOUT, "out")]),
        ("cat < in", ["cat"], [(RedirectionKind.READ_STDIN, "in")]),
        ("ls 2> err", ["ls"], [(RedirectionKind.WRITE_STDERR, "err")]),
        ("ls 2>> err", ["ls"], [(RedirectionKind.APPEND_STDERR, "err")]),
        ("ls 2>&1", ["ls"], [(RedirectionKind.STDERR_TO_STDOUT, "")]),
        ("ls &> all", ["ls"], [(RedirectionKind.WRITE_BOTH, "all")]),
        ("ls 1> out", ["ls"], [(RedirectionKind.WRITE_STDOUT, "out")]),
        ("echo 2 > out", ["echo", "2"], [(RedirectionKind.WRITE_STDOUT, "out")]),
        ("cat <<< word", ["cat"], [(RedirectionKind.HERE_STRING, "word")]),
        ("echo > out a", ["echo", "a"], [(RedirectionKind.WRITE_STDOUT, "out")]),
        ("echo > 'my file'", ["echo"], [(RedirectionKind.WRITE_STDOUT, "'my file'")]),
        ("ls > out 2>&1", ["ls"], [(RedirectionKind.WRITE_STDOUT, "out"), (RedirectionKind.STDERR_TO_STDOUT, "")]),
    ],
    ids=[
        "write",
        "write_without_spaces",
        "append",
        "read",
        "stderr_write",
        "stderr_append",
        "stderr_to_stdout",
        "both",
        "explicit_descriptor_one",
        "digit_argument_is_not_a_descriptor",
        "here_string",
        "redirection_before_argument",
        "quoted_target_kept_raw",
        "two_redirections",
    ],
)
def test_tokenize_extracts_redirections(
    text: str, expected_words: list[str], expected_redirections: list[tuple[RedirectionKind, str]]
) -> None:
    """Check that redirection operators and their targets leave the word list"""
    words, redirections, _ = tokenize_simple_command(text)

    assert [word.raw_text() for word in words] == expected_words
    assert [(redirection.kind, redirection.target) for redirection in redirections] == expected_redirections


@pytest.mark.parametrize(
    ("text", "expected_body", "expected_expand"),
    [
        ("cat <<EOF\nhello $x\nEOF", "hello $x\n", True),
        ("cat <<'EOF'\nhello $x\nEOF", "hello $x\n", False),
        ('cat <<"EOF"\nhello\nEOF', "hello\n", False),
        ("cat <<\\EOF\nhello\nEOF", "hello\n", False),
        ("cat <<-EOF\n\tindented\n\tEOF", "indented\n", True),
        ("cat <<EOF\na\nb\nEOF", "a\nb\n", True),
        ("cat <<EOF\nnever closed", "never closed\n", True),
    ],
    ids=[
        "plain",
        "single_quoted_delimiter",
        "double_quoted_delimiter",
        "escaped_delimiter",
        "dash_strips_tabs",
        "multiple_lines",
        "unterminated_runs_to_end",
    ],
)
def test_tokenize_reads_heredoc_bodies(text: str, expected_body: str, expected_expand: bool) -> None:
    """Check that a heredoc body is captured and quoting of the delimiter controls expansion"""
    words, redirections, _ = tokenize_simple_command(text)

    assert [word.raw_text() for word in words] == ["cat"]
    assert [(redirection.kind, redirection.target, redirection.expand_target) for redirection in redirections] == [
        (RedirectionKind.HEREDOC, expected_body, expected_expand)
    ]


def test_tokenize_reads_two_heredocs_in_order() -> None:
    """Check that two heredocs on one line each take the next body"""
    redirections = redirections_of("cat <<A <<B\n1\nA\n2\nB")

    assert [redirection.target for redirection in redirections] == ["1\n", "2\n"]


@pytest.mark.parametrize(
    "text",
    ["echo 'open", 'echo "open', "echo $(open", "echo >", "echo >&2", "echo (a)", "echo `open"],
    ids=[
        "unclosed_single",
        "unclosed_double",
        "unbalanced_substitution",
        "missing_target",
        "unsupported_descriptor_redirection",
        "bare_parenthesis",
        "unclosed_backtick",
    ],
)
def test_tokenize_rejects_malformed_text(text: str) -> None:
    """Check that malformed quoting and operators raise a syntax error"""
    with pytest.raises(ShellSyntaxError):
        tokenize_simple_command(text)
