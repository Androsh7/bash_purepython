"""Test the sed command through the shell"""

# Standard libraries
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.cat import CatCommand
from bash_purepython.command.echo import EchoCommand
from bash_purepython.command.printf import PrintfCommand
from bash_purepython.command.registry import CommandRegistry
from bash_purepython.command.sed import SedCommand, translate_regex
from bash_purepython.command.yes import YesCommand
from tests.conftest import ShellHarness


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness], tmp_path: Path) -> ShellHarness:
    """Return a harness with sed registered and a five-line file to edit"""
    (tmp_path / "lines.txt").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8", newline="\n")
    (tmp_path / "block.txt").write_text("a\nstart\nb\nc\nend\nd\n", encoding="utf-8")
    return make_shell(CommandRegistry([SedCommand(), EchoCommand(), PrintfCommand(), CatCommand(), YesCommand()]))


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo hi | sed s/hi/bye/", "bye\n"),
        ("sed -n '2p' lines.txt", "two\n"),
        ("sed '1d' lines.txt", "two\nthree\nfour\nfive\n"),
        ("echo aaa | sed -E 's/(a+)/[\\1]/'", "[aaa]\n"),
        ("echo aaa | sed 's/\\(a*\\)/[\\1]/'", "[aaa]\n"),
        ("sed '/start/,/end/d' block.txt", "a\nd\n"),
        ("echo 'x x x' | sed 's/x/y/2'", "x y x\n"),
        ("echo 'x x x' | sed 's/x/y/2g'", "x y y\n"),
        ("sed '$!d' lines.txt", "five\n"),
        ("sed = lines.txt | sed -n '1,4p'", "1\none\n2\ntwo\n"),
        ("echo abcabc | sed 'y/abc/ABC/'", "ABCABC\n"),
        ("sed '2a added' lines.txt", "one\ntwo\nadded\nthree\nfour\nfive\n"),
        ("sed '2i inserted' lines.txt", "one\ninserted\ntwo\nthree\nfour\nfive\n"),
        ("sed '2,4c changed' lines.txt", "one\nchanged\nfive\n"),
        ("sed '3q' lines.txt", "one\ntwo\nthree\n"),
        ("sed -n '$p' lines.txt", "five\n"),
        ("sed -n '1~2p' lines.txt", "one\nthree\nfive\n"),
        ("sed -n '2,+1p' lines.txt", "two\nthree\n"),
        ("sed -n '/two/,4p' lines.txt", "two\nthree\nfour\n"),
        ("sed -n '4,2p' lines.txt", "four\n"),
        ("sed -n -e '1p' -e '3p' lines.txt", "one\nthree\n"),
        ("sed -n '1p;3p' lines.txt", "one\nthree\n"),
        ("sed '2{s/two/TWO/;p}' lines.txt", "one\nTWO\nTWO\nthree\nfour\nfive\n"),
        ("sed -n '/^t/{/e/p}' lines.txt", "three\n"),
        ("echo Hello | sed 's/hello/bye/I'", "bye\n"),
        ("echo Hello | sed -n 's/hello/bye/ip'", "bye\n"),
        ("echo hello | sed 's/l/L/g'", "heLLo\n"),
        ("echo hello | sed 's/l\\+/[&]/'", "he[ll]o\n"),
        ("echo 'a+b' | sed 's/a+b/plus/'", "plus\n"),
        ("echo 'a|b' | sed 's/a|b/pipe/'", "pipe\n"),
        ("echo 'ab' | sed -E 's/a|b/x/g'", "xx\n"),
        ("echo 'aaa' | sed 's/a\\{2\\}/X/'", "Xa\n"),
        ("echo 'a.b' | sed 's/\\./-/'", "a-b\n"),
        ("echo 'a/b' | sed 's,/,\\,,'", "a,b\n"),
        ("echo 'a/b' | sed 's/\\//|/'", "a|b\n"),
        ("echo 'one two' | sed 's/ /\\n/'", "one\ntwo\n"),
        ("echo 'one two' | sed 's/ /\\t/'", "one\ttwo\n"),
        ("echo 'a1b' | sed 's/[[:digit:]]/#/'", "a#b\n"),
        ("echo '*star' | sed 's/*/x/'", "xstar\n"),
        ("echo 'a$b' | sed 's/a$b/money/'", "money\n"),
        ("echo 'a^b' | sed 's/a^b/caret/'", "caret\n"),
        ("echo abc | sed -n '/b/p'", "abc\n"),
        ("echo abc | sed -n '\\,b,p'", "abc\n"),
        ("printf 'a\\nb\\n' | sed '/a/!d'", "a\n"),
        ("printf 'a\\nb\\n' | sed -n '/A/Ip'", "a\n"),
        ("yes | sed 2q", "y\ny\n"),
        ("sed -n '$=' lines.txt", "5\n"),
        ("sed '2,$d' lines.txt", "one\n"),
        ("sed -s -n '$p' lines.txt block.txt", "five\nd\n"),
        ("sed -n '$p' lines.txt block.txt", "d\n"),
        ("sed -n '2p' - < lines.txt", "two\n"),
        ("sed 's/a/b/ ; s/b/c/' block.txt | sed -n 1p", "c\n"),
        ("sed -n '2p # comment' lines.txt", "two\n"),
        ("printf 'x\\ny\\n' | sed '$a\\\nlast'", "x\ny\nlast\n"),
        ("printf 'x' | sed p", "x\nx"),
        ("printf 'x' | sed -n p", "x"),
        ("printf '' | sed p", ""),
    ],
    ids=[
        "substitute_from_pipe",
        "print_line_two",
        "delete_line_one",
        "extended_group",
        "basic_group",
        "regex_range_delete",
        "second_occurrence",
        "second_occurrence_onwards",
        "all_but_last_deleted",
        "line_numbers",
        "transliterate",
        "append_after_line",
        "insert_before_line",
        "change_range",
        "quit_after_three",
        "print_last",
        "step_address",
        "relative_range",
        "regex_to_number_range",
        "backwards_range_is_one_line",
        "two_expressions",
        "semicolon_separated",
        "group",
        "nested_group",
        "case_insensitive_flag",
        "case_insensitive_and_print",
        "global",
        "basic_plus_and_ampersand",
        "basic_plus_is_literal",
        "basic_bar_is_literal",
        "extended_alternation",
        "basic_interval",
        "escaped_dot",
        "custom_delimiter",
        "escaped_slash",
        "newline_in_replacement",
        "tab_in_replacement",
        "posix_class",
        "leading_star_is_literal",
        "inner_dollar_is_literal",
        "inner_caret_is_literal",
        "regex_address",
        "custom_delimiter_address",
        "negated_address",
        "case_insensitive_address",
        "quit_stops_endless_input",
        "last_line_number",
        "delete_to_end",
        "separate_files",
        "continuous_files",
        "explicit_stdin",
        "spaces_around_semicolon",
        "comment",
        "append_classic_form",
        "missing_final_newline_kept",
        "missing_final_newline_kept_quiet",
        "empty_input",
    ],
)
def test_sed_edits_text(shell: ShellHarness, script: str, expected: str) -> None:
    """Check each editing command, address form and regex translation"""
    run = shell.run(script)

    assert (run.stdout, run.stderr, run.exit_code) == (expected, "", 0)


def test_sed_in_place_rewrites_the_file(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -i writes the edited text back and prints nothing"""
    run = shell.run("sed -i 's/o/0/g' lines.txt")

    assert (run.stdout, run.exit_code) == ("", 0)
    assert (tmp_path / "lines.txt").read_text(encoding="utf-8") == "0ne\ntw0\nthree\nf0ur\nfive\n"


def test_sed_in_place_with_suffix_keeps_a_backup(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -i.bak saves the original beside the edited file"""
    shell.run("sed -i.bak '1d' lines.txt")

    assert (tmp_path / "lines.txt.bak").read_text(encoding="utf-8") == "one\ntwo\nthree\nfour\nfive\n"
    assert (tmp_path / "lines.txt").read_text(encoding="utf-8") == "two\nthree\nfour\nfive\n"


def test_sed_in_place_combined_with_other_flags(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -ni and a following -e are both understood"""
    shell.run("sed -ni -e '2p' lines.txt")

    assert (tmp_path / "lines.txt").read_text(encoding="utf-8") == "two\n"


def test_sed_in_place_treats_each_file_separately(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -i restarts line numbers for every file"""
    shell.run("sed -i '1d' lines.txt block.txt")

    assert (tmp_path / "lines.txt").read_text(encoding="utf-8") == "two\nthree\nfour\nfive\n"
    assert (tmp_path / "block.txt").read_text(encoding="utf-8") == "start\nb\nc\nend\nd\n"


def test_sed_quit_exit_code_is_reported(shell: ShellHarness) -> None:
    """Check that q with a number sets the exit code"""
    run = shell.run("sed '2q5' lines.txt")

    assert (run.stdout, run.exit_code) == ("one\ntwo\n", 5)


@pytest.mark.parametrize(
    ("script", "expected_stderr"),
    [
        ("echo hi | sed s/hi/bye", "sed: -e expression #1, char 8: unterminated `s' command\n"),
        ("echo hi | sed k", "sed: -e expression #1, char 1: unknown command: `k'\n"),
        ("echo hi | sed 's/a/b/x'", "sed: -e expression #1, char 7: unknown option to `s'\n"),
        ("echo hi | sed -e p -e k", "sed: -e expression #2, char 1: unknown command: `k'\n"),
        ("echo hi | sed '2{p'", "sed: -e expression #1, char 3: unmatched `{'\n"),
        ("echo hi | sed 'p}'", "sed: -e expression #1, char 2: unexpected `}'\n"),
        ("echo hi | sed 'y/ab/c/'", "sed: -e expression #1, char 7: strings for `y' command are different lengths\n"),
        ("echo hi | sed '2a'", "sed: -e expression #1, char 2: expected \\ after `a', `c' or `i'\n"),
        ("echo hi | sed 's/a/\\1/'", "sed: -e expression #1, char 7: invalid reference \\1 on `s' command's RHS\n"),
        ("echo hi | sed '2'", "sed: -e expression #1, char 1: missing command\n"),
        ("echo hi | sed '0p'", "sed: -e expression #1, char 1: invalid usage of line address 0\n"),
    ],
    ids=[
        "unterminated_substitute",
        "unknown_command",
        "unknown_substitute_option",
        "second_expression_numbered",
        "unmatched_brace",
        "unexpected_brace",
        "transliterate_lengths",
        "append_without_text",
        "invalid_group_reference",
        "missing_command",
        "line_address_zero",
    ],
)
def test_sed_reports_script_errors_in_gnu_wording(shell: ShellHarness, script: str, expected_stderr: str) -> None:
    """Check that a bad script is reported with the expression number and character position"""
    run = shell.run(script)

    assert (run.stdout, run.stderr, run.exit_code) == ("", expected_stderr, 1)


def test_sed_reports_a_missing_file_and_exits_two(shell: ShellHarness) -> None:
    """Check that an unreadable input is named and the other inputs still processed"""
    run = shell.run("sed -n 1p missing.txt lines.txt")

    assert (run.stdout, run.exit_code) == ("one\n", 2)
    assert run.stderr == "sed: can't read missing.txt: No such file or directory\n"


def test_sed_without_a_script_prints_usage(shell: ShellHarness) -> None:
    """Check that running sed with nothing to do is a usage failure"""
    run = shell.run("sed")

    assert run.exit_code == 1
    assert run.stderr.startswith("Usage: sed")


def test_sed_help_goes_to_stdout(shell: ShellHarness) -> None:
    """Check that --help prints usage on stdout and succeeds"""
    run = shell.run("sed --help")

    assert run.exit_code == 0
    assert "usage" in run.stdout.lower()


@pytest.mark.parametrize(
    ("pattern", "extended", "expected"),
    [
        (r"a\(b\)", False, "a(b)"),
        ("a(b)", False, r"a\(b\)"),
        (r"a\{2,3\}", False, "a{2,3}"),
        ("a{2}", False, r"a\{2\}"),
        ("a(b)", True, "a(b)"),
        (r"\<word\>", True, r"\bword\b"),
        ("[^]a]", False, r"[^\]a]"),
        ("[[:space:]]", False, r"[\s]"),
        ("^a^b$c$", False, r"^a\^b\$c$"),
        (r"\(^a\)", False, "(^a)"),
    ],
    ids=[
        "basic_group",
        "basic_literal_parens",
        "basic_interval",
        "basic_literal_braces",
        "extended_group",
        "word_boundaries",
        "bracket_with_leading_close",
        "posix_space_class",
        "anchors_only_at_ends",
        "anchor_after_group_open",
    ],
)
def test_translate_regex_rewrites_posix_dialects(pattern: str, extended: bool, expected: str) -> None:
    """Check the basic and extended regex translation to Python syntax"""
    assert translate_regex(pattern, extended) == expected
