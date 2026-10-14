"""Decide whether the lines typed so far form a complete command or the shell should ask for another"""

# Project libraries
from bash_purepython.parse_script import ScriptSplitter

TRAILING_LIST_OPERATORS = ("&&", "||", "|&", "|")


def script_needs_more_lines(text: str) -> bool:
    """Return whether an interactive shell would prompt for another line before running the text

    The text is scanned the way the engine splits a script. It is unfinished while a quote, backtick,
    ``$( )``, ``${ }``, ``( )``, ``{ }``, ``[[ ]]`` or compound command is still open, a here-document has
    not reached its delimiter, the last line ends in a backslash, or the last command ends in ``|``, ``|&``,
    ``&&`` or ``||`` with nothing after it

    Args:
        text: The lines entered so far, joined by newlines

    Returns:
        True when another line is needed
    """
    splitter = ScriptSplitter(text)
    blocks = splitter.split()
    if (
        splitter.nesting
        or splitter.pending_heredocs
        or splitter.unterminated_heredoc
        or splitter.unclosed_quote
        or splitter.unclosed_conditional
        or splitter.trailing_backslash
    ):
        return True
    return bool(blocks) and blocks[-1].command.rstrip().endswith(TRAILING_LIST_OPERATORS)
