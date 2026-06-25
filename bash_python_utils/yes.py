"""PurePython implementation of the bash yes command"""

# Standard libraries
import sys
from argparse import ArgumentParser


def main():
    parser = ArgumentParser(prog="yes", description="Print a string repeatedly until killed")
    parser.add_argument("words", nargs="*", default=["y"], help="Strings to print (default 'y')")
    args = parser.parse_args()

    line = (" ".join(args.words) if args.words else "y") + "\n"
    try:
        while True:
            sys.stdout.write(line)
    except (BrokenPipeError, KeyboardInterrupt):
        return


if __name__ == "__main__":
    main()
