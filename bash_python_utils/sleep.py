"""PurePython implementation of the bash sleep command"""

# Standard libraries
import time
from argparse import ArgumentParser

# Project libraries
from bash_python_utils.color import print_error

SUFFIXES = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(spec: str) -> float:
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


def main():
    parser = ArgumentParser(prog="sleep", description="Sleep for the given duration")
    parser.add_argument("durations", nargs="+", help="Durations (e.g. 1.5, 2s, 3m, 1h)")
    args = parser.parse_args()

    total = sum(parse_duration(d) for d in args.durations)
    time.sleep(total)


if __name__ == "__main__":
    main()
