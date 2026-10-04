"""Group tokens into pipelines joined by chain operators"""

# Project libraries
from bash_purepython.shell.models import (
    ChainOperator,
    CommandList,
    Pipeline,
    Redirect,
    ShellSyntaxError,
    SimpleCommand,
    Token,
    TokenKind,
)

CHAIN_OPERATORS = {
    TokenKind.AND: ChainOperator.AND,
    TokenKind.OR: ChainOperator.OR,
    TokenKind.SEMICOLON: ChainOperator.SEMICOLON,
}
REDIRECT_KINDS = {TokenKind.REDIRECT_WRITE, TokenKind.REDIRECT_APPEND}


def parse_simple_command(tokens: list[Token], index: int) -> tuple[SimpleCommand | None, int]:
    """Return the command starting at index and the index of the token after it

    Args:
        tokens: The whole token list
        index: The position of the command's first token

    Raises:
        ShellSyntaxError: If a redirect has no target or stands without a command

    Returns:
        The command, or None when there are no words before the next operator, and the
        position of that operator or the end
    """
    argv: list[str] = []
    redirect = None
    while index < len(tokens):
        token = tokens[index]
        if token.kind == TokenKind.WORD:
            argv.append(token.value)
            index += 1
            continue
        if token.kind in REDIRECT_KINDS:
            if index + 1 >= len(tokens) or tokens[index + 1].kind != TokenKind.WORD:
                raise ShellSyntaxError("syntax error: missing redirect target")
            redirect = Redirect(target=tokens[index + 1].value, append=token.kind == TokenKind.REDIRECT_APPEND)
            index += 2
            continue
        break
    if not argv:
        if redirect is not None:
            raise ShellSyntaxError("syntax error: redirect without a command")
        return None, index
    return SimpleCommand(argv=tuple(argv), redirect=redirect), index


def parse_pipeline(tokens: list[Token], index: int) -> tuple[Pipeline, int]:
    """Return the pipeline starting at index and the index of the token after it

    A lone command that expanded to no words is an empty pipeline, which runs nothing

    Args:
        tokens: The whole token list
        index: The position of the pipeline's first token

    Raises:
        ShellSyntaxError: If a pipe has no command on either side

    Returns:
        The pipeline and the position of the next chain operator or the end
    """
    commands: list[SimpleCommand] = []
    while True:
        command, index = parse_simple_command(tokens, index)
        piped = index < len(tokens) and tokens[index].kind == TokenKind.PIPE
        if command is None and (commands or piped):
            raise ShellSyntaxError("syntax error near unexpected token '|'")
        if command is not None:
            commands.append(command)
        if piped:
            index += 1
            continue
        return Pipeline(commands=tuple(commands)), index


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
    pipelines: list[Pipeline] = []
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
