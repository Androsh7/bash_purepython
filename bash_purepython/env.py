"""PurePython implementation of the bash env command"""

# Standard libraries
import os
from argparse import ArgumentParser


def main():
    parser = ArgumentParser(prog="env", description="Print the environment")
    parser.add_argument("-0", dest="null", action="store_true", help="Terminate entries with NUL instead of newline")
    args = parser.parse_args()

    sep = "\0" if args.null else "\n"
    print(sep.join(f"{k}={v}" for k, v in os.environ.items()), end=sep)


if __name__ == "__main__":
    main()
