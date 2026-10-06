"""Expose the shell and REPL to a host through JSON strings"""

# Standard libraries
import dataclasses
import json

# Project libraries
from bash_purepython.shell.models import DEFAULT_TERMINAL_COLUMNS, CompletionResult, HostCommand, ShellError
from bash_purepython.shell.repl import ReplSession
from bash_purepython.shell.session import ShellSession
from bash_purepython.shell.streams import OutputSink

SHELL_SESSION: ShellSession | None = None
REPL_SESSION: ReplSession | None = None
OUTPUT_SINK: OutputSink | None = None


class ShellNotStartedError(ShellError):
    """Signal a call made before start_shell"""


def current_shell() -> ShellSession:
    """Return the running shell session

    Raises:
        ShellNotStartedError: If start_shell has not been called
    """
    if SHELL_SESSION is None:
        raise ShellNotStartedError("the shell has not been started")
    return SHELL_SESSION


def current_repl() -> ReplSession:
    """Return the running REPL session, creating it on first use"""
    global REPL_SESSION
    if REPL_SESSION is None:
        REPL_SESSION = ReplSession()
    return REPL_SESSION


def set_output_sink(sink: OutputSink | None) -> None:
    """Choose where a running line's output streams, for shells started afterwards

    Args:
        sink: A callable taking (kind, text), or None to collect output in the result
    """
    global OUTPUT_SINK
    OUTPUT_SINK = sink
    if SHELL_SESSION is not None:
        SHELL_SESSION.output_sink = sink


def start_shell(payload_json: str) -> str:
    """Create the shell session from a JSON payload

    The payload holds home, environment, history, host_commands as a list of
    {name, summary} objects, and columns

    Args:
        payload_json: The JSON-encoded payload

    Returns:
        JSON with every command name the shell knows
    """
    global SHELL_SESSION
    payload = json.loads(payload_json)
    SHELL_SESSION = ShellSession(
        home=payload["home"],
        host_commands=[HostCommand(name=entry["name"], summary=entry["summary"]) for entry in payload["host_commands"]],
        environment=payload.get("environment", {}),
        history=payload.get("history", []),
        columns=payload.get("columns") or DEFAULT_TERMINAL_COLUMNS,
        output_sink=OUTPUT_SINK,
    )
    return json.dumps({"command_names": SHELL_SESSION.all_command_names()})


def run_line(payload_json: str) -> str:
    """Run one command line in the shell

    Args:
        payload_json: JSON with line and optionally columns

    Returns:
        The JSON-encoded RunResult
    """
    payload = json.loads(payload_json)
    result = current_shell().run_line(payload["line"], payload.get("columns"))
    return json.dumps(dataclasses.asdict(result))


def index_from_utf16_offset(text: str, offset: int) -> int:
    """Return the code point index that a JavaScript string offset refers to

    Args:
        text: The text the offset points into
        offset: The offset in UTF-16 code units, as the host counts

    Returns:
        The index into the Python string, clamped to its length
    """
    units = 0
    for index, character in enumerate(text):
        if units >= offset:
            return index
        units += 2 if ord(character) > 0xFFFF else 1
    return len(text)


def utf16_offset_from_index(text: str, index: int) -> int:
    """Return the JavaScript string offset of a code point index

    Args:
        text: The text the index points into
        index: The index into the Python string

    Returns:
        The offset in UTF-16 code units
    """
    return sum(2 if ord(character) > 0xFFFF else 1 for character in text[:index])


def completion_for_host(result: CompletionResult, text: str) -> dict[str, object]:
    """Return a completion result with its word start counted the way the host counts

    Args:
        result: The completion with a code point word start
        text: The line the word start points into

    Returns:
        The fields of the result, word_start in UTF-16 code units
    """
    fields = dataclasses.asdict(result)
    fields["word_start"] = utf16_offset_from_index(text, result.word_start)
    return fields


def line_needs_more(payload_json: str) -> str:
    """Report whether the text entered so far should keep reading lines

    Args:
        payload_json: JSON with text, the lines so far joined by newlines

    Returns:
        JSON true when a quote or here-document is still open
    """
    payload = json.loads(payload_json)
    return json.dumps(current_shell().needs_more(payload["text"]))


def complete_line(payload_json: str) -> str:
    """Complete the word under the cursor of a shell line

    The cursor arrives in UTF-16 code units, as JavaScript counts, and the word
    start goes back the same way

    Args:
        payload_json: JSON with line and cursor

    Returns:
        The JSON-encoded CompletionResult
    """
    payload = json.loads(payload_json)
    line = payload["line"]
    result = current_shell().complete(line, index_from_utf16_offset(line, payload["cursor"]))
    return json.dumps(completion_for_host(result, line))


def report_host_exit(payload_json: str) -> str:
    """Record the exit code of a host command so $? reflects it

    Args:
        payload_json: JSON with exit_code

    Returns:
        JSON null
    """
    payload = json.loads(payload_json)
    current_shell().set_last_exit_code(int(payload["exit_code"]))
    return json.dumps(None)


def start_repl() -> str:
    """Start a fresh REPL session

    Returns:
        The JSON-encoded banner text
    """
    global REPL_SESSION
    REPL_SESSION = ReplSession()
    return json.dumps(REPL_SESSION.banner())


def feed_repl(payload_json: str) -> str:
    """Feed one line to the REPL

    Args:
        payload_json: JSON with line

    Returns:
        The JSON-encoded ReplFeedResult
    """
    payload = json.loads(payload_json)
    result = current_repl().feed(payload["line"])
    return json.dumps(dataclasses.asdict(result))


def complete_repl(payload_json: str) -> str:
    """Complete the end of a REPL line

    Args:
        payload_json: JSON with text, the line up to the cursor

    Returns:
        The JSON-encoded CompletionResult
    """
    payload = json.loads(payload_json)
    result = current_repl().complete(payload["text"])
    return json.dumps(completion_for_host(result, payload["text"]))
