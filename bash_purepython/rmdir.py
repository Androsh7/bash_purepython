"""PurePython implementation of the bash rmdir command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def main():
    parser = ArgumentParser(prog="rmdir", description="Remove empty directories")
    parser.add_argument("-p", "--parents", action="store_true", help="Remove empty parent directories")
    parser.add_argument("paths", nargs="+", help="Directories to remove")
    args = parser.parse_args()

    for path_str in args.paths:
        path = Path(path_str)
        if not path.exists():
            print_error(f"{path}: No such file or directory")
        if not path.is_dir():
            print_error(f"{path}: Not a directory")
        try:
            path.rmdir()
        except OSError:
            print_error(f"{path}: Directory not empty")
        if args.parents:
            parent = path.parent
            while parent != parent.parent:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent


if __name__ == "__main__":
    main()
