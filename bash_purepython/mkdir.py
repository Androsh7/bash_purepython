"""PurePython implementation of the bash mkdir command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error


def main():
    parser = ArgumentParser(prog="mkdir", description="Create directories")
    parser.add_argument("-p", "--parents", action="store_true", help="Create parents as needed; no error if existing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print created paths")
    parser.add_argument("paths", nargs="+", help="Directories to create")
    args = parser.parse_args()

    for path_str in args.paths:
        path = Path(path_str)
        try:
            path.mkdir(parents=args.parents, exist_ok=args.parents)
        except FileExistsError:
            print_error(f"{path}: File exists")
        except FileNotFoundError:
            print_error(f"{path}: No such file or directory (use -p)")
        if args.verbose:
            print(f"created directory {path}")


if __name__ == "__main__":
    main()
