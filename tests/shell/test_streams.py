"""Tests for the streams commands are bound to"""

# Standard libraries
import contextlib

# Project libraries
from bash_purepython.shell.models import OutputLimitExceededError
from bash_purepython.shell.streams import OutputCapture, make_sink_stream


def test_sink_stream_forwards_text_as_it_is_written() -> None:
    """Check that every write reaches the sink immediately with its kind"""
    received: list[tuple[str, str]] = []
    stream = make_sink_stream(lambda kind, text: received.append((kind, text)), "stdout")

    stream.write("one\n")
    stream.write("two")

    assert received == [("stdout", "one\n"), ("stdout", "two")]


def test_sink_stream_forwards_bytes_written_through_the_buffer() -> None:
    """Check that binary writes are decoded and forwarded in order with text writes"""
    received: list[str] = []
    stream = make_sink_stream(lambda _kind, text: received.append(text), "stdout")

    stream.write("a")
    stream.buffer.write(b"b")
    stream.write("c")

    assert "".join(received) == "abc"


def test_sink_stream_keeps_a_split_multibyte_character_until_it_is_complete() -> None:
    """Check that a character split across two writes is not replaced"""
    received: list[str] = []
    stream = make_sink_stream(lambda _kind, text: received.append(text), "stdout")
    encoded = "é".encode()

    stream.buffer.write(encoded[:1])
    stream.buffer.write(encoded[1:])

    assert "".join(received) == "é"


def test_output_capture_records_an_overflow() -> None:
    """Check that a write past the limit is refused and remembered"""
    capture = OutputCapture(limit_bytes=4)

    capture.stream.write("abcd")
    with contextlib.suppress(OutputLimitExceededError):
        capture.stream.write("e")

    assert capture.overflowed
    assert capture.getvalue() == b"abcd"
