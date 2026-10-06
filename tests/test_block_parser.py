"""Test turning classified command blocks into plan nodes"""

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.block_parser import build_plan, split_at_operators
from bash_purepython.parse_script import split_script_into_connected_commands
from bash_purepython.shell_state import ShellSyntaxError, UnsupportedBlockError
from bash_purepython.workflow import (
    AndOrListNode,
    BackgroundNode,
    BraceGroupNode,
    ForNode,
    FunctionDefinitionNode,
    IfNode,
    ListOperator,
    PipelineNode,
    PlanNode,
    RedirectionKind,
    SimpleCommandNode,
    SubshellNode,
    UntilNode,
    WhileNode,
)


def plan_for(script: str) -> PlanNode:
    """Return the plan of a script holding exactly one block

    Args:
        script: The script text

    Returns:
        The plan node for its single block
    """
    blocks = split_script_into_connected_commands(script)
    assert len(blocks) == 1
    return build_plan(blocks[0])


@pytest.mark.parametrize(
    ("text", "expected_segments", "expected_operators"),
    [
        ("echo a | cat", ["echo a", "cat"], ["|"]),
        ("echo a |& cat", ["echo a", "cat"], ["|&"]),
        ("true && echo yes || echo no", ["true", "echo yes", "echo no"], ["&&", "||"]),
        ("echo 'a | b' | cat", ["echo 'a | b'", "cat"], ["|"]),
        ('echo "$(echo a | cat)" | cat', ['echo "$(echo a | cat)"', "cat"], ["|"]),
        ("echo $(true && false) && echo b", ["echo $(true && false)", "echo b"], ["&&"]),
        ("ls 2>&1 | cat", ["ls 2>&1", "cat"], ["|"]),
        ("ls &> log | cat", ["ls &> log", "cat"], ["|"]),
        ("cat <<EOF | cat\nbody\nEOF", ["cat <<EOF\nbody\nEOF", "cat"], ["|"]),
        ("(echo a | cat) | cat", ["(echo a | cat)", "cat"], ["|"]),
        ("{ echo a || echo b; } && echo c", ["{ echo a || echo b; }", "echo c"], ["&&"]),
    ],
    ids=[
        "pipe",
        "pipe_with_stderr",
        "and_or",
        "quoted_pipe_kept",
        "pipe_inside_substitution_kept",
        "list_inside_substitution_kept",
        "stderr_redirection_not_an_operator",
        "both_redirection_not_an_operator",
        "heredoc_body_stays_with_its_stage",
        "subshell_stage",
        "brace_group_stage",
    ],
)
def test_split_at_operators_respects_quoting_and_nesting(
    text: str, expected_segments: list[str], expected_operators: list[str]
) -> None:
    """Check that only top-level unquoted operators split a block"""
    segments, operators = split_at_operators(text)

    assert (segments, operators) == (expected_segments, expected_operators)


def test_split_at_operators_rejects_a_missing_operand() -> None:
    """Check that an operator with nothing after it is a syntax error"""
    with pytest.raises(ShellSyntaxError):
        split_at_operators("echo a |")


def test_build_plan_makes_a_simple_command() -> None:
    """Check that a plain command becomes one simple command node holding its text"""
    node = plan_for("echo hello world")

    assert node == SimpleCommandNode(text="echo hello world")


def test_build_plan_makes_a_pipeline_with_stderr_merges() -> None:
    """Check that a pipeline records each stage and which pipes carry stderr"""
    node = plan_for("yes |& head -n 3 | cat")

    assert node == PipelineNode(
        stages=[SimpleCommandNode("yes"), SimpleCommandNode("head -n 3"), SimpleCommandNode("cat")],
        merge_stderr=[True, False],
    )


def test_build_plan_marks_a_negated_command() -> None:
    """Check that a leading bang negates a single command as a one-stage pipeline"""
    node = plan_for("! true")

    assert node == PipelineNode(stages=[SimpleCommandNode("true")], merge_stderr=[], negated=True)


def test_build_plan_makes_an_and_or_list_of_pipelines() -> None:
    """Check that pipelines inside a list stay grouped under their operators"""
    node = plan_for("echo a | cat && echo b || echo c | cat")

    assert node == AndOrListNode(
        first=PipelineNode(stages=[SimpleCommandNode("echo a"), SimpleCommandNode("cat")], merge_stderr=[False]),
        rest=[
            (ListOperator.AND, SimpleCommandNode("echo b")),
            (
                ListOperator.OR,
                PipelineNode(stages=[SimpleCommandNode("echo c"), SimpleCommandNode("cat")], merge_stderr=[False]),
            ),
        ],
    )


def test_build_plan_unwraps_a_background_command() -> None:
    """Check that the trailing ampersand is removed and the command wrapped"""
    node = plan_for("sleep 1 &")

    assert node == BackgroundNode(inner=SimpleCommandNode("sleep 1"))


def test_build_plan_makes_a_subshell_with_redirection() -> None:
    """Check that a subshell keeps its body text and its trailing redirection"""
    node = plan_for("(cd dir; make) > log")

    assert isinstance(node, SubshellNode)
    assert node.body == "cd dir; make"
    assert [(redirection.kind, redirection.target) for redirection in node.redirections] == [
        (RedirectionKind.WRITE_STDOUT, "log")
    ]


def test_build_plan_makes_a_brace_group() -> None:
    """Check that a brace group keeps its body text without the braces"""
    node = plan_for("{ echo a; echo b; } >> out")

    assert isinstance(node, BraceGroupNode)
    assert node.body == "echo a; echo b;"
    assert [redirection.kind for redirection in node.redirections] == [RedirectionKind.APPEND_STDOUT]


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("if true; then echo a; fi", IfNode(branches=[("true", "echo a")])),
        ("if true; then echo a; else echo b; fi", IfNode(branches=[("true", "echo a")], else_body="echo b")),
        (
            "if a; then echo a; elif b; then echo b; elif c; then echo c; else echo d; fi",
            IfNode(branches=[("a", "echo a"), ("b", "echo b"), ("c", "echo c")], else_body="echo d"),
        ),
        ("if true\nthen\n  echo a\n  echo b\nfi", IfNode(branches=[("true", "echo a\necho b")])),
        (
            "if true; then\n  if false; then echo inner; fi\nfi",
            IfNode(branches=[("true", "if false; then echo inner; fi")]),
        ),
    ],
    ids=["one_line", "with_else", "elif_chain", "multi_line_body", "nested_if_stays_whole"],
)
def test_build_plan_makes_if_nodes(script: str, expected: IfNode) -> None:
    """Check that every branch of an if statement is captured in order"""
    assert plan_for(script) == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("for x in a b c; do echo $x; done", ForNode(variable="x", words_text="a b c", body="echo $x")),
        ("for x in a b\ndo\n  echo $x\ndone", ForNode(variable="x", words_text="a b", body="echo $x")),
        ("for x; do echo $x; done", ForNode(variable="x", words_text=None, body="echo $x")),
        ("for x in; do echo $x; done", ForNode(variable="x", words_text="", body="echo $x")),
        ("while true; do break; done", WhileNode(condition="true", body="break")),
        ("until false\ndo\n  echo a\n  break\ndone", UntilNode(condition="false", body="echo a\nbreak")),
    ],
    ids=["for_words", "for_multi_line", "for_positional", "for_empty_list", "while", "until_multi_line"],
)
def test_build_plan_makes_loop_nodes(script: str, expected: PlanNode) -> None:
    """Check that loop headers and bodies are separated at do and done"""
    assert plan_for(script) == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("greet() { echo hi; }", FunctionDefinitionNode(name="greet", body="{ echo hi; }")),
        ("greet () {\n  echo hi\n}", FunctionDefinitionNode(name="greet", body="{\n  echo hi\n}")),
        ("function greet { echo hi; }", FunctionDefinitionNode(name="greet", body="{ echo hi; }")),
        ("function greet() ( echo hi )", FunctionDefinitionNode(name="greet", body="( echo hi )")),
    ],
    ids=["parentheses", "spaced_multi_line", "keyword", "keyword_with_subshell_body"],
)
def test_build_plan_makes_function_definitions(script: str, expected: FunctionDefinitionNode) -> None:
    """Check that the function name and its group body are separated"""
    assert plan_for(script) == expected


@pytest.mark.parametrize(
    "script",
    ["case $x in a) echo;; esac", "select x in a b; do echo $x; done", "while true; do break; done < file"],
    ids=["case", "select", "loop_redirection"],
)
def test_build_plan_rejects_unsupported_blocks(script: str) -> None:
    """Check that constructs outside this slice raise rather than misbehave"""
    with pytest.raises(UnsupportedBlockError):
        plan_for(script)
