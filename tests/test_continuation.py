"""Test the check that decides when an interactive shell asks for another line"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.continuation import script_needs_more_lines

UNFINISHED_SCRIPTS = [
    "for i in 1 2 3",
    "for i in 1 2 3; do",
    "for i in 1 2 3; do echo $i",
    "for i in 1 2 3\ndo\necho $i",
    "while true; do",
    "until false; do echo x",
    "if true",
    "if true; then echo y",
    "if true; then echo y; else echo n",
    "case x in",
    "case x in\nx) echo matched;;",
    "f() {",
    "f() {\necho x",
    "function f {",
    "f() (",
    "( echo a",
    "{ echo a",
    "{ echo a; echo b",
    "echo a |",
    "echo a |&",
    "echo a &&",
    "echo a ||",
    "echo a && # comment",
    "echo a |\n",
    'echo "abc',
    "echo 'abc",
    'echo "abc\ndef',
    "echo $'open",
    "echo $'it\\'s",
    "echo $(",
    "echo $(echo a",
    'echo "$(echo a"',
    "echo ${x",
    "echo `echo a",
    "echo $((1+",
    "[[ a == a",
    "echo a \\",
    "cat <<EOF",
    "cat <<EOF\nabc",
    "cat <<EOF | cat",
    "cat <<'EOF'\n$x",
    "cat <<-EOF\n\tabc",
    "x=$(cat <<EOF\nabc",
    "if [ -f x ]; then\n  cat <<EOF\nabc",
]

FINISHED_SCRIPTS = [
    "",
    "   ",
    "# just a comment",
    "echo a",
    "echo a;",
    "echo a &",
    "echo a & echo b",
    "echo a | cat",
    "echo a && echo b",
    "echo a || echo b",
    "echo 'a | b'",
    'echo "a &&"',
    "echo a \\\\",
    "echo a\\\\",
    "for i in 1 2 3; do echo $i; done",
    "for i in 1 2 3\ndo\necho $i\ndone",
    "while true; do break; done",
    "if true; then echo y; fi",
    "if true; then echo y\nelse echo n\nfi",
    "case x in x) echo matched;; esac",
    "case x in\nx) echo matched;;\n*) echo other;;\nesac",
    "f() { echo a; }",
    "f() {\necho a\n}",
    "function f { echo a; }",
    "f() ( echo a )",
    "( echo a )",
    "{ echo a; }",
    "echo $(echo a)",
    'echo "$(echo a)"',
    "echo ${x:-y}",
    "echo `echo a`",
    "echo $((1+2))",
    "[[ a == a ]]",
    "[[ a == a ]] && echo y",
    "cat <<EOF\nabc\nEOF",
    "cat <<EOF\nabc\nEOF\necho after",
    "cat <<'EOF'\n$x\nEOF",
    "cat <<-EOF\n\tabc\n\tEOF",
    "cat <<A <<B\na\nA\nb\nB",
    "cat <<< here",
    "x=$(cat <<EOF\nabc\nEOF\n)",
    "echo a > f; echo b >> f",
    "echo a 2>&1 | cat",
    "echo a\necho b",
    "echo a # trailing | comment",
    "echo $'it\\'s' $'a\\\\b'",
]


@pytest.mark.parametrize(
    "text", UNFINISHED_SCRIPTS, ids=[f"unfinished_{index}" for index in range(len(UNFINISHED_SCRIPTS))]
)
def test_unfinished_text_needs_more_lines(text: str) -> None:
    """Check that an open construct makes the shell ask for another line"""
    assert script_needs_more_lines(text) is True


@pytest.mark.parametrize("text", FINISHED_SCRIPTS, ids=[f"finished_{index}" for index in range(len(FINISHED_SCRIPTS))])
def test_finished_text_runs_at_once(text: str) -> None:
    """Check that a complete command does not wait for another line"""
    assert script_needs_more_lines(text) is False
