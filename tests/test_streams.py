"""Test lazy streams and conversion between output kinds"""

# Standard libraries
from collections.abc import Generator

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.command import InputKind, OutputKind
from bash_purepython.shell_state import EXIT_CODE_BROKEN_PIPE
from bash_purepython.streams import TextStream, choose_kinds, convert


class CountingProducer:
    """Yield numbered lines forever while counting how many were pulled and whether it was closed"""

    def __init__(self):
        """Start with nothing pulled"""
        self.pulled = 0
        self.closed = False

    def lines(self) -> Generator[str, None, int]:
        """Yield lines until closed

        Returns:
            Zero when the consumer let the generator finish, which never happens for an endless producer
        """
        try:
            while True:
                self.pulled += 1
                yield f"{self.pulled}\n"
        finally:
            self.closed = True
        return 0


def finite_lines(count: int, exit_code: int) -> Generator[str, None, int]:
    """Yield a fixed number of lines then return an exit code

    Args:
        count: How many lines to yield
        exit_code: The value to return

    Returns:
        The exit code
    """
    for line_number in range(1, count + 1):
        yield f"{line_number}\n"
    return exit_code


def test_text_stream_pulls_lazily_and_closes_the_source_when_closed() -> None:
    """Check that a consumer taking three lines pulls only three and closing stops the producer"""
    producer = CountingProducer()
    stream = TextStream(producer.lines())

    taken = [line for _, line in zip(range(3), stream, strict=False)]
    stream.close()

    assert (taken, producer.pulled, producer.closed) == (["1\n", "2\n", "3\n"], 3, True)


def test_text_stream_reports_broken_pipe_when_closed_early() -> None:
    """Check that closing before exhaustion sets the broken-pipe exit code"""
    stream = TextStream(finite_lines(5, exit_code=0))

    next(iter(stream))
    stream.close()

    assert stream.exit_code == EXIT_CODE_BROKEN_PIPE


def test_text_stream_takes_exit_code_from_generator_return() -> None:
    """Check that the generator's return value becomes the exit code once exhausted"""
    stream = TextStream(finite_lines(2, exit_code=3), provisional_exit_code=0)

    text = stream.read_all()

    assert (text, stream.exit_code, stream.finished) == ("1\n2\n", 3, True)


def test_text_stream_closes_its_upstream_when_it_finishes() -> None:
    """Check that a stream feeding another is closed when the downstream one is exhausted"""
    producer = CountingProducer()
    upstream = TextStream(producer.lines())
    downstream = TextStream(finite_lines(1, exit_code=0))
    downstream.upstream = upstream
    next(iter(upstream))

    downstream.read_all()

    assert (producer.closed, upstream.finished) == (True, True)


@pytest.mark.parametrize(
    ("producer_kinds", "consumer_kinds", "expected"),
    [
        (
            frozenset({OutputKind.STREAM_TEXT}),
            frozenset({InputKind.STREAM_TEXT, InputKind.TEXT}),
            (OutputKind.STREAM_TEXT, InputKind.STREAM_TEXT),
        ),
        (
            frozenset({OutputKind.TEXT, OutputKind.STREAM_TEXT}),
            frozenset({InputKind.TEXT}),
            (OutputKind.TEXT, InputKind.TEXT),
        ),
        (
            frozenset({OutputKind.TEXT}),
            frozenset({InputKind.STREAM_TEXT}),
            (OutputKind.TEXT, InputKind.STREAM_TEXT),
        ),
        (
            frozenset({OutputKind.STREAM_BYTES}),
            frozenset({InputKind.STREAM_TEXT, InputKind.ARGUMENTS}),
            (OutputKind.STREAM_BYTES, InputKind.STREAM_TEXT),
        ),
    ],
    ids=[
        "shared_stream_wins",
        "shared_static_when_consumer_cannot_stream",
        "convert_static_to_stream",
        "bytes_to_text",
    ],
)
def test_choose_kinds_prefers_a_shared_streaming_kind(
    producer_kinds: frozenset[OutputKind], consumer_kinds: frozenset[InputKind], expected: tuple[OutputKind, InputKind]
) -> None:
    """Check that negotiation picks a shared kind, streaming first, and otherwise converts"""
    assert choose_kinds(producer_kinds, consumer_kinds) == expected


@pytest.mark.parametrize(
    ("value", "from_kind", "to_kind", "expected"),
    [
        ("ab", OutputKind.TEXT, OutputKind.BYTES, b"ab"),
        (b"ab", OutputKind.BYTES, OutputKind.TEXT, "ab"),
        (iter(["a", "b"]), OutputKind.STREAM_TEXT, OutputKind.TEXT, "ab"),
        (iter([b"a", b"b"]), OutputKind.STREAM_BYTES, OutputKind.TEXT, "ab"),
        ("ab", OutputKind.TEXT, OutputKind.STREAM_TEXT, ["ab"]),
        (iter(["a", "b"]), OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES, [b"a", b"b"]),
        (iter([b"a", b"\xff"]), OutputKind.STREAM_BYTES, OutputKind.STREAM_TEXT, ["a", "�"]),
    ],
    ids=[
        "text_to_bytes",
        "bytes_to_text",
        "stream_text_to_text",
        "stream_bytes_to_text",
        "text_to_stream",
        "stream_text_to_stream_bytes",
        "stream_bytes_to_stream_text_replaces_bad_bytes",
    ],
)
def test_convert_reshapes_between_kinds(
    value: object, from_kind: OutputKind, to_kind: OutputKind, expected: object
) -> None:
    """Check that every supported conversion yields the same data in the new kind"""
    converted = convert(value, from_kind, to_kind)

    assert (list(converted) if isinstance(expected, list) else converted) == expected


def test_convert_between_streams_stays_lazy() -> None:
    """Check that converting a stream of text to bytes pulls nothing until the result is iterated"""
    producer = CountingProducer()

    converted = convert(producer.lines(), OutputKind.STREAM_TEXT, OutputKind.STREAM_BYTES)
    first = next(converted)

    assert (first, producer.pulled) == (b"1\n", 1)
