"""PurePython implementation of the bash touch command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils.color import print_error


def main():
    parser = ArgumentParser(prog="touch", description="Creates an empty file at the given path")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite any existing file with the same name")
    parser.add_argument("path", type=str, help="Path for the file to create")
    args = parser.parse_args()
    file_path = Path(args.path)
    if file_path.is_dir():
        print_error(f'Path "{file_path.resolve()}" is a directory')
    try:
        file_path.touch(exist_ok=args.force)
    except FileExistsError:
        print_error(f'File "{file_path.resolve()}" already exists')


if __name__ == "__main__":
    main()
