"""Test running script files and inline scripts with bash, sh, source and by path"""

# Standard libraries
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from tests.conftest import ShellHarness


def write_script(directory: Path, name: str, *lines: str) -> None:
    """Write a script file, one argument per line

    Args:
        directory: The directory to write into
        name: The file name
        lines: The lines of the script
    """
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize("command", ["bash", "sh"], ids=str)
def test_shell_command_runs_a_script_file_with_its_arguments(shell: ShellHarness, tmp_path: Path, command: str) -> None:
    """Check that the script sees the words after its name as positional arguments"""
    write_script(tmp_path, "greet.sh", "#!/bin/bash", 'echo "$# args: $1 and $2"')

    run = shell.run(f"{command} greet.sh first 'second word'")

    assert run.stdout == "2 args: first and second word\n"


def test_script_exit_code_becomes_the_command_exit_code_and_stops_the_script(
    shell: ShellHarness, tmp_path: Path
) -> None:
    """Check that exit ends the script only, with its code visible to the caller"""
    write_script(tmp_path, "stop.sh", "echo before", "exit 4", "echo after")

    run = shell.run('bash stop.sh; echo "rc=$?"')

    assert run.stdout.splitlines() == ["before", "rc=4"]


def test_script_run_with_bash_does_not_change_the_calling_shell(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that variables and the directory a script changes stay inside it"""
    (tmp_path / "inner").mkdir()
    write_script(tmp_path, "change.sh", "name=inside", "cd inner")

    run = shell.run("name=outside; bash change.sh; echo $name; pwd")

    name, directory = run.stdout.splitlines()
    assert (name, Path(directory)) == ("outside", tmp_path)


def test_script_run_with_bash_sees_the_callers_variables(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a script starts from a copy of the calling shell's variables"""
    write_script(tmp_path, "show.sh", "echo $shared")

    run = shell.run("shared=visible; bash show.sh")

    assert run.stdout == "visible\n"


@pytest.mark.parametrize("command", ["source", "."], ids=["source", "dot"])
def test_sourced_script_changes_the_calling_shell(shell: ShellHarness, tmp_path: Path, command: str) -> None:
    """Check that variables and functions a sourced file defines remain afterwards"""
    write_script(tmp_path, "library.sh", "name=sourced", 'hello() { echo "hello $1"; }')

    run = shell.run(f"{command} library.sh; echo $name; hello there")

    assert run.stdout.splitlines() == ["sourced", "hello there"]


def test_sourced_script_can_return_early(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that return leaves a sourced file with its code and the caller carries on"""
    write_script(tmp_path, "early.sh", "echo first", "return 6", "echo never")

    run = shell.run('source early.sh; echo "rc=$?"')

    assert run.stdout.splitlines() == ["first", "rc=6"]


def test_inline_script_takes_its_arguments_after_the_script_name(shell: ShellHarness) -> None:
    """Check that bash -c runs its text with the word after it as the name and the rest as arguments"""
    run = shell.run("bash -c 'echo \"$1-$2\"' name one two")

    assert run.stdout == "one-two\n"


def test_shell_command_without_a_file_reads_the_script_from_standard_input(shell: ShellHarness) -> None:
    """Check that a script piped into bash is run"""
    run = shell.run("echo 'echo from stdin' | bash")

    assert run.stdout == "from stdin\n"


def test_script_named_by_its_path_runs(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a command name holding a slash runs that file"""
    write_script(tmp_path, "tool.sh", 'echo "tool $1"')

    run = shell.run("./tool.sh arg")

    assert run.stdout == "tool arg\n"


def test_script_output_streams_through_a_pipeline(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that an endless script stops once the next stage has read enough"""
    write_script(tmp_path, "forever.sh", "while true; do echo line; done")

    run = shell.run("bash forever.sh | head -n 2")

    assert run.stdout.splitlines() == ["line", "line"]


def test_script_reads_the_input_piped_into_it(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a command inside the script consumes what was piped to the script"""
    write_script(tmp_path, "upper.sh", "cat | rev")

    run = shell.run("echo abc | bash upper.sh")

    assert run.stdout == "cba\n"


def test_script_output_can_be_redirected_and_captured(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a script's output goes to a file or a substitution like any command's"""
    write_script(tmp_path, "say.sh", "echo said")

    run = shell.run('bash say.sh > out.txt; cat out.txt; echo "got $(bash say.sh)"')

    assert run.stdout.splitlines() == ["said", "got said"]


def test_multi_line_script_with_loop_function_and_condition(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a script using several constructs across lines runs top to bottom"""
    write_script(
        tmp_path,
        "program.sh",
        "total=0",
        "add() {",
        "  total=$((total + $1))",
        "}",
        "for number in 1 2 3; do",
        "  add $number",
        "done",
        "if [[ $total -eq 6 ]]; then",
        '  echo "total $total"',
        "fi",
    )

    run = shell.run("bash program.sh")

    assert run.stdout == "total 6\n"


@pytest.mark.parametrize(
    ("script", "expected_exit_code"),
    [
        ("bash missing.sh", 127),
        ("source missing.sh", 1),
        ("./missing.sh", 127),
        ("bash .", 126),
        ("source", 2),
        ("bash -c", 2),
        ("bash --unknown-option file", 2),
    ],
    ids=[
        "bash_missing_file",
        "source_missing_file",
        "path_missing_file",
        "directory",
        "source_without_a_file",
        "inline_without_text",
        "unknown_option",
    ],
)
def test_script_that_cannot_start_reports_why(shell: ShellHarness, script: str, expected_exit_code: int) -> None:
    """Check the exit code and that a message is printed when a script cannot be run"""
    run = shell.run(script)

    assert run.exit_code == expected_exit_code
    assert run.stderr != ""
