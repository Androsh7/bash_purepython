"""PurePython implementation of the bash realpath command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils.color import print_error


def main():
    parser = ArgumentParser(prog="realpath", description="Print the resolved absolute path")
    parser.add_argument("-e", "--canonicalize-existing", action="store_true", help="All components must exist")
    parser.add_argument("paths", nargs="+", help="Paths to resolve")
    args = parser.parse_args()

    for path_str in args.paths:
        path = Path(path_str)
        if args.canonicalize_existing and not path.exists():
            print_error(f"{path}: No such file or directory")
        print(path.resolve())


if __name__ == "__main__":
    main()
