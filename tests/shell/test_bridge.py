"""Tests for the JSON facade a host calls"""

# Standard libraries
import json
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.shell import bridge
from bash_purepython.shell.bridge import ShellNotStartedError


@pytest.fixture
def started_bridge(shell_home: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Start the bridge shell in the isolated home and return the start payload"""
    monkeypatch.setattr(bridge, "SHELL_SESSION", None)
    monkeypatch.setattr(bridge, "REPL_SESSION", None)
    payload = json.dumps(
        {
            "home": str(shell_home),
            "environment": {"HOME": str(shell_home)},
            "history": ["echo earlier"],
            "host_commands": [{"name": "vim", "summary": "edit"}],
            "columns": 100,
        }
    )
    return bridge.start_shell(payload)


def test_start_shell_returns_every_command_name(started_bridge: str) -> None:
    """Check that the start reply lists builtins, package commands and host commands"""
    names = json.loads(started_bridge)["command_names"]

    assert {"cd", "ls", "vim"} <= set(names)


def test_run_line_returns_the_result_as_json(started_bridge: str) -> None:
    """Check that a run result round-trips with every field"""
    result = json.loads(bridge.run_line(json.dumps({"line": "echo hi"})))

    assert result["stdout"] == "hi\n"
    assert result["exit_code"] == 0
    assert result["host_call"] is None
    assert set(result) == {"stdout", "stderr", "exit_code", "cwd", "environment", "host_call"}


def test_run_line_returns_a_host_call_as_json(started_bridge: str) -> None:
    """Check that a host command comes back as a nested object with a list argv"""
    result = json.loads(bridge.run_line(json.dumps({"line": "vim a.txt"})))

    assert result["host_call"] == {"name": "vim", "argv": ["vim", "a.txt"], "redirect": None}


def test_complete_line_returns_the_completion_as_json(started_bridge: str) -> None:
    """Check that a completion result round-trips"""
    result = json.loads(bridge.complete_line(json.dumps({"line": "gre", "cursor": 3})))

    assert result == {"word_start": 0, "replacement": "grep ", "listing": []}


def test_report_host_exit_feeds_the_next_question_mark(started_bridge: str) -> None:
    """Check that a host exit code is visible to the shell"""
    bridge.report_host_exit(json.dumps({"exit_code": 7}))

    result = json.loads(bridge.run_line(json.dumps({"line": "echo $?"})))

    assert result["stdout"] == "7\n"


def test_run_line_before_start_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that using the shell before starting it is an error"""
    monkeypatch.setattr(bridge, "SHELL_SESSION", None)

    with pytest.raises(ShellNotStartedError):
        bridge.run_line(json.dumps({"line": "true"}))


def test_start_repl_returns_the_banner(started_bridge: str) -> None:
    """Check that starting the REPL yields its banner"""
    banner = json.loads(bridge.start_repl())

    assert banner.startswith("Python 3.")


def test_feed_repl_and_complete_repl_round_trip(started_bridge: str) -> None:
    """Check that REPL lines run and their names complete through the bridge"""
    bridge.start_repl()
    fed = json.loads(bridge.feed_repl(json.dumps({"line": "zeta_value = 3"})))

    completed = json.loads(bridge.complete_repl(json.dumps({"text": "zeta_v"})))

    assert fed == {"status": "done"}
    assert completed["replacement"] == "zeta_value"


def test_set_output_sink_streams_the_next_lines(started_bridge: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that a sink set on the bridge receives output and empties the result"""
    received: list[tuple[str, str]] = []
    monkeypatch.setattr(bridge, "OUTPUT_SINK", None)
    bridge.set_output_sink(lambda kind, text: received.append((kind, text)))

    result = json.loads(bridge.run_line(json.dumps({"line": "echo streamed"})))

    assert result["stdout"] == ""
    assert {kind for kind, _ in received} == {"stdout"}
    assert "".join(text for _, text in received) == "streamed\n"
