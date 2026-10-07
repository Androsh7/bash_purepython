"""Test the date command through the shell"""

# Standard libraries
import re

# Project libraries
from tests.conftest import ShellHarness


def test_date_formats_with_a_plus_format(shell: ShellHarness) -> None:
    """Check that a + format is applied"""
    run = shell.run("date +%Y")

    assert re.fullmatch(r"\d{4}\n", run.stdout)


def test_date_default_output_names_the_year(shell: ShellHarness) -> None:
    """Check that the default format ends with the four-digit year"""
    run = shell.run("date -u")

    assert re.search(r"\d{4}\n$", run.stdout)
