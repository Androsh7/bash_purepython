"""PurePython implementation of the bash echo command"""

# Standard libraries
import sys
from argparse import ArgumentParser


def main():
    parser = ArgumentParser(prog="echo", description="Print arguments to stdout")
    parser.add_argument("-n", dest="no_newline", action="store_true", help="Do not print trailing newline")
    parser.add_argument("-e", dest="escapes", action="store_true", help="Interpret backslash escapes")
    parser.add_argument("words", nargs="*", help="Strings to print")
    args = parser.parse_args()

    text = " ".join(args.words)
    if args.escapes:
        text = text.encode("utf-8").decode("unicode_escape")
    sys.stdout.write(text)
    if not args.no_newline:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
