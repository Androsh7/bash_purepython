"""PurePython implementation of the bash ls command"""

# Standard libraries
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import Color, print_error


def main():
    parser = ArgumentParser(prog="ls", description="List files in the given directory/directories")
    parser.add_argument("-l", "--long", action="store_true", help="Prints a long listing of files")
    parser.add_argument("-a", "--all", action="store_true", help="Prints all files including hidden ones")
    parser.add_argument("-r", "--recursive", action="store_true", help="Prints all files recursively")
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to list")

    args = parser.parse_args()

    # Validate the path list
    path_list = [Path(path_str) for path_str in args.paths]
    for path in path_list:
        if not path.exists():
            print_error(f"FileNotFound: {path}", Color.RED)
            sys.exit(1)

    # Find all files in the list
    file_list: list[Path] = []
    for path in path_list:
        if args.recursive:
            file_list.extend(path.rglob("*", recurse_symlinks=False))
        else:
            file_list.extend(file_path for file_path in path.iterdir())

    # Exclude "hidden" files if the all flag is not set
    if not args.all:
        trimmed_list = []
        for file_path in file_list:
            if str(file_path).startswith("."):
                continue
            trimmed_list.append(file_path)
        file_list = trimmed_list

    # Printing the file list
    file_list.sort()
    if not args.long:
        for file_path in file_list:
            print(str(file_path), end="  ")
    else:
        for file_path in file_list:
            print(f"{'d' if file_path.is_dir() else 'f'} {file_path.stat().st_size} {file_path}")


if __name__ == "__main__":
    main()
