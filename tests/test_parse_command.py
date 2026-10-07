"""Test splitting a script into classified top-level command blocks"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.parse_script import CommandBlock, CommandBlockType, split_script_into_connected_commands

EXAMPLE_SCRIPT = """
echo "start" | tee log.txt ; sleep 1 & echo $(date; uptime) > out.txt ; cat <<EOF
some; text
EOF
echo "all done"
"""


def split_into_command_text(script: str) -> list[str]:
    """Return only the command text of every block in a script

    Args:
        script: The shell script text to split

    Returns:
        The command strings in script order
    """
    return [block.command for block in split_script_into_connected_commands(script)]


def test_split_keeps_pipelines_substitutions_and_heredocs_together() -> None:
    """Check that the README example splits into exactly its five classified top-level commands"""
    blocks = split_script_into_connected_commands(EXAMPLE_SCRIPT)

    assert blocks == [
        CommandBlock(CommandBlockType.PIPED_COMMANDS, 'echo "start" | tee log.txt'),
        CommandBlock(CommandBlockType.BACKGROUND_COMMAND, "sleep 1 &"),
        CommandBlock(CommandBlockType.COMMAND, "echo $(date; uptime) > out.txt"),
        CommandBlock(CommandBlockType.MULTILINE_CAT, "cat <<EOF\nsome; text\nEOF"),
        CommandBlock(CommandBlockType.COMMAND, 'echo "all done"'),
    ]


@pytest.mark.parametrize(
    ("script", "expected_block_type"),
    [
        ("echo hello", CommandBlockType.COMMAND),
        ("! grep x file", CommandBlockType.COMMAND),
        ("echo a | sort | uniq", CommandBlockType.PIPED_COMMANDS),
        ("echo a |& cat", CommandBlockType.PIPED_COMMANDS),
        ("true && echo yes", CommandBlockType.AND_OR_LIST),
        ("false || echo no", CommandBlockType.AND_OR_LIST),
        ("echo a | cat && echo b", CommandBlockType.AND_OR_LIST),
        ("sleep 1 &", CommandBlockType.BACKGROUND_COMMAND),
        ("cat <<EOF\nbody\nEOF", CommandBlockType.MULTILINE_CAT),
        ("tee out <<-EOF\n\tbody\n\tEOF", CommandBlockType.MULTILINE_CAT),
        ("cat <<EOF | grep x\nbody\nEOF", CommandBlockType.PIPED_COMMANDS),
        ("if true; then echo a; fi", CommandBlockType.IF),
        ("for x in a b; do echo $x; done", CommandBlockType.FOR),
        ("while true; do break; done", CommandBlockType.WHILE),
        ("until false; do break; done", CommandBlockType.UNTIL),
        ("case $x in a) echo;; esac", CommandBlockType.CASE),
        ("select x in a b; do echo $x; done", CommandBlockType.SELECT),
        ("greet() { echo hi; }", CommandBlockType.FUNCTION),
        ("greet () {\n  echo hi\n}", CommandBlockType.FUNCTION),
        ("function greet { echo hi; }", CommandBlockType.FUNCTION),
        ("(cd dir; make)", CommandBlockType.SUBSHELL),
        ("(cd dir; make) > log", CommandBlockType.SUBSHELL),
        ("{ echo a; echo b; } > out", CommandBlockType.BRACE_GROUP),
        ("echo {a,b}", CommandBlockType.COMMAND),
        ("echo $(date) `uptime` ${x}", CommandBlockType.COMMAND),
        ("echo fi", CommandBlockType.COMMAND),
        ("echo 'a | b' \"c && d\"", CommandBlockType.COMMAND),
    ],
    ids=[
        "plain_command",
        "negated_command",
        "pipeline",
        "pipeline_with_stderr",
        "and_list",
        "or_list",
        "list_containing_a_pipeline",
        "background_command",
        "heredoc",
        "dash_heredoc_on_tee",
        "heredoc_feeding_a_pipeline",
        "if_block",
        "for_block",
        "while_block",
        "until_block",
        "case_block",
        "select_block",
        "function_with_parentheses",
        "function_with_spaced_parentheses",
        "function_keyword",
        "subshell",
        "subshell_with_redirection",
        "brace_group",
        "brace_expansion_is_a_command",
        "expansions_are_a_command",
        "keyword_as_argument_is_a_command",
        "operators_inside_quotes_are_a_command",
    ],
)
def test_split_classifies_each_block(script: str, expected_block_type: CommandBlockType) -> None:
    """Check that a single block is given the type matching its top-level structure"""
    blocks = split_script_into_connected_commands(script)

    assert [block.block_type for block in blocks] == [expected_block_type]


def test_split_classifies_each_block_independently() -> None:
    """Check that the type of one block does not leak into the next"""
    blocks = split_script_into_connected_commands("if true; then echo a; fi\necho b | cat\necho c")

    assert [block.block_type for block in blocks] == [
        CommandBlockType.IF,
        CommandBlockType.PIPED_COMMANDS,
        CommandBlockType.COMMAND,
    ]


@pytest.mark.parametrize(
    ("script", "expected_commands"),
    [
        ("echo a; echo b\necho c", ["echo a", "echo b", "echo c"]),
        ("echo 'a; b' ; echo \"c; d\"", ["echo 'a; b'", 'echo "c; d"']),
        ("echo a\\; b; echo c", ["echo a\\; b", "echo c"]),
        ("echo a \\\n  b; echo c", ["echo a b", "echo c"]),
        ("echo a \\\n    | cat \\\n\t| wc; echo c", ["echo a | cat | wc", "echo c"]),
        ("echo ab\\\ncd; echo e", ["echo abcd", "echo e"]),
        ('echo "a\\\nb"; echo c', ['echo "ab"', "echo c"]),
        ("echo 'a\\\nb'; echo c", ["echo 'a\\\nb'", "echo c"]),
        ("cat <<EOF\na \\\nb\nEOF\necho c", ["cat <<EOF\na \\\nb\nEOF", "echo c"]),
        ("true && echo yes || echo no; echo next", ["true && echo yes || echo no", "echo next"]),
        ("sleep 1 & sleep 2 &\necho done", ["sleep 1 &", "sleep 2 &", "echo done"]),
        ("ls 2>&1 &> log; echo a |& cat", ["ls 2>&1 &> log", "echo a |& cat"]),
        ("echo `date; uptime`; echo b", ["echo `date; uptime`", "echo b"]),
        ('echo "$(date; uptime)"; echo b', ['echo "$(date; uptime)"', "echo b"]),
        ("echo ${name:-x}; echo b", ["echo ${name:-x}", "echo b"]),
        ("echo $((1 + 2; )); echo b", ["echo $((1 + 2; ))", "echo b"]),
        ("(cd dir; make) ; echo b", ["(cd dir; make)", "echo b"]),
        ("{ echo a; echo b; } > out; echo c", ["{ echo a; echo b; } > out", "echo c"]),
        ("echo {a,b}; echo c", ["echo {a,b}", "echo c"]),
    ],
    ids=[
        "semicolons_and_newlines",
        "quotes_hide_separators",
        "escaped_semicolon",
        "line_continuation_becomes_one_space",
        "continued_pipeline_joins_onto_one_line",
        "continuation_inside_word_joins_the_word",
        "continuation_inside_double_quotes_is_removed",
        "continuation_inside_single_quotes_is_literal",
        "continuation_inside_heredoc_is_literal",
        "and_or_lists_stay_together",
        "background_ampersand_ends_command",
        "redirection_ampersands_are_not_separators",
        "backtick_substitution",
        "substitution_inside_double_quotes",
        "parameter_expansion",
        "arithmetic_expansion",
        "subshell_group",
        "brace_group",
        "brace_expansion_is_not_a_group",
    ],
)
def test_split_respects_quoting_and_grouping(script: str, expected_commands: list[str]) -> None:
    """Check that separators inside quotes, substitutions, and groups do not end a command"""
    commands = split_into_command_text(script)

    assert commands == expected_commands


@pytest.mark.parametrize(
    ("script", "expected_commands"),
    [
        ("if true; then echo a; else echo b; fi\necho c", ["if true; then echo a; else echo b; fi", "echo c"]),
        ("if true\nthen\n  echo a\nfi\necho c", ["if true\nthen\n  echo a\nfi", "echo c"]),
        ("for name in a b; do echo $name; done; echo c", ["for name in a b; do echo $name; done", "echo c"]),
        ("while read x; do echo $x; done < file\necho c", ["while read x; do echo $x; done < file", "echo c"]),
        ("until false; do break; done; echo c", ["until false; do break; done", "echo c"]),
        ("case $x in\n  a) echo;;\n  *) ls;;\nesac\necho c", ["case $x in\n  a) echo;;\n  *) ls;;\nesac", "echo c"]),
        ("greet() {\n  echo hi\n}\ngreet", ["greet() {\n  echo hi\n}", "greet"]),
        ("function greet {\n  echo hi\n}; greet", ["function greet {\n  echo hi\n}", "greet"]),
        ("if true; then\n  for x in 1; do ls; done\nfi; ls", ["if true; then\n  for x in 1; do ls; done\nfi", "ls"]),
        ("echo fi; echo done; echo esac", ["echo fi", "echo done", "echo esac"]),
    ],
    ids=[
        "if_on_one_line",
        "if_across_lines",
        "for_loop",
        "while_loop_with_redirection",
        "until_loop",
        "case_statement",
        "function_with_parentheses",
        "function_keyword",
        "nested_compound",
        "keywords_as_arguments_are_plain_words",
    ],
)
def test_split_keeps_compound_commands_together(script: str, expected_commands: list[str]) -> None:
    """Check that a compound command is one unit however many lines and semicolons it spans"""
    commands = split_into_command_text(script)

    assert commands == expected_commands


@pytest.mark.parametrize(
    ("script", "expected_commands"),
    [
        ("cat <<EOF\na; b\nEOF\necho c", ["cat <<EOF\na; b\nEOF", "echo c"]),
        ("cat <<-EOF\n\ta; b\n\tEOF\necho c", ["cat <<-EOF\n\ta; b\n\tEOF", "echo c"]),
        ("cat <<'EOF'\n$x; b\nEOF\necho c", ["cat <<'EOF'\n$x; b\nEOF", "echo c"]),
        ('cat <<"EOF"\na\nEOF\necho c', ['cat <<"EOF"\na\nEOF', "echo c"]),
        ("tee out <<EOF > log\nbody\nEOF\necho c", ["tee out <<EOF > log\nbody\nEOF", "echo c"]),
        ("diff <(cat <<A\nx\nA\n) - <<B\ny\nB\necho c", ["diff <(cat <<A\nx\nA\n) - <<B\ny\nB", "echo c"]),
        ("cat <<A <<B\n1\nA\n2\nB\necho c", ["cat <<A <<B\n1\nA\n2\nB", "echo c"]),
        ("cat <<< 'here string'; echo c", ["cat <<< 'here string'", "echo c"]),
        ("if true; then\n  cat <<EOF\n  a\nEOF\nfi\necho c", ["if true; then\n  cat <<EOF\n  a\nEOF\nfi", "echo c"]),
        ("cat <<EOF\nnever closed; still body", ["cat <<EOF\nnever closed; still body"]),
    ],
    ids=[
        "plain_heredoc",
        "dash_heredoc_strips_tabs",
        "single_quoted_delimiter",
        "double_quoted_delimiter",
        "redirection_after_operator",
        "heredoc_inside_process_substitution",
        "two_heredocs_on_one_line",
        "here_string_is_not_a_heredoc",
        "heredoc_inside_compound",
        "unterminated_heredoc_runs_to_end",
    ],
)
def test_split_keeps_heredoc_bodies_with_their_command(script: str, expected_commands: list[str]) -> None:
    """Check that heredoc bodies are never split, whatever delimiter form is used"""
    commands = split_into_command_text(script)

    assert commands == expected_commands


@pytest.mark.parametrize(
    ("script", "expected_commands"),
    [
        ("# only a comment\necho a", ["echo a"]),
        ("echo a # trailing; not a command\necho b", ["echo a", "echo b"]),
        ("echo a#b; echo c", ["echo a#b", "echo c"]),
        ("echo '#not'; echo \"#not\"", ["echo '#not'", 'echo "#not"']),
        ("", []),
        ("\n\n; ;\n", []),
        ("   echo a   \n\n\n", ["echo a"]),
    ],
    ids=[
        "whole_line_comment_dropped",
        "trailing_comment_dropped",
        "hash_inside_word_kept",
        "hash_inside_quotes_kept",
        "empty_script",
        "only_separators",
        "surrounding_whitespace_trimmed",
    ],
)
def test_split_drops_comments_and_empty_commands(script: str, expected_commands: list[str]) -> None:
    """Check that comments and blank lines never produce a command"""
    commands = split_into_command_text(script)

    assert commands == expected_commands
