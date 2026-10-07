"""Check the Pyodide session relays host commands through the engine and reports its state"""

# Standard libraries
import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.pyodide_session import PyodideSession


@dataclass
class FakeOutputPiece:
    """Hold one piece of output a fake host command produced"""

    kind: str
    text: str


@dataclass
class FakeHostCallHandle:
    """Replay scripted output for one host command and remember whether the engine stopped reading"""

    pieces: list[FakeOutputPiece]
    code: int = 0
    cancelled: bool = False

    async def __aiter__(self) -> AsyncIterator[FakeOutputPiece]:
        for piece in self.pieces:
            yield piece

    def exit_code(self) -> int:
        return self.code

    def cancel(self) -> None:
        self.cancelled = True


@dataclass
class FakeHost:
    """Record every host call and answer each from a table of scripted handles"""

    handles: dict[str, FakeHostCallHandle]
    calls: list[tuple[str, list[str]]] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    attached: list[bool] = field(default_factory=list)
    piped_inputs: list[str | None] = field(default_factory=list)
    process_directories: list[Path] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def start(
        self, name: str, arguments: list[str], cwd: str, attached: bool, piped_input: str | None
    ) -> FakeHostCallHandle:
        self.piped_inputs.append(piped_input)
        self.process_directories.append(Path.cwd())
        self.calls.append((name, arguments))
        self.directories.append(cwd)
        self.attached.append(attached)
        return self.handles[name]


def build_session(home: Path, host: FakeHost) -> PyodideSession:
    return PyodideSession(
        home=str(home),
        environment={"USER": "guest"},
        host_command_names=list(host.handles),
        start_host_call=host.start,
        write_output=host.output.append,
        write_error=host.errors.append,
    )


def run(session: PyodideSession, script: str) -> dict:
    return json.loads(asyncio.run(session.run(script)))


@pytest.fixture(autouse=True)
def restore_process_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test in its own directory and put the process back afterwards, since a session moves it"""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def host() -> FakeHost:
    return FakeHost(
        handles={
            "fetchy": FakeHostCallHandle(
                pieces=[FakeOutputPiece("stdout", "line one\n"), FakeOutputPiece("stdout", "line two\n")]
            ),
            "broken": FakeHostCallHandle(pieces=[FakeOutputPiece("stderr", "broken: no\n")], code=3),
        }
    )


def test_host_command_output_reaches_the_terminal(tmp_path: Path, host: FakeHost) -> None:
    """Check that what a host command prints is written to the output sink with its arguments passed through"""
    session = build_session(tmp_path, host)

    result = run(session, "fetchy https://example.test -i")

    assert "".join(host.output) == "line one\nline two\n"
    assert host.calls == [("fetchy", ["https://example.test", "-i"])]
    assert result["exit_code"] == 0


def test_host_command_receives_the_directory_current_when_it_runs(tmp_path: Path, host: FakeHost) -> None:
    """Check that a cd earlier on the same line is seen by the host command that follows it"""
    (tmp_path / "notes").mkdir()
    session = build_session(tmp_path, host)

    run(session, "cd notes; fetchy")

    assert [Path(directory) for directory in host.directories] == [(tmp_path / "notes").resolve()]


@pytest.mark.parametrize(
    "script",
    ["fetchy", "true && fetchy", "if true; then fetchy; fi", "cd .; fetchy"],
    ids=["alone", "after-and", "inside-if", "after-another-command"],
)
def test_host_command_is_attached_when_nothing_stands_between_it_and_the_terminal(
    tmp_path: Path, host: FakeHost, script: str
) -> None:
    """Check that a host command writing straight to the terminal is told so"""
    session = build_session(tmp_path, host)

    run(session, script)

    assert host.attached == [True]


@pytest.mark.parametrize(
    "script",
    [
        "fetchy | head -n 1",
        "echo x | fetchy",
        "fetchy > saved.txt",
        "fetchy >> saved.txt",
        "fetchy 2> errors.txt",
        "fetchy &> both.txt",
        "fetchy 2>&1",
        "value=$(fetchy)",
        "{ fetchy; } > saved.txt",
        "( fetchy ) | cat",
    ],
    ids=[
        "piped-out",
        "piped-in",
        "stdout-to-file",
        "stdout-appended",
        "stderr-to-file",
        "both-to-file",
        "stderr-joined",
        "captured",
        "group-redirected",
        "subshell-piped",
    ],
)
def test_host_command_is_not_attached_when_its_output_is_piped_captured_or_redirected(
    tmp_path: Path, host: FakeHost, script: str
) -> None:
    """Check that a host command whose output the shell must route is told it is not on the terminal"""
    session = build_session(tmp_path, host)

    run(session, script)

    assert host.attached == [False]


def test_host_command_receives_input_piped_into_it(tmp_path: Path, host: FakeHost) -> None:
    """Check that the output of the previous pipeline stage is handed to the host command whole"""
    session = build_session(tmp_path, host)

    run(session, "printf 'one\\ntwo\\n' | fetchy")

    assert host.piped_inputs == ["one\ntwo\n"]


def test_host_command_receives_input_redirected_from_a_file(tmp_path: Path, host: FakeHost) -> None:
    """Check that a file named after < is handed to the host command, which stays attached"""
    (tmp_path / "answers.txt").write_text("bob\n", encoding="utf-8")
    session = build_session(tmp_path, host)

    run(session, "fetchy < answers.txt")

    assert (host.piped_inputs, host.attached) == (["bob\n"], [True])


def test_host_command_gets_no_input_when_nothing_is_piped(tmp_path: Path, host: FakeHost) -> None:
    """Check that a host command run on its own is told there is no piped input, so it reads the terminal"""
    session = build_session(tmp_path, host)

    run(session, "fetchy")

    assert host.piped_inputs == [None]


def test_host_command_output_flows_through_a_pipeline(tmp_path: Path, host: FakeHost) -> None:
    """Check that a host command's output is read by the next pipeline stage"""
    session = build_session(tmp_path, host)

    run(session, "fetchy | head -n 1")

    assert "".join(host.output) == "line one\n"


def test_host_command_output_can_be_redirected_to_a_file(tmp_path: Path, host: FakeHost) -> None:
    """Check that redirecting a host command writes its output to the file and not the terminal"""
    session = build_session(tmp_path, host)

    run(session, "fetchy > saved.txt")

    assert (tmp_path / "saved.txt").read_text() == "line one\nline two\n"
    assert host.output == []


def test_host_command_errors_and_exit_code_are_reported(tmp_path: Path, host: FakeHost) -> None:
    """Check that a host command's errors reach the error sink and its exit code becomes the script's"""
    session = build_session(tmp_path, host)

    result = run(session, "broken")

    assert "".join(host.errors) == "broken: no\n"
    assert result["exit_code"] == 3


def test_host_command_is_told_when_the_engine_stops_reading(tmp_path: Path, host: FakeHost) -> None:
    """Check that the handle is cancelled whether the output was read to the end or cut short"""
    session = build_session(tmp_path, host)

    run(session, "fetchy | head -n 1")

    assert host.handles["fetchy"].cancelled is True


def test_run_reports_the_directory_and_variables_after_the_script(tmp_path: Path, host: FakeHost) -> None:
    """Check that cd and export are reflected in the returned state"""
    (tmp_path / "notes").mkdir()
    session = build_session(tmp_path, host)

    result = run(session, "cd notes; export GREETING=hello")

    assert Path(result["cwd"]) == tmp_path / "notes"
    assert result["environment"]["GREETING"] == "hello"
    assert result["environment"]["USER"] == "guest"


def test_state_persists_between_runs(tmp_path: Path, host: FakeHost) -> None:
    """Check that a variable set in one run is visible in the next"""
    session = build_session(tmp_path, host)
    run(session, "export GREETING=hello")

    run(session, "echo $GREETING")

    assert "".join(host.output) == "hello\n"


def test_host_command_runs_with_the_process_in_the_shells_directory(
    tmp_path: Path, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that code the host runs in this interpreter sees the directory the shell is in"""
    (tmp_path / "notes").mkdir()
    monkeypatch.chdir(tmp_path)
    session = build_session(tmp_path, host)

    run(session, "cd notes; fetchy")

    assert host.process_directories == [(tmp_path / "notes").resolve()]


def test_process_returns_home_once_the_host_command_is_over(
    tmp_path: Path, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that the process does not stay inside a directory the shell may go on to remove"""
    (tmp_path / "notes").mkdir()
    monkeypatch.chdir(tmp_path)
    session = build_session(tmp_path, host)

    result = run(session, "cd notes; fetchy; cd ..; rm -r notes")

    assert (result["exit_code"], (tmp_path / "notes").exists()) == (0, False)
    assert Path.cwd() == tmp_path.resolve()


def test_cd_inside_a_subshell_does_not_move_later_host_commands(
    tmp_path: Path, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that a directory change confined to a subshell is not what the next host command runs in"""
    (tmp_path / "notes").mkdir()
    monkeypatch.chdir(tmp_path)
    session = build_session(tmp_path, host)

    run(session, "(cd notes; true); fetchy")

    assert host.process_directories == [tmp_path.resolve()]


def test_run_reports_only_exported_variables_as_the_environment(tmp_path: Path, host: FakeHost) -> None:
    """Check that a plain assignment stays in the session while an export is reported for the next one"""
    session = build_session(tmp_path, host)

    result = run(session, "local_only=1; export SHARED=yes; later=2; export later")

    assert result["environment"]["SHARED"] == "yes"
    assert result["environment"]["later"] == "2"
    assert "local_only" not in result["environment"]


def test_unset_removes_a_variable_from_the_reported_environment(tmp_path: Path, host: FakeHost) -> None:
    """Check that an exported variable is no longer reported once it is unset"""
    session = build_session(tmp_path, host)

    result = run(session, "export GONE=1; unset GONE")

    assert "GONE" not in result["environment"]


def test_a_failure_inside_a_command_is_reported_and_the_state_still_returned(tmp_path: Path, host: FakeHost) -> None:
    """Check that an exception escaping a command gives exit code one on stderr instead of losing the state"""
    (tmp_path / "notes").mkdir()
    host.handles["crashy"] = FakeHostCallHandle(pieces=[], code="not a number")  # type: ignore[arg-type]
    session = build_session(tmp_path, host)

    result = run(session, "cd notes; crashy")

    assert result["exit_code"] == 1
    assert Path(result["cwd"]) == tmp_path / "notes"
    assert "ValueError" in "".join(host.errors)


def test_command_names_cover_builtins_shipped_commands_and_host_commands(tmp_path: Path, host: FakeHost) -> None:
    """Check that the names a host uses for completion and help include every kind of command"""
    session = build_session(tmp_path, host)

    names = set(session.command_names())

    assert {"cd", "export", "cat", "echo", "fetchy", "broken"} <= names


@dataclass
class FakeConsole:
    """Stand in for the Pyodide console, holding only the lines of an unfinished block"""

    buffer: list[str]


def test_repl_discard_forgets_an_unfinished_block(tmp_path: Path, host: FakeHost) -> None:
    """Check that the lines of a block the console was still waiting on are dropped"""
    session = build_session(tmp_path, host)
    session.console = FakeConsole(buffer=["def half_typed():"])

    session.repl_discard()

    assert session.console.buffer == []
