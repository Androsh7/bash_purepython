"""PurePython implementation of the bash which command"""

# Standard libraries
import shutil
import sys
from argparse import ArgumentParser


def main():
    parser = ArgumentParser(prog="which", description="Locate an executable in PATH")
    parser.add_argument("-a", "--all", action="store_true", help="Print all matches, not just the first")
    parser.add_argument("names", nargs="+", help="Executables to find")
    args = parser.parse_args()

    exit_code = 0
    for name in args.names:
        found = shutil.which(name)
        if not found:
            exit_code = 1
            continue
        print(found)
        if not args.all:
            continue
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
