"""Test the file command through the shell"""

# Standard libraries
import gzip
import struct
import zipfile
from collections.abc import Callable
from pathlib import Path

# Third-party libraries
import pytest

# Project libraries
from bash_purepython.command.file import FileCommand, describe_bytes
from bash_purepython.command.registry import COMMAND_CLASSES, CommandRegistry
from tests.conftest import ShellHarness

ELF_64_LSB_EXECUTABLE = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9) + struct.pack("<HH", 2, 0x3E) + bytes(44)
PNG_ONE_BY_TWO = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1, 2) + bytes(5)
PE32_PLUS = b"MZ" + bytes(0x3C - 2) + struct.pack("<I", 0x40) + b"PE\0\0" + struct.pack("<H", 0x8664) + bytes(18)


@pytest.fixture
def shell(make_shell: Callable[[CommandRegistry], ShellHarness]) -> ShellHarness:
    """Return a harness whose registry also holds file"""
    return make_shell(CommandRegistry([*(command_class() for command_class in COMMAND_CLASSES), FileCommand()]))


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (b"", "empty"),
        (b"hello\n", "ASCII text"),
        (b"hello", "ASCII text, with no line terminators"),
        (b"hello\r\nworld\r\n", "ASCII text, with CRLF line terminators"),
        ("héllo\n".encode(), "UTF-8 Unicode text"),
        (b"\x00\x01\x02\x03", "data"),
        (b"\xff\xfe\xfd", "data"),
        (ELF_64_LSB_EXECUTABLE, "ELF 64-bit LSB executable"),
        (PNG_ONE_BY_TWO, "PNG image data, 1 x 2"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "JPEG image data"),
        (gzip.compress(b"x"), "gzip compressed data"),
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "PDF document, version 1.7"),
        (PE32_PLUS, "PE32+ executable"),
        (b"#!/usr/bin/env python3\nprint('hi')\n", "a python3 script, ASCII text executable"),
        (b"#!/bin/bash\necho hi\n", "a bash script, ASCII text executable"),
    ],
    ids=[
        "empty",
        "ascii",
        "ascii without newline",
        "ascii crlf",
        "utf-8",
        "binary",
        "invalid utf-8",
        "elf",
        "png",
        "jpeg",
        "gzip",
        "pdf",
        "pe32 plus",
        "env script",
        "bash script",
    ],
)
def test_describe_bytes_recognises_each_kind(sample: bytes, expected: str) -> None:
    """Check that the magic bytes and text heuristics name each kind the way file does"""
    assert describe_bytes(sample) == expected


def test_file_prints_the_name_before_the_description(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that each path is printed with its description"""
    (tmp_path / "a.txt").write_bytes(b"hello\n")
    (tmp_path / "dir").mkdir()

    run = shell.run("file a.txt dir")

    assert (run.stdout, run.exit_code) == ("a.txt: ASCII text\ndir: directory\n", 0)


def test_file_recognises_a_zip_archive(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that a real zip archive is named as one"""
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as archive:
        archive.writestr("a.txt", "a")

    run = shell.run("file a.zip")

    assert run.stdout == "a.zip: Zip archive data\n"


def test_file_brief_leaves_out_the_name(shell: ShellHarness, tmp_path: Path) -> None:
    """Check that -b prints only the description"""
    (tmp_path / "a.txt").write_bytes(b"hello\n")

    run = shell.run("file -b a.txt")

    assert run.stdout == "ASCII text\n"


def test_file_reports_a_missing_path(shell: ShellHarness) -> None:
    """Check that a missing path is reported on its own line with exit code one"""
    run = shell.run("file missing")

    assert run.exit_code == 1
    assert run.stdout == "missing: cannot open 'missing' (No such file or directory)\n"
