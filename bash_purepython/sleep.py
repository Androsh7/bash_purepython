"""PurePython implementation of the bash sleep command"""

# Standard libraries
import time
from argparse import ArgumentParser

# Project libraries
from bash_purepython._color import print_error

SUFFIXES = {"s": 1, "m": 60, "h": 3600, "d": 86400}
SLICE_S = 0.05


def parse_duration(spec: str) -> float:
    """Return the number of seconds a duration string names

    Args:
        spec: A number with an optional s, m, h, or d suffix

    Returns:
        The duration in seconds
    """
    if not spec:
        print_error("missing duration")
    multiplier = 1
    if spec[-1] in SUFFIXES:
        multiplier = SUFFIXES[spec[-1]]
        spec = spec[:-1]
    try:
        return float(spec) * multiplier
    except ValueError:
        print_error(f"invalid duration: {spec}")
        return 0.0


def sleep_interruptibly(total_s: float) -> None:
    """Sleep for a duration in short slices, so an interrupt is noticed between them

    A single long time.sleep cannot be interrupted on every platform; under Pyodide
    it blocks the worker until it returns

    Args:
        total_s: How long to sleep in total
    """
    deadline = time.monotonic() + total_s
    while True:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            return
        time.sleep(min(SLICE_S, remaining_s))


def main():
    """Sleep for the total of the given durations"""
    parser = ArgumentParser(prog="sleep", description="Sleep for the given duration")
    parser.add_argument("durations", nargs="+", help="Durations (e.g. 1.5, 2s, 3m, 1h)")
    args = parser.parse_args()

    sleep_interruptibly(sum(parse_duration(duration) for duration in args.durations))


if __name__ == "__main__":
    main()
