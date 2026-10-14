"""Test brace expansion, ANSI-C quoting, IFS splitting, arrays and the parameter operators"""

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo {a,b}{1,2}", "a1 a2 b1 b2\n"),
        ("echo {1..5} {5..1} {1..10..3}", "1 2 3 4 5 5 4 3 2 1 1 4 7 10\n"),
        ("echo {01..03} {a..e} {e..a..2}", "01 02 03 a b c d e e c a\n"),
        ("echo x{,a} {a} {} pre{a,b}post", "x xa {a} {} preapost prebpost\n"),
        ("echo {a,b{1,2}}", "a b1 b2\n"),
        ("echo '{a,b}' \"{1..2}\" \\{a,b\\}", "{a,b} {1..2} {a,b}\n"),
        ("x={a,b}; echo $x; echo ${x}y", "{a,b}\n{a,b}y\n"),
        ("f() { echo $#; }; f {1..3}", "3\n"),
        ("printf '[%s]' {,a}; echo", "[a]\n"),
    ],
    ids=[
        "lists",
        "ranges",
        "padded_and_letters",
        "literals",
        "nested",
        "quoted",
        "assignment",
        "fields",
        "empty_alternative",
    ],
)
def test_brace_expansion(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that unquoted brace lists and ranges expand into words and quoted ones stay literal"""
    run = shell.run(script)

    assert run.stdout == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo $'a\\tb'", "a\tb\n"),
        ("echo $'x\\x41\\u00e9\\101'", "xAéA\n"),
        ("echo $'it\\'s' $'a\\\\b'", "it's a\\b\n"),
        ("x=$'l1\\nl2'; echo \"$x\"", "l1\nl2\n"),
    ],
    ids=["tab", "hex_unicode_octal", "escaped_quote_and_backslash", "assignment"],
)
def test_ansi_c_quoting(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that $'...' decodes backslash escapes"""
    run = shell.run(script)

    assert run.stdout == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("IFS=,; x=a,b,,c; for w in $x; do echo [$w]; done", "[a]\n[b]\n[]\n[c]\n"),
        ("IFS=,; x=,a,; for w in $x; do echo [$w]; done", "[]\n[a]\n"),
        ('IFS=:; set -- a b; echo "$*"; echo "$@"', "a:b\na b\n"),
        ("IFS=' ,'; x='a, b  c'; for w in $x; do echo [$w]; done", "[a]\n[b]\n[c]\n"),
        ("x='a  b'; for w in $x; do echo [$w]; done", "[a]\n[b]\n"),
    ],
    ids=["comma", "edges", "star_join", "mixed", "default"],
)
def test_ifs_controls_word_splitting(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that IFS decides where unquoted expansions split, with empty fields between non-blank separators"""
    run = shell.run(script)

    assert run.stdout == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("x=abcabc; echo ${x#ab} ${x##*a} ${x%bc} ${x%%c*}", "cabc bc abca ab\n"),
        ("x=abcabc; echo ${x/b/X} ${x//b/X} ${x/#a/Z} ${x/%c/Z} ${x/b}", "aXcabc aXcaXc Zbcabc abcabZ acabc\n"),
        ("x=abc; echo ${x^} ${x^^} ${x,} ${x^^[ab]}; y=ABC; echo ${y,,} ${y,}", "Abc ABC abc ABc\nabc aBC\n"),
        ("y=x; x=val; echo ${!y}", "val\n"),
        ("x=abcdef; echo ${x:1} ${x:1:2} ${x: -2} ${x:(-3):2} ${x:1:-1}", "bcdef bc ef de bcde\n"),
        ("x='a b'; echo ${x// /_}; p=' '; echo ${x/$p/-}", "a_b\na-b\n"),
        ("f() { echo ${@:2} ${*:1:1} ${#@}; }; f a b c", "b c a 3\n"),
        ("echo ${#} ${#x}; x=hello; echo ${#x}", "0 0\n5\n"),
        ("echo $$ $PPID; echo $RANDOM | grep -qE '^[0-9]+$' && echo random; echo ${SECONDS}", "1 0\nrandom\n0\n"),
    ],
    ids=[
        "removal",
        "substitution",
        "case",
        "indirection",
        "substring",
        "substitute_variable",
        "positional_slices",
        "lengths",
        "special",
    ],
)
def test_parameter_operators(shell: ShellHarness, script: str, expected: str) -> None:
    """Check pattern removal, substitution, case modification, indirection, substrings and lengths"""
    run = shell.run(script)

    assert run.stdout == expected


def test_unknown_parameter_operator_is_a_bad_substitution(shell: ShellHarness) -> None:
    """Check that an operator the shell does not know is rejected the way bash rejects it"""
    run = shell.run("x=1; echo ${x@Q}")

    assert run.exit_code == 1
    assert "bad substitution" in run.stderr


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("a=(1 2 3); echo ${a[1]} ${#a[@]} ${a[@]} ${a[*]} ${a[-1]} ${!a[@]} $a", "2 3 1 2 3 1 2 3 3 0 1 2 1\n"),
        ('a=(x y z); for v in "${a[@]}"; do echo [$v]; done; echo ${#a[1]}', "[x]\n[y]\n[z]\n1\n"),
        ("a=(1 2 3); a+=(4); a[6]=7; echo ${a[@]} ${#a[@]} ${!a[@]}", "1 2 3 4 7 5 0 1 2 3 6\n"),
        ("a=(a b c d); echo ${a[@]:1:2} ${a[@]/b/B} ${a[@]^^} ${a[@]#a}", "b c a B c d A B C D b c d\n"),
        ("a=('a b' c); echo ${#a[@]}; for v in \"${a[@]}\"; do echo [$v]; done", "2\n[a b]\n[c]\n"),
        ('b=(); echo [${b[@]}] ${#b[@]}; for v in "${b[@]}"; do echo never; done; echo end', "[] 0\nend\n"),
        ("a=(1 2 3); unset a[1]; echo ${a[@]} ${!a[@]}; unset a; echo [${a[@]}]", "1 3 0 2\n[]\n"),
        (
            "a=(1 2); a[0]+=x; echo ${a[@]}; s=abc; s[1]=Q; echo ${s[@]}; t=hi; t+=there; echo $t",
            "1x 2\nabc Q\nhithere\n",
        ),
        ("a=(1 2 3); echo ${a[$((1+1))]} ${a[1+1]}; i=0; echo ${a[i]}", "3 3\n1\n"),
        ("a=(x=1 y); echo ${a[@]}; f() { echo in; }; f; g=(1); echo ${g[0]}", "x=1 y\nin\n1\n"),
        (
            '[[ abc =~ ^a(b)(c) ]] && m=("${BASH_REMATCH[@]}"); echo ${m[0]} ${m[1]} ${m[2]} ${#m[@]}',
            "abc b c 3\n",
        ),
        ("a=(1 2); ( a+=(3); echo ${#a[@]} ); echo ${#a[@]}", "3\n2\n"),
    ],
    ids=[
        "basics",
        "quoted_elements",
        "append_and_sparse",
        "element_wise_operators",
        "elements_with_spaces",
        "empty_array",
        "unset",
        "append_to_element_and_scalar",
        "arithmetic_subscripts",
        "not_a_function",
        "rematch",
        "subshell_copy",
    ],
)
def test_arrays(shell: ShellHarness, script: str, expected: str) -> None:
    """Check indexed array assignment, expansion, slicing, element-wise operators and BASH_REMATCH"""
    run = shell.run(script)

    assert run.stdout == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ('set --; echo "[${1-default}]"', "[default]\n"),
        ('set -- ""; echo "[${1-default}] [${1:-default}]"', "[] [default]\n"),
        ('set -- a; echo "[${1-default}] [${2-default}]"', "[a] [default]\n"),
        ('echo "[${0-default}] [${?-default}]"', "[bash] [0]\n"),
    ],
    ids=["unset_positional", "empty_positional", "second_positional", "special_parameters_always_set"],
)
def test_positional_parameters_count_as_set_only_when_given(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that a default applies to a positional parameter that was never given"""
    run = shell.run(script)

    assert run.stdout == expected


@pytest.mark.parametrize(
    "script",
    ['set --; echo "${1?missing}"', 'set --; set -u; echo "$1"', 'set --; set -u; echo "${1}"'],
    ids=["error_operator", "nounset_bare", "nounset_braced"],
)
def test_unset_positional_parameter_is_reported(shell: ShellHarness, script: str) -> None:
    """Check that an unset positional parameter fails under ${1?} and set -u"""
    run = shell.run(script)

    assert run.stdout == ""
    assert run.exit_code != 0


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ('x=(a b); x[5]=f; echo "${x[-1]}"', "f\n"),
        ('x=(a b c); unset x[1]; echo "${x[-1]} ${x[-3]}"', "c a\n"),
    ],
    ids=["sparse_tail", "after_unset"],
)
def test_negative_subscript_counts_back_from_the_highest_index(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that a negative subscript on a sparse array reaches the last element bash would"""
    run = shell.run(script)

    assert run.stdout == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("x='*abc'; echo \"${x#\"*\"}\" ${x#\\*} ${x#'*'} ${x#*}", "abc abc abc *abc\n"),
        ('z=\'a*b*c\'; echo "${z//\\*/+}" "${z/\'*\'/ }" "${z//"*"}"', "a+b+c a b*c abc\n"),
        ('q=\'x[y]\'; echo "${q#"x["}" "${q/"["/<}"', "y] x<y]\n"),
        ('w=\'hello world\'; v=lo; echo "${w/$v/LO}" "${w#*"$v"}" "${w/o/\\/}"', "helLO world  world hell/ world\n"),
        ("p=abc; echo ${p^b} ${p^a} ${p^^[ab]}", "abc Abc ABc\n"),
    ],
    ids=["removal", "substitution", "bracket", "variables_and_slash", "case"],
)
def test_parameter_patterns_match_quoted_characters_literally(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that quoted or escaped glob characters in a pattern operand match only themselves"""
    run = shell.run(script)

    assert run.stdout == expected


def test_nounset_treats_ifs_as_set(shell: ShellHarness) -> None:
    """Check that set -u allows saving and restoring IFS before it was ever assigned"""
    run = shell.run('set -u; old=$IFS; IFS=:; IFS=$old; x="a b"; set -- $x; echo $#')

    assert (run.stdout, run.exit_code) == ("2\n", 0)
