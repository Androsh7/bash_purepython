"""Run an interactive Python session one line at a time"""

# Standard libraries
import code
import os
import re
import rlcompleter
import sys
from typing import Any

# Project libraries
from bash_purepython.shell.models import REPL_INDENT_WIDTH_SPACES, CompletionResult, ReplFeedResult, ReplStatus

EXIT_REQUESTS = frozenset({"exit()", "quit()", "exit", "quit"})
TRAILING_NAME = re.compile(r"[\w.]*$")
SOURCE_FILENAME = "<stdin>"


def name_completion_result(start: int, name: str, values: list[str]) -> CompletionResult:
    """Return the completion for a Python name given its candidate values

    Args:
        start: Where the name begins in the line
        name: The name typed so far
        values: Every candidate the completer produced

    Returns:
        The single candidate, a longer common prefix, or a listing
    """
    if not values:
        return CompletionResult(word_start=start, replacement=None, listing=())
    if len(values) == 1:
        return CompletionResult(word_start=start, replacement=values[0], listing=())
    common = os.path.commonprefix(values)
    if len(common) > len(name):
        return CompletionResult(word_start=start, replacement=common, listing=())
    return CompletionResult(word_start=start, replacement=None, listing=tuple(values))


class ReplInterpreter(code.InteractiveInterpreter):
    """Run statements the way the standard interactive interpreter does, noting syntax errors"""

    def __init__(self, session_globals: dict[str, Any]):
        """Bind the interpreter to the session's globals

        Args:
            session_globals: The namespace statements run in
        """
        super().__init__(session_globals)
        self.syntax_error_seen = False

    def showsyntaxerror(self, filename: str | None = None, **keyword_arguments: Any) -> None:
        """Print the syntax error the way the interpreter does and remember that one happened

        Args:
            filename: The name to show for the source
            keyword_arguments: Extra arguments newer Python versions pass through
        """
        self.syntax_error_seen = True
        super().showsyntaxerror(filename, **keyword_arguments)


class ReplSession:
    """Hold the globals and the pending lines of one interactive session"""

    def __init__(self):
        """Start with empty globals, as a fresh interpreter would"""
        self._globals: dict[str, Any] = {"__name__": "__main__", "__doc__": None}
        self._interpreter = ReplInterpreter(self._globals)
        self._pending_lines: list[str] = []

    def banner(self) -> str:
        """Return the lines printed when the session opens"""
        version = sys.version.split()[0]
        return f'Python {version} on {sys.platform}\nType "help", "copyright", "credits" or "exit()" to leave the REPL.'

    def feed(self, line: str) -> ReplFeedResult:
        """Accept one line, running the statement once it is complete

        Output and tracebacks go to the real sys.stdout and sys.stderr so the host can
        stream them, and both are flushed before returning. An exit request is only
        honoured at the top level, not inside a pending block

        Args:
            line: The line as typed, without its newline

        Returns:
            Whether more input is needed, the statement ran, it failed to compile, or exit was requested
        """
        if not self._pending_lines and line.strip() in EXIT_REQUESTS:
            return ReplFeedResult(status=ReplStatus.EXIT)
        self._pending_lines.append(line)
        source = "\n".join(self._pending_lines)
        self._interpreter.syntax_error_seen = False
        try:
            needs_more = self._interpreter.runsource(source, SOURCE_FILENAME, "single")
        except SystemExit:
            self._pending_lines = []
            return ReplFeedResult(status=ReplStatus.EXIT)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
        if needs_more:
            return ReplFeedResult(status=ReplStatus.MORE)
        self._pending_lines = []
        if self._interpreter.syntax_error_seen:
            return ReplFeedResult(status=ReplStatus.ERROR)
        return ReplFeedResult(status=ReplStatus.DONE)

    def complete(self, text_before_cursor: str) -> CompletionResult:
        """Return the completion for the end of a REPL line

        A blank prefix indents by one level, otherwise the trailing dotted name is
        completed against the session globals

        Args:
            text_before_cursor: The line up to the cursor

        Returns:
            A replacement for the trailing name or a listing of candidates
        """
        if not text_before_cursor.strip():
            return CompletionResult(
                word_start=len(text_before_cursor), replacement=" " * REPL_INDENT_WIDTH_SPACES, listing=()
            )
        match = TRAILING_NAME.search(text_before_cursor)
        name = match.group(0) if match else ""
        start = match.start() if match else len(text_before_cursor)
        if not name:
            return CompletionResult(word_start=start, replacement=None, listing=())
        completer = rlcompleter.Completer(self._globals)
        values: list[str] = []
        state = 0
        while (candidate := completer.complete(name, state)) is not None:
            if candidate not in values:
                values.append(candidate)
            state += 1
        return name_completion_result(start, name, values)
