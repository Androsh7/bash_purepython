"""Test the builtins that change the shell: read, set, local, aliases, the directory stack and the rest"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("read x <<< hello; echo [$x]", "[hello]\n"),
        ('read a b <<< "one two three"; echo [$a] [$b]', "[one] [two three]\n"),
        ('echo "a b" | read v w; echo [$v] [$w]', "[] []\n"),
        ("read <<< plain; echo $REPLY", "plain\n"),
        ("read -a words <<< 'x y z'; echo ${words[1]} ${#words[@]}", "y 3\n"),
        ("read -d , x <<< 'a,b'; echo [$x]", "[a]\n"),
        ("read -n 2 x <<< abcd; echo [$x]", "[ab]\n"),
        ("IFS=: read a b <<< 'u:v'; echo $a $b", "u v\n"),
        ("read -r x <<< 'a\\tb'; echo $x; read x <<< 'a\\tb'; echo $x", "a\\tb\natb\n"),
    ],
    ids=["here_string", "last_name_takes_rest", "pipe", "reply", "array", "delimiter", "count", "ifs", "raw"],
)
def test_read_assigns_fields_from_its_input(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that read splits one line of its input into the named variables"""
    run = shell.run(script)

    assert run.stdout == expected


def test_read_in_a_loop_takes_one_line_at_a_time(shell: ShellHarness) -> None:
    """Check that a loop reading from a here-string, a file and a pipe sees every line once"""
    run = shell.run(
        "while read l; do echo got $l; done <<< $'p\\nq'; "
        "printf 'l1\\nl2\\n' > f; while read -r l; do echo \"<$l>\"; done < f; "
        "printf 'a\\nb\\n' | while read l; do echo piped $l; done"
    )

    assert run.stdout == "got p\ngot q\n<l1>\n<l2>\npiped a\npiped b\n"


def test_read_stops_an_endless_producer_when_the_loop_breaks(shell: ShellHarness) -> None:
    """Check that yes piped into a reading loop ends once the loop breaks"""
    run = shell.run("yes | while read l; do echo $l; break; done; echo after")

    assert run.stdout == "y\nafter\n"


def test_read_fails_at_the_end_of_input(shell: ShellHarness) -> None:
    """Check that read returns one when nothing is left to read and no terminal is attached"""
    run = shell.run("read x < /dev/null; echo $?; read y; echo $?")

    assert run.stdout == "1\n1\n"


def test_read_takes_a_line_from_the_host_when_nothing_is_piped(shell: ShellHarness) -> None:
    """Check that read asks the host's line reader for terminal input, showing the prompt first"""
    shell.state.read_line = lambda: "typed line\n"

    run = shell.run("read -p 'name: ' answer; echo [$answer]")

    assert run.stdout == "[typed line]\n"
    assert run.stderr == "name: "


def test_shift_drops_positional_arguments(shell: ShellHarness) -> None:
    """Check that shift removes arguments inside a function and after set --"""
    run = shell.run("f() { shift; echo $1 $#; }; f a b c; set -- x y z; shift 2; echo $1; shift 5; echo $?")

    assert run.stdout == "b 2\nz\n1\n"


def test_set_errexit_stops_the_script_on_a_failure(shell: ShellHarness) -> None:
    """Check that set -e leaves the script at the first failing command with its exit code"""
    run = shell.run("set -e; echo before; false; echo after")

    assert (run.stdout, run.exit_code) == ("before\n", 1)


def test_set_errexit_ignores_failures_in_conditions_and_lists(shell: ShellHarness) -> None:
    """Check that errexit does not fire for if and loop conditions, and-or lists, or negated commands"""
    run = shell.run(
        "set -e; false || echo recovered; false && echo no; if false; then :; fi; "
        "while false; do :; done; ! false; echo done"
    )

    assert (run.stdout, run.exit_code) == ("recovered\ndone\n", 0)


def test_set_nounset_rejects_an_unset_variable(shell: ShellHarness) -> None:
    """Check that set -u fails an expansion of an unset variable but allows defaults"""
    run = shell.run("set -u; echo ${missing:-default}; echo $missing; echo after")

    assert (run.stdout, run.exit_code) == ("default\n", 127)
    assert "missing: unbound variable" in run.stderr


def test_set_xtrace_prints_each_command_before_it_runs(shell: ShellHarness) -> None:
    """Check that set -x traces expanded commands and assignments on standard error"""
    run = shell.run("set -x; x=1; echo $x two")

    assert run.stdout == "1 two\n"
    assert run.stderr == "+ x=1\n+ echo 1 two\n"


def test_set_pipefail_reports_the_failing_stage(shell: ShellHarness) -> None:
    """Check that pipefail makes a pipeline fail when any stage fails, and that it can be turned off"""
    run = shell.run("set -o pipefail; false | true; echo $?; set +o pipefail; false | true; echo $?")

    assert run.stdout == "1\n0\n"


def test_set_replaces_the_positional_arguments(shell: ShellHarness) -> None:
    """Check that set -- and set with plain words set the positional arguments"""
    run = shell.run("set -- a b; echo $2 $#; set c; echo $1 $#")

    assert run.stdout == "b 2\nc 1\n"


def test_local_variables_are_restored_when_the_function_returns(shell: ShellHarness) -> None:
    """Check that local shadows a variable inside a function and the outer value comes back"""
    run = shell.run(
        "x=outer; f() { local x=inner; echo $x; }; f; echo $x; "
        "g() { local y; y=1; }; g; echo [${y-unset}]; "
        "arr=(1 2 3); h() { local -a arr; arr=(9); echo ${#arr[@]}; }; h; echo ${#arr[@]}"
    )

    assert run.stdout == "inner\nouter\n[unset]\n1\n3\n"


def test_local_outside_a_function_fails(shell: ShellHarness) -> None:
    """Check that local complains when there is no function to scope to"""
    run = shell.run("local z=1")

    assert run.exit_code == 1
    assert "can only be used in a function" in run.stderr


def test_eval_runs_its_arguments_as_a_script(shell: ShellHarness) -> None:
    """Check that eval joins its arguments and runs them against the live state"""
    run = shell.run('eval "echo evaled $(echo sub)"; eval x=5; echo $x; eval; echo $?')

    assert run.stdout == "evaled sub\n5\n0\n"


def test_type_describes_each_kind_of_command(shell: ShellHarness) -> None:
    """Check that type names aliases, keywords, functions, builtins and commands, and fails on unknown names"""
    run = shell.run(
        "f() { :; }; alias ll='ls -l'; type f ll if cd cat nothing; echo $?; type -t cat; type -t cd; type -p cat"
    )

    assert run.stdout == (
        "f is a function\nf () \n{ :; }\nll is aliased to `ls -l'\nif is a shell keyword\n"
        "cd is a shell builtin\ncat is /usr/bin/cat\n1\nfile\nbuiltin\n/usr/bin/cat\n"
    )
    assert "nothing: not found" in run.stderr


def test_command_bypasses_a_function_and_reports_names(shell: ShellHarness) -> None:
    """Check that command runs the real command behind a function and that -v names what it finds"""
    run = shell.run(
        "command -v echo cd; command -v nothing; echo $?; echo() { printf 'shadow\\n'; }; command echo real; echo x"
    )

    assert run.stdout == "echo\ncd\n1\nreal\nshadow\n"


def test_aliases_expand_in_the_command_position(shell: ShellHarness) -> None:
    """Check that an alias replaces the command name, chains to another alias, and can be listed and removed"""
    run = shell.run(
        "alias e=echo; e aliased; alias greet='e hi'; greet there; alias; unalias greet; greet; echo $?; "
        "alias e='echo quoted'; e 'e'"
    )

    assert run.stdout == "aliased\nhi there\nalias e='echo'\nalias greet='e hi'\n127\nquoted e\n"
    assert "greet: command not found" in run.stderr


def test_directory_stack_follows_pushd_and_popd(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that pushd, popd and dirs move through directories and print the stack with the home shortened"""
    (tmp_path / "sub").mkdir()
    shell.state.variables["HOME"] = str(tmp_path)

    run = shell.run("pushd sub; dirs; pushd; popd; popd; echo $?")

    assert run.stdout == "~/sub ~\n~/sub ~\n~ ~/sub\n~/sub\n1\n"
    assert "directory stack empty" in run.stderr


def test_let_evaluates_arithmetic_and_reports_zero(shell: ShellHarness) -> None:
    """Check that let assigns through arithmetic and fails when the last value is zero"""
    run = shell.run("let x=1+2 y=x*2; echo $x $y; let 'z = 0'; echo $?")

    assert run.stdout == "3 6\n1\n"


def test_declare_sets_attributes_and_prints_declarations(shell: ShellHarness) -> None:
    """Check that declare handles integers, arrays, exports, -p output and function listings"""
    run = shell.run(
        "declare -i n=2+3; declare -a arr; arr+=(x); declare -x EXP=1; declare -p n arr; env | grep ^EXP=; "
        "f() { echo body; }; declare -F; declare -f f; typeset v=1; echo $v"
    )

    assert run.stdout == ('declare -- n="5"\ndeclare -a arr=([0]="x")\nEXP=1\ndeclare -f f\nf () \n{ echo body; }\n1\n')


def test_declare_inside_a_function_is_local_unless_global(shell: ShellHarness) -> None:
    """Check that declare scopes to the function while declare -g sets the global"""
    run = shell.run("x=outer; f() { declare x=inner; declare -g g=global; }; f; echo $x $g")

    assert run.stdout == "outer global\n"


def test_readonly_variables_reject_assignment(shell: ShellHarness) -> None:
    """Check that assigning to a read-only variable fails and leaves the value alone"""
    run = shell.run("readonly r=1; r=2; echo $? $r; readonly -p")

    assert run.stdout == '1 1\ndeclare -r r="1"\n'
    assert "r: readonly variable" in run.stderr


def test_printf_v_stores_the_text_in_a_variable(shell: ShellHarness) -> None:
    """Check that printf -v assigns instead of printing"""
    run = shell.run("printf -v v 'x%03d' 7; echo [$v]")

    assert run.stdout == "[x007]\n"


def test_unsupported_builtins_say_so(shell: ShellHarness) -> None:
    """Check that exec, trap and getopts fail with a clear message while hash is accepted"""
    run = shell.run("hash; echo $?; exec echo x; echo $?; trap 'echo t' EXIT; echo $?")

    assert run.stdout == "0\n1\n1\n"
    assert "exec: not supported in this shell" in run.stderr


def test_cd_dash_prints_the_directory_it_returns_to(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that cd - goes back and prints where it went"""
    (tmp_path / "sub").mkdir()

    run = shell.run("cd sub; cd -")

    assert run.stdout == tmp_path.resolve().as_posix() + "\n"


def test_jobs_lists_in_bash_layout_and_kill_takes_a_job_spec(shell: ShellHarness) -> None:
    """Check that jobs marks the current and previous job and that kill %N ends a job"""
    run = shell.run("sleep 5 & sleep 5 & jobs; kill %1; sleep 0.01; jobs; kill %%; wait; echo waited")

    assert run.stdout == (
        "[1]-  Running                 sleep 5 &\n[2]+  Running                 sleep 5 &\n"
        "[1]-  Terminated              sleep 5\n[2]+  Running                 sleep 5 &\nwaited\n"
    )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ('declare -a arr=(x y); echo "${arr[1]} ${#arr[@]}"', "y 2\n"),
        ('f() { local -a arr=(p q r); echo "${arr[2]} ${#arr[@]}"; }; f', "r 3\n"),
        ('f() { local arr=(p q); echo "${arr[1]}"; }; f', "q\n"),
        ('v=x; declare -a arr=($v "$v"y); echo "${arr[0]} ${arr[1]}"', "x xy\n"),
    ],
    ids=["declare", "local_with_flag", "local_without_flag", "expanded_elements"],
)
def test_declare_and_local_accept_array_literals(shell: ShellHarness, script: str, expected: str) -> None:
    """Check that an array literal after declare or local populates the array"""
    run = shell.run(script)

    assert run.stdout == expected


def test_read_with_an_empty_delimiter_reads_to_the_end(shell: ShellHarness) -> None:
    """Check that read -d '' slurps every line rather than one character"""
    run = shell.run("read -r -d '' v <<< $'line1\\nline2'; echo \"<$v>\"")

    assert run.stdout == "<line1\nline2>\n"
