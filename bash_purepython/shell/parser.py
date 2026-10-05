"""Group tokens into pipelines joined by chain operators"""

# Standard libraries
import dataclasses

# Project libraries
from bash_purepython.shell.models import (
    ChainOperator,
    CommandList,
    IncompleteInputError,
    RawCommand,
    RawPipeline,
    RawRedirects,
    RawWord,
    ShellSyntaxError,
    Token,
    TokenKind,
)
from bash_purepython.shell.tokenizer import split_first_line, tokenize

CHAIN_OPERATORS = {
    TokenKind.AND: ChainOperator.AND,
    TokenKind.OR: ChainOperator.OR,
    TokenKind.SEMICOLON: ChainOperator.SEMICOLON,
}
REDIRECTS_WITH_TARGET = {
    TokenKind.REDIRECT_WRITE,
    TokenKind.REDIRECT_APPEND,
    TokenKind.REDIRECT_STDERR_WRITE,
    TokenKind.REDIRECT_STDERR_APPEND,
    TokenKind.REDIRECT_BOTH,
    TokenKind.REDIRECT_INPUT,
    TokenKind.HEREDOC,
    TokenKind.HEREDOC_STRIP_TABS,
}


def apply_redirect(redirects: RawRedirects, kind: TokenKind, target: RawWord | None) -> RawRedirects:
    """Return the redirects with one more operator applied, in the order bash applies them

    2>&1 sends stderr wherever stdout goes at that point: a file named earlier on the
    line, or the pipe or terminal when none was. A > that comes later moves only stdout

    Args:
        redirects: The redirects gathered so far
        kind: The redirect operator
        target: The word after it, or None for 2>&1

    Returns:
        The updated redirects
    """
    if kind == TokenKind.REDIRECT_WRITE:
        return RawRedirects(
            stdout_target=target,
            stdout_append=False,
            stderr_target=redirects.stderr_target,
            stderr_append=redirects.stderr_append,
            stderr_to_stdout=redirects.stderr_to_stdout,
            stdin_source=redirects.stdin_source,
        )
    if kind == TokenKind.REDIRECT_APPEND:
        return RawRedirects(
            stdout_target=target,
            stdout_append=True,
            stderr_target=redirects.stderr_target,
            stderr_append=redirects.stderr_append,
            stderr_to_stdout=redirects.stderr_to_stdout,
            stdin_source=redirects.stdin_source,
        )
    if kind == TokenKind.REDIRECT_STDERR_WRITE:
        return RawRedirects(
            stdout_target=redirects.stdout_target,
            stdout_append=redirects.stdout_append,
            stderr_target=target,
            stderr_append=False,
            stderr_to_stdout=False,
            stdin_source=redirects.stdin_source,
        )
    if kind == TokenKind.REDIRECT_STDERR_APPEND:
        return RawRedirects(
            stdout_target=redirects.stdout_target,
            stdout_append=redirects.stdout_append,
            stderr_target=target,
            stderr_append=True,
            stderr_to_stdout=False,
            stdin_source=redirects.stdin_source,
        )
    if kind == TokenKind.REDIRECT_STDERR_TO_STDOUT:
        return RawRedirects(
            stdout_target=redirects.stdout_target,
            stdout_append=redirects.stdout_append,
            stderr_target=redirects.stdout_target,
            stderr_append=redirects.stdout_append,
            stderr_to_stdout=redirects.stdout_target is None,
            stdin_source=redirects.stdin_source,
        )
    if kind == TokenKind.REDIRECT_BOTH:
        return RawRedirects(
            stdout_target=target,
            stdout_append=False,
            stderr_target=target,
            stderr_append=False,
            stderr_to_stdout=False,
            stdin_source=redirects.stdin_source,
        )
    if kind in (TokenKind.HEREDOC, TokenKind.HEREDOC_STRIP_TABS):
        return dataclasses.replace(
            redirects,
            stdin_source=None,
            heredoc_delimiter=target,
            heredoc_strip_tabs=kind == TokenKind.HEREDOC_STRIP_TABS,
        )
    return dataclasses.replace(redirects, stdin_source=target, heredoc_delimiter=None)


def delimiter_text(word: RawWord) -> str:
    """Return the literal text of a here-document delimiter, quotes removed

    Args:
        word: The word after <<

    Returns:
        The delimiter to look for
    """
    return "".join(part.text for part in word.parts)


def attach_heredoc_bodies(command_list: CommandList, lines: list[str]) -> CommandList:
    """Return the list with each << fed the lines up to its delimiter, in order

    Args:
        command_list: The parsed command line
        lines: The lines that followed it

    Raises:
        IncompleteInputError: If a here-document never reaches its delimiter
        ShellSyntaxError: If lines remain after the last here-document

    Returns:
        The command list with every heredoc_body filled in
    """
    remaining = list(lines)
    pipelines = []
    for pipeline in command_list.pipelines:
        commands = []
        for command in pipeline.commands:
            delimiter = command.redirects.heredoc_delimiter
            if delimiter is None:
                commands.append(command)
                continue
            wanted = delimiter_text(delimiter)
            strip_tabs = command.redirects.heredoc_strip_tabs
            body_lines: list[str] = []
            while True:
                if not remaining:
                    raise IncompleteInputError(f"here-document delimited by {wanted} is not terminated")
                line = remaining.pop(0)
                if strip_tabs:
                    line = line.lstrip("\t")
                if line == wanted:
                    break
                body_lines.append(line)
            body = "".join(line + "\n" for line in body_lines)
            commands.append(
                RawCommand(words=command.words, redirects=dataclasses.replace(command.redirects, heredoc_body=body))
            )
        pipelines.append(RawPipeline(commands=tuple(commands)))
    if any(line.strip() for line in remaining):
        raise ShellSyntaxError("unexpected text after the last here-document")
    return CommandList(pipelines=tuple(pipelines), operators=command_list.operators)


def parse_text(text: str) -> CommandList:
    """Return the command list for everything the user entered, here-documents included

    Args:
        text: The command line and any here-document lines, joined by newlines

    Raises:
        IncompleteInputError: If a quote or here-document is left open
        ShellSyntaxError: If the text cannot be parsed

    Returns:
        The parsed line with every here-document body attached
    """
    first_line, lines = split_first_line(text)
    command_list = parse(tokenize(first_line))
    needs_bodies = any(
        command.redirects.heredoc_delimiter is not None
        for pipeline in command_list.pipelines
        for command in pipeline.commands
    )
    if not needs_bodies and any(line.strip() for line in lines):
        raise ShellSyntaxError("unexpected text after the command line")
    return attach_heredoc_bodies(command_list, lines) if needs_bodies else command_list


def parse_simple_command(tokens: list[Token], index: int) -> tuple[RawCommand, int]:
    """Return the command starting at index and the index of the token after it

    Args:
        tokens: The whole token list
        index: The position of the command's first token

    Raises:
        ShellSyntaxError: If the command has no words or a redirect has no target

    Returns:
        The command and the position of the next operator or the end
    """
    words: list[RawWord] = []
    redirects = RawRedirects()
    while index < len(tokens):
        token = tokens[index]
        if token.kind == TokenKind.WORD and token.word is not None:
            words.append(token.word)
            index += 1
            continue
        if token.kind == TokenKind.REDIRECT_STDERR_TO_STDOUT:
            redirects = apply_redirect(redirects, token.kind, None)
            index += 1
            continue
        if token.kind in REDIRECTS_WITH_TARGET:
            if index + 1 >= len(tokens) or tokens[index + 1].word is None:
                raise ShellSyntaxError(f"syntax error: missing target after {token.value}")
            redirects = apply_redirect(redirects, token.kind, tokens[index + 1].word)
            index += 2
            continue
        break
    if not words:
        unexpected = tokens[index].value if index < len(tokens) else "newline"
        raise ShellSyntaxError(f"syntax error near unexpected token '{unexpected}'")
    return RawCommand(words=tuple(words), redirects=redirects), index


def parse_pipeline(tokens: list[Token], index: int) -> tuple[RawPipeline, int]:
    """Return the pipeline starting at index and the index of the token after it

    Args:
        tokens: The whole token list
        index: The position of the pipeline's first token

    Raises:
        ShellSyntaxError: If a pipe has no command on either side

    Returns:
        The pipeline and the position of the next chain operator or the end
    """
    commands: list[RawCommand] = []
    while True:
        command, index = parse_simple_command(tokens, index)
        commands.append(command)
        if index < len(tokens) and tokens[index].kind == TokenKind.PIPE:
            index += 1
            continue
        return RawPipeline(commands=tuple(commands)), index


def parse(tokens: list[Token]) -> CommandList:
    """Return the pipelines of a tokenized line and the operators that join them

    A trailing ; is accepted and ignored

    Args:
        tokens: The tokens of one command line, at least one of them

    Raises:
        ShellSyntaxError: If an operator is missing a command on either side or a redirect has no target

    Returns:
        The pipelines in order with one chain operator between each pair
    """
    pipelines: list[RawPipeline] = []
    operators: list[ChainOperator] = []
    index = 0
    while True:
        pipeline, index = parse_pipeline(tokens, index)
        pipelines.append(pipeline)
        if index >= len(tokens):
            break
        operator = CHAIN_OPERATORS[tokens[index].kind]
        index += 1
        if index >= len(tokens):
            if operator == ChainOperator.SEMICOLON:
                break
            raise ShellSyntaxError("syntax error near unexpected token 'newline'")
        operators.append(operator)
    return CommandList(pipelines=tuple(pipelines), operators=tuple(operators))
